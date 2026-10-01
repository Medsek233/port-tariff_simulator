"""
pmis.py — Connecteur PMIS (Port Management Information System)

- Authentification par TOKEN (login / refresh), appels Bearer.
- Récupération des visites (/pmisBackend/api/visits) avec filtres.
- Conversion d'une visite PMIS en escale + lignes de facture, en réutilisant le
  moteur de tarification (billing) et les tarifs NWM (tarifs_data).

⚠️ Aucun secret n'est stocké dans le code. Les paramètres de connexion sont lus
depuis les *secrets* de l'application Streamlit (Settings → Secrets) ou, à défaut,
depuis les variables d'environnement. Voir .streamlit/secrets.toml.example.

Règles métier convenues :
- Services facturés = droits de port (nautique/port/stationnement) + PILOTAGE.
  Les remorqueurs (TOWG) et le lamanage/amarrage (MOOR) sont EXCLUS.
- Pilotage : activity_type « annulation » ⇒ majoration +100 %.
- Terminal déduit du nom du poste (préfixe) — mapping éditable côté app.
- VG basé sur le tirant « max_static_draught_full_load » du navire.
"""
from __future__ import annotations

import json
import math
import os
import time

import requests

import billing
import tarifs_data as td


# ═══════════════════════════════════════════════════════════════════════════════
#  CONFIGURATION (secrets Streamlit → variables d'environnement)
# ═══════════════════════════════════════════════════════════════════════════════
def _secret(key: str, default=None):
    """Lit un paramètre PMIS depuis st.secrets['pmis'][key] puis PMIS_<KEY>."""
    try:
        import streamlit as st
        sec = st.secrets.get("pmis", {}) if hasattr(st, "secrets") else {}
        if key in sec:
            return sec[key]
    except Exception:
        pass
    return os.environ.get("PMIS_" + key.upper(), default)


class PMISError(Exception):
    pass


def _clean_base(url, *strip_suffixes) -> str:
    """Normalise une URL de base : retire les / superflus et les suffixes de
    endpoint collés par erreur (ex. '.../api/login' → '.../api')."""
    u = (str(url or "")).strip().rstrip("/")
    changed = True
    while changed:
        changed = False
        for suf in strip_suffixes:
            if u.lower().endswith("/" + suf.lower()):
                u = u[: -(len(suf) + 1)].rstrip("/")
                changed = True
    return u


class PMISClient:
    """Client minimal pour l'API PMIS (auth token + visites)."""

    def __init__(self):
        self.auth_url = _clean_base(_secret("auth_url", ""), "login", "refresh")
        self.backend_url = _clean_base(_secret("backend_url", ""), "visits")
        self.username = _secret("username")
        self.mail = _secret("mail")
        self.password = _secret("password")
        self.verify_ssl = str(_secret("verify_ssl", "true")).lower() not in ("0", "false", "no")
        self.timeout = int(_secret("timeout", 60) or 60)
        self.access_token = None
        self.refresh_token = None

    # --- statut de configuration (sans exposer les valeurs) ---
    def configured(self) -> bool:
        return bool(self.auth_url and self.backend_url and self.password
                    and (self.username or self.mail))

    def config_report(self) -> dict:
        return {
            "auth_url": bool(self.auth_url), "backend_url": bool(self.backend_url),
            "identifiant": bool(self.username or self.mail), "password": bool(self.password),
            "verify_ssl": self.verify_ssl,
            "login_endpoint": (self.auth_url + "/login") if self.auth_url else "",
            "visits_endpoint": (self.backend_url + "/visits") if self.backend_url else "",
        }

    # --- authentification ---
    @staticmethod
    def _extract_tokens(payload: dict):
        data = payload.get("data", payload) if isinstance(payload, dict) else {}
        acc = data.get("accessToken") or payload.get("accessToken")
        ref = data.get("refreshToken") or payload.get("refreshToken")
        return acc, ref

    def login(self):
        if not self.configured():
            raise PMISError("Connexion PMIS non configurée (secrets manquants).")
        url = self.auth_url + "/login"
        body = {"password": self.password}
        if self.username:
            body["username"] = self.username
        else:
            body["mail"] = self.mail
        try:
            r = requests.post(url, json=body, verify=self.verify_ssl, timeout=self.timeout)
        except requests.RequestException as e:
            raise PMISError(f"Serveur d'authentification injoignable ({url}) : {e}") from e
        if r.status_code == 404:
            raise PMISError(
                f"Endpoint de login introuvable (HTTP 404) : {url}. "
                "Vérifiez le secret « auth_url » — il doit pointer sur la base du "
                "serveur d'auth, p. ex. https://PMIS_IP/pmisAuthServer/api "
                "(le connecteur ajoute /login).")
        if r.status_code in (401, 403):
            raise PMISError(f"Identifiants refusés (HTTP {r.status_code}). "
                            "Vérifiez username/mail et password.")
        if r.status_code >= 400:
            raise PMISError(f"Login en échec (HTTP {r.status_code}) sur {url}. "
                            f"{(r.text or '')[:200]}")
        try:
            self.access_token, self.refresh_token = self._extract_tokens(r.json())
        except ValueError as e:
            raise PMISError(f"Réponse de login illisible (pas du JSON) depuis {url}.") from e
        if not self.access_token:
            raise PMISError("Réponse de login sans accessToken.")
        return self.access_token

    def refresh(self):
        if not self.refresh_token:
            return self.login()
        try:
            r = requests.post(self.auth_url + "/refresh",
                              json={"refreshToken": self.refresh_token},
                              verify=self.verify_ssl, timeout=self.timeout)
            r.raise_for_status()
            self.access_token, self.refresh_token = self._extract_tokens(r.json())
            return self.access_token
        except requests.RequestException:
            return self.login()

    def _headers(self):
        return {"Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json", "Accept": "application/json"}

    # --- visites ---
    def get_visits(self, **params) -> dict:
        if not self.access_token:
            self.login()
        q = {k: v for k, v in params.items() if v not in (None, "", [])}
        url = self.backend_url + "/visits"
        try:
            r = requests.get(url, params=q, headers=self._headers(),
                             verify=self.verify_ssl, timeout=self.timeout)
            if r.status_code == 401:          # token expiré → refresh puis retry
                self.refresh()
                r = requests.get(url, params=q, headers=self._headers(),
                                 verify=self.verify_ssl, timeout=self.timeout)
        except requests.RequestException as e:
            raise PMISError(f"Serveur PMIS injoignable ({url}) : {e}") from e
        if r.status_code == 404:
            raise PMISError(
                f"Endpoint des visites introuvable (HTTP 404) : {url}. "
                "Vérifiez le secret « backend_url » (p. ex. "
                "https://PMIS_IP/pmisBackend/api ; le connecteur ajoute /visits).")
        if r.status_code in (401, 403):
            raise PMISError(f"Accès refusé aux visites (HTTP {r.status_code}). "
                            "Token invalide ou droits insuffisants.")
        if r.status_code >= 400:
            raise PMISError(f"Récupération des visites en échec (HTTP {r.status_code}). "
                            f"{(r.text or '')[:200]}")
        try:
            payload = r.json()
        except ValueError as e:
            raise PMISError(f"Réponse des visites illisible (pas du JSON) depuis {url}.") from e
        data = payload.get("data", payload)
        return {
            "rows": data.get("rows", []) if isinstance(data, dict) else [],
            "total": data.get("total") if isinstance(data, dict) else None,
            "page": data.get("page") if isinstance(data, dict) else None,
            "raw": payload,
        }


# ═══════════════════════════════════════════════════════════════════════════════
#  MAPPING VISITE PMIS → ESCALE + LIGNES DE FACTURE
# ═══════════════════════════════════════════════════════════════════════════════
STATUS_LABELS = {1: "Pending", 2: "Approved", 3: "Completed", 4: "Rejected",
                 5: "Provisionally Approved", 6: "Cancelled"}


def berth_to_terminal(name: str):
    """Déduit le terminal tarifaire NWM à partir du nom du poste PMIS (préfixe)."""
    n = (name or "").upper()
    if any(k in n for k in ("TCE", "TCO", "CONTENEUR", "CONTAINER")):
        return "Terminal à Conteneurs"
    if any(k in n for k in ("TRV", "ROUL", "CAR CARRIER", "VEHIC")):
        return "Terminal Rouliers – Car Carrier"
    if n.strip().startswith("PP") or any(k in n for k in ("PETROL", "HYDRO", "OIL", "TANKER")):
        return "Terminal Hydrocarbures"
    if any(k in n for k in ("TGL", "GAZ", "GAS", "LPG", "LNG")):
        return "Terminal GAZ"
    if any(k in n for k in ("TMD", "TVS", "VRAC", "DIVERS", "BULK")):
        return "Terminal Marchandises Div"
    return None


def _f(x, default=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def _dt_fr(iso: str):
    """'2026-09-19T15:00:00.000Z' → '19/09/2026 15:00' (affichage)."""
    if not iso:
        return ""
    s = str(iso).replace("Z", "").split(".")[0]
    try:
        from datetime import datetime
        d = datetime.fromisoformat(s)
        return d.strftime("%d/%m/%Y %H:%M")
    except Exception:
        return str(iso)


def _hours_between(a: str, b: str) -> float:
    from datetime import datetime
    try:
        da = datetime.fromisoformat(str(a).replace("Z", "").split(".")[0])
        db = datetime.fromisoformat(str(b).replace("Z", "").split(".")[0])
        return max((db - da).total_seconds() / 3600.0, 0.0)
    except Exception:
        return 0.0


def _pilotage_activity(booking: dict) -> str:
    """Renvoie 'annulation' si le booking pilotage est en annulation, sinon 'normal'."""
    # 1) resources[].resource_properties.usage_details.activity_type
    for res in (booking.get("resources") or []):
        act = ((res.get("resource_properties") or {}).get("usage_details") or {}).get("activity_type")
        if act and "annul" in str(act).lower():
            return "annulation"
    # 2) niveau booking
    act = (booking.get("resource_usage_details") or {}).get("activity_type")
    if act and "annul" in str(act).lower():
        return "annulation"
    # 3) recherche large (robustesse : emplacement exact non garanti par la doc)
    try:
        if "annulation" in json.dumps(booking).lower():
            return "annulation"
    except Exception:
        pass
    return "normal"


def is_billable(visit: dict) -> bool:
    return bool(visit.get("billable")) and visit.get("billing_status") in (None, "", "null")


def visit_summary(visit: dict) -> dict:
    ship = visit.get("ship") or {}
    orgs = visit.get("organizations") or ship.get("organizations") or []
    client = orgs[0]["name"] if orgs else ""
    return {
        "visit_id": visit.get("visit_id"),
        "business_id": visit.get("business_id"),
        "navire": (ship.get("target_name") or "").strip(),
        "imo": ship.get("imo_number"),
        "client": client,
        "activite": visit.get("activity_type"),
        "statut": visit.get("status"),
        "billable": is_billable(visit),
        "eta": _dt_fr(visit.get("port_of_call_eta")),
        "ata": _dt_fr(visit.get("port_of_call_ata")),
        "etd": _dt_fr(visit.get("port_of_call_etd")),
        "atd": _dt_fr(visit.get("port_of_call_atd")),
    }


def build_call_and_lines(visit: dict, catalog: list[dict],
                         bill_terminal: str | None = None):
    """Construit (call, lines) pour une visite PMIS via le moteur de tarification.

    Services : droits de port (nautique/port/stationnement) + pilotage.
    Exclut remorqueurs (TOWG) et lamanage/amarrage (MOOR).
    """
    ship = visit.get("ship") or {}
    loa = _f(ship.get("loa"))
    beam = _f(ship.get("width"))
    gt = _f(ship.get("gross_tonnage"))
    draft = _f(ship.get("max_static_draught_full_load"))
    vg = td.calc_vg(loa, beam, draft) if (loa and beam) else 0.0
    te_min = round(0.14 * math.sqrt(loa * beam), 2) if (loa and beam) else 0.0
    te_decl = round(draft, 2)
    te_used = max(te_decl, te_min)

    orgs = visit.get("organizations") or ship.get("organizations") or []
    client_name = orgs[0]["name"] if orgs else ""

    movements = sorted((visit.get("movements") or []),
                       key=lambda m: (m.get("start_dt") or m.get("etm") or ""))
    bookings = {b.get("booking_id"): b for b in (visit.get("resource_bookings") or [])}

    # Terminal principal : premier poste (non nul) rencontré
    inferred = None
    for m in movements:
        loc = (m.get("location_to") or m.get("location_from") or {}) or {}
        t = berth_to_terminal(loc.get("name"))
        if t:
            inferred = t
            break
    term_principal = bill_terminal or inferred or "Terminal à Conteneurs"
    pref = term_principal.split()[-1][:3].upper()
    rade_taux = td.DROITS_PORT_NAVIRES_NWM[term_principal]["stationnement"]

    # Séjour : ATA → ATD (réel) sinon ETA → ETD
    ata = visit.get("port_of_call_ata") or visit.get("port_of_call_eta")
    atd = visit.get("port_of_call_atd") or visit.get("port_of_call_etd")
    sejour_h = _hours_between(ata, atd)
    jours = max(1, -(-int(sejour_h) // 24)) if sejour_h else 1

    ctx = billing.CallContext(gt=gt, vg=vg, loa=loa, sejour_h=sejour_h, jours=jours,
                              lamanage_h=2.0)
    cat = {it["code"]: it for it in catalog if it.get("active", True)}

    def find(code):
        return cat.get(code)

    lines = []

    # 1) Droits de port navire : nautique + port
    for p in ("DN", "DP"):
        it = find(f"{p}-{pref}")
        if it:
            lines.append(billing.make_line(it, 1, ctx))

    # 2) Droit de stationnement (un tronçon au terminal principal, ATA→ATD)
    stat_amount, stat_detail = billing.calc_stationnement_legs(
        vg, [{"label": term_principal, "is_rade": False, "taux": rade_taux, "dur_h": sejour_h}])
    if stat_amount > 0:
        lines.append({
            "code": "DS", "designation": f"Droit de stationnement ({sejour_h:.0f} h)",
            "quantite": 1, "unite": "escale", "pu": round(stat_amount, 2),
            "majoration": 0, "montant_ht": round(stat_amount, 2), "tva": 0.0,
        })

    # 3) Pilotage par mouvement (PILO uniquement ; TOWG/MOOR exclus)
    berth_chain = []
    for m in movements:
        loc = (m.get("location_to") or m.get("location_from") or {}) or {}
        berth = loc.get("name") or ""
        if berth:
            berth_chain.append(berth)
        mname = (m.get("movements_type") or {}).get("movement_type_name", "") or ""
        is_shift = any(k in mname.lower() for k in ("shift", "berth", "changement"))
        pil_code = "PIL-CQ" if is_shift else "PIL-ES"
        for bid in (m.get("booking_ids") or []):
            b = bookings.get(bid) or {}
            st = (b.get("service_type") or {})
            code = (st.get("imo_code") or "").upper()
            if code == "PILO" and find(pil_code):
                maj = 100.0 if _pilotage_activity(b) == "annulation" else 0.0
                l = billing.make_line(find(pil_code), 1, ctx, maj)
                suffix = "annulation" if maj else mname
                l["designation"] = f"{l['designation']} — {mname or 'Mouvement'}"
                if maj:
                    l["designation"] += " (annulation)"
                lines.append(l)

    emplacements = list(dict.fromkeys(berth_chain)) or [term_principal]

    call = {
        "id": f"pmis-{visit.get('visit_id')}",
        "ref": str(visit.get("business_id") or visit.get("visit_id") or ""),
        "vessel_id": None,
        "vessel_inline": {"name": (ship.get("target_name") or "").strip(),
                          "imo": ship.get("imo_number"), "flag": ship.get("home_port"),
                          "gt": gt, "loa": loa, "beam": beam, "draft": draft},
        "terminal": term_principal, "berth": " → ".join(emplacements),
        "eta": _dt_fr(ata), "etd": _dt_fr(atd),
        "sejour_h": sejour_h, "jours": jours,
        "vg": vg, "draught_declared": te_decl, "draught_min": te_min, "draught_used": te_used,
        "client_name": client_name, "client_address": "",
        "stationnement_detail": stat_detail, "source": "PMIS",
        "lines": lines, "status": "Brouillon",
    }
    return call, lines
