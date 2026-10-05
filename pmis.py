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
- Pilotage : Arrival / Departure ⇒ entrée/sortie ; Internal ⇒ changement de quai
  entre deux postes (entrée/sortie si depuis / vers la rade).
- Terminal déduit du nom du poste (préfixe). Escale au mouillage seul (emplacements
  ANCH / MOUILL / RADE) ⇒ Terminal Marchandises Diverses (TMD).
- Stationnement découpé en tronçons rade / quai (franchise 24 h, tranches de 24 h,
  rade 50 % au-delà de 96 h).
- VG basé sur le tirant « max_static_draught_full_load » du navire.
- Tous les paramètres de l'escale sont modifiables et des articles (catalogue ou
  lignes libres) peuvent être ajoutés : la facture est recalculée à chaque fois.
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


# ═══════════════════════════════════════════════════════════════════════════════
#  PARAMÈTRES D'ESCALE (éditables) → FACTURE
# ═══════════════════════════════════════════════════════════════════════════════
# Une visite PMIS est d'abord convertie en un dict de *paramètres* modifiables
# (dimensions, tirant, client, itinéraire, pilotage, terminal). La facture est
# ensuite entièrement recalculée à partir de ces paramètres + des articles ajoutés.

ANCHORAGE_KEYS = ("ANCH", "MOUILL", "RADE")
ANCHORAGE_TERMINAL = "Terminal Marchandises Div"   # escale au mouillage seul → TMD
DEFAULT_TERMINAL = "Terminal à Conteneurs"

PILOT_TYPES = {"ES": "Entrée / Sortie", "CQ": "Changement de quai"}


def is_anchorage(name) -> bool:
    """Emplacement de mouillage (rade) : nom contenant ANCH, MOUILL ou RADE."""
    n = (name or "").upper()
    return any(k in n for k in ANCHORAGE_KEYS)


def leg_terminal(name):
    """Terminal tarifaire d'un emplacement (None pour la rade ou un poste inconnu)."""
    if not name or is_anchorage(name):
        return None
    return berth_to_terminal(name)


def _parse_dt(v):
    from datetime import datetime
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "").split(".")[0])
    except Exception:
        return None


def _iso(d) -> str:
    return d.strftime("%Y-%m-%dT%H:%M:%S") if d else ""


def _loc_name(loc) -> str:
    return ((loc or {}).get("name") or "").strip()


def _movement_time(m):
    return _parse_dt(m.get("start_dt") or m.get("end_dt") or m.get("etm"))


def pilot_type(movement_name: str, loc_from: str, loc_to: str) -> str:
    """Barème de pilotage d'un mouvement : 'ES' (entrée/sortie) ou 'CQ' (chgt de quai).

    Arrival / Departure → ES. Internal (ou shifting) → CQ entre deux postes à quai ;
    ES si l'une des extrémités est la rade (entrée depuis / sortie vers le mouillage).
    """
    n = (movement_name or "").lower()
    internal = any(k in n for k in ("internal", "shift", "changement"))
    if not internal:
        return "ES"
    if not loc_from or not loc_to or is_anchorage(loc_from) or is_anchorage(loc_to):
        return "ES"
    return "CQ"


def visit_legs(visit: dict) -> list[dict]:
    """Découpe le séjour ATA → ATD en tronçons {location, start, end} (ISO) d'après
    les mouvements PMIS. Le transit d'un mouvement est rattaché à sa destination et
    le dernier tronçon court jusqu'à l'ATD (séjour total = ATA → ATD)."""
    movements = sorted((visit.get("movements") or []),
                       key=lambda m: (_iso(_movement_time(m)) or ""))
    ata = _parse_dt(visit.get("port_of_call_ata") or visit.get("port_of_call_eta"))
    atd = _parse_dt(visit.get("port_of_call_atd") or visit.get("port_of_call_etd"))
    times = [t for t in (_movement_time(m) for m in movements) if t]
    ata = ata or (min(times) if times else None)
    atd = atd or (max(times) if times else None)
    if not ata or not atd or atd <= ata:
        return []

    legs, cur_loc, cur_start = [], None, ata
    for m in movements:
        t = min(max(_movement_time(m) or cur_start, ata), atd)
        fr, to = _loc_name(m.get("location_from")), _loc_name(m.get("location_to"))
        if cur_loc is None:
            if fr and t > cur_start:          # position connue avant le 1er mouvement
                legs.append({"location": fr, "start": _iso(cur_start), "end": _iso(t)})
                cur_start = t
            cur_loc = to or fr or None
            continue
        if not to or to == cur_loc:           # départ : le tronçon courant va jusqu'à l'ATD
            continue
        if t > cur_start:
            legs.append({"location": cur_loc, "start": _iso(cur_start), "end": _iso(t)})
        cur_loc, cur_start = to, max(t, cur_start)
    legs.append({"location": cur_loc or "", "start": _iso(cur_start), "end": _iso(atd)})
    return [l for l in legs if l["end"] > l["start"]]


def visit_pilotage(visit: dict) -> list[dict]:
    """Une entrée par service PILO réservé sur un mouvement (TOWG / MOOR exclus)."""
    movements = sorted((visit.get("movements") or []),
                       key=lambda m: (_iso(_movement_time(m)) or ""))
    bookings = {b.get("booking_id"): b for b in (visit.get("resource_bookings") or [])}
    out = []
    for m in movements:
        mname = (m.get("movements_type") or {}).get("movement_type_name", "") or ""
        fr, to = _loc_name(m.get("location_from")), _loc_name(m.get("location_to"))
        for bid in (m.get("booking_ids") or []):
            b = bookings.get(bid) or {}
            if ((b.get("service_type") or {}).get("imo_code") or "").upper() != "PILO":
                continue
            out.append({
                "mouvement": mname or "Mouvement", "de": fr, "vers": to,
                "date": _iso(_movement_time(m)),
                "type": pilot_type(mname, fr, to),
                "annulation": _pilotage_activity(b) == "annulation",
                "facturer": True,
            })
    return out


def visit_params(visit: dict) -> dict:
    """Paramètres d'escale éditables, initialisés depuis la visite PMIS."""
    ship = visit.get("ship") or {}
    orgs = visit.get("organizations") or ship.get("organizations") or []
    return {
        "visit_id": visit.get("visit_id"),
        "ref": str(visit.get("business_id") or visit.get("visit_id") or ""),
        "name": (ship.get("target_name") or "").strip(),
        "imo": ship.get("imo_number"), "flag": ship.get("home_port"),
        "loa": _f(ship.get("loa")), "beam": _f(ship.get("width")),
        "gt": _f(ship.get("gross_tonnage")),
        "draft": _f(ship.get("max_static_draught_full_load")),
        "client_name": orgs[0]["name"] if orgs else "",
        "client_ice": "", "client_address": "",
        "bill_terminal": None,          # None = automatique (poste / mouillage)
        "legs": visit_legs(visit),
        "pilotage": visit_pilotage(visit),
    }


def resolve_terminal(legs: list[dict], bill_terminal=None):
    """Terminal de facturation → (terminal, mode).

    mode : 'manuel' (choisi), 'poste' (1er poste reconnu), 'mouillage' (escale au
    mouillage seul → TMD) ou 'défaut' (aucun poste reconnu).
    """
    if bill_terminal and bill_terminal in td.DROITS_PORT_NAVIRES_NWM:
        return bill_terminal, "manuel"
    for l in legs:
        t = leg_terminal(l.get("location"))
        if t:
            return t, "poste"
    if legs and all(is_anchorage(l.get("location")) for l in legs):
        return ANCHORAGE_TERMINAL, "mouillage"
    return DEFAULT_TERMINAL, "défaut"


def extra_line(extra: dict, cat: dict, ctx) -> dict | None:
    """Ligne d'un article ajouté : article du catalogue (chiffré selon les paramètres
    de l'escale) ou ligne libre (désignation + prix unitaire saisis)."""
    qty = _f(extra.get("quantite"), 1.0)
    maj = _f(extra.get("majoration"), 0.0)
    if extra.get("kind") == "catalog":
        it = cat.get(extra.get("code"))
        return billing.make_line(it, qty, ctx, maj) if it else None
    des = (extra.get("designation") or "").strip()
    if not des:
        return None
    pu = _f(extra.get("pu"))
    return {"code": extra.get("code") or "DIV", "designation": des, "quantite": round(qty, 3),
            "unite": extra.get("unite") or "u", "pu": round(pu, 5), "majoration": maj,
            "montant_ht": round(qty * pu * (1 + maj / 100.0), 2), "tva": 0.0}


def build_from_params(p: dict, catalog: list[dict], extras: list[dict] | None = None):
    """Construit (call, lines) à partir des paramètres d'escale (éventuellement
    modifiés) et des articles ajoutés. Tous les montants sont recalculés."""
    loa, beam, gt, draft = _f(p.get("loa")), _f(p.get("beam")), _f(p.get("gt")), _f(p.get("draft"))
    vg = td.calc_vg(loa, beam, draft) if (loa and beam) else 0.0
    te_min = round(0.14 * math.sqrt(loa * beam), 2) if (loa and beam) else 0.0
    te_decl = round(draft, 2)
    te_used = max(te_decl, te_min)

    legs = [l for l in (p.get("legs") or [])
            if _parse_dt(l.get("start")) and _parse_dt(l.get("end"))
            and _parse_dt(l["end"]) > _parse_dt(l["start"])]
    legs.sort(key=lambda l: l["start"])
    term_principal, term_mode = resolve_terminal(legs, p.get("bill_terminal"))
    pref = term_principal.split()[-1][:3].upper()
    rates = td.DROITS_PORT_NAVIRES_NWM

    ata = _parse_dt(legs[0]["start"]) if legs else None
    atd = _parse_dt(legs[-1]["end"]) if legs else None
    stat_legs, rade_h = [], 0.0
    for l in legs:
        h = _hours_between(l["start"], l["end"])
        rade = is_anchorage(l.get("location"))
        t = term_principal if rade else (leg_terminal(l.get("location")) or term_principal)
        rade_h += h if rade else 0.0
        stat_legs.append({"label": l.get("location") or t, "is_rade": rade,
                          "taux": rates[t]["stationnement"], "dur_h": h})
    sejour_h = sum(sl["dur_h"] for sl in stat_legs)
    jours = max(1, -(-int(sejour_h) // 24)) if sejour_h else 1

    ctx = billing.CallContext(gt=gt, vg=vg, loa=loa, sejour_h=sejour_h, jours=jours,
                              lamanage_h=2.0)
    cat = {it["code"]: it for it in catalog if it.get("active", True)}
    lines = []

    # 1) Droits de port navire : nautique + port (terminal de facturation)
    for pre in ("DN", "DP"):
        it = cat.get(f"{pre}-{pref}")
        if it:
            lines.append(billing.make_line(it, 1, ctx))

    # 2) Droit de stationnement : tronçons rade / quai (franchise, tranches, rade 50 %)
    stat_amount, stat_detail = billing.calc_stationnement_legs(vg, stat_legs)
    if stat_amount > 0:
        des = f"Droit de stationnement ({sejour_h:.0f} h"
        des += f", dont {rade_h:.0f} h en rade)" if rade_h else ")"
        lines.append({"code": f"DS-{pref}", "designation": des, "quantite": 1,
                      "unite": "escale", "pu": round(stat_amount, 2), "majoration": 0,
                      "montant_ht": round(stat_amount, 2), "tva": 0.0})

    # 3) Pilotage : une ligne par service PILO facturé (annulation ⇒ +100 %)
    for pl in (p.get("pilotage") or []):
        if not pl.get("facturer", True):
            continue
        it = cat.get("PIL-CQ" if pl.get("type") == "CQ" else "PIL-ES")
        if not it:
            continue
        maj = 100.0 if pl.get("annulation") else 0.0
        l = billing.make_line(it, 1, ctx, maj)
        l["designation"] = f"{l['designation']} — {pl.get('mouvement') or 'Mouvement'}"
        if maj:
            l["designation"] += " (annulation)"
        lines.append(l)

    # 4) Articles ajoutés (catalogue chiffré selon l'escale, ou lignes libres)
    for ex in (extras or []):
        l = extra_line(ex, cat, ctx)
        if l:
            lines.append(l)

    berths = list(dict.fromkeys(l["location"] for l in legs if l.get("location")))
    call = {
        "id": f"pmis-{p.get('visit_id')}",
        "ref": p.get("ref", ""),
        "vessel_id": None,
        "vessel_inline": {"name": p.get("name", ""), "imo": p.get("imo"),
                          "flag": p.get("flag"), "gt": gt, "loa": loa, "beam": beam,
                          "draft": draft},
        "terminal": term_principal, "terminal_mode": term_mode,
        "berth": " → ".join(berths) or term_principal,
        "eta": ata.strftime("%d/%m/%Y %H:%M") if ata else "",
        "etd": atd.strftime("%d/%m/%Y %H:%M") if atd else "",
        "sejour_h": sejour_h, "rade_h": rade_h, "jours": jours,
        "vg": vg, "draught_declared": te_decl, "draught_min": te_min, "draught_used": te_used,
        "client_name": p.get("client_name", ""), "client_address": p.get("client_address", ""),
        "client_ice": p.get("client_ice", ""),
        "stationnement_detail": stat_detail, "source": "PMIS",
        "lines": lines, "status": "Brouillon",
    }
    return call, lines


def build_call_and_lines(visit: dict, catalog: list[dict],
                         bill_terminal: str | None = None, extras: list[dict] | None = None):
    """Construit (call, lines) pour une visite PMIS (paramètres non modifiés)."""
    p = visit_params(visit)
    p["bill_terminal"] = bill_terminal
    return build_from_params(p, catalog, extras)
