"""
tugs.py — Suivi des remorqueurs (usages & tarification) par escale

Un *enregistrement* = un remorqueur engagé sur un mouvement d'une escale.
Sources : import des réservations TOWG des visites PMIS, ou saisie manuelle.

Tarification NWM (Cahier Tarifaire) — par remorqueur et par mouvement :
  • tarif de base = barème remorquage NWM par tranche de GT
    (+ 150 € par tranche de 5 000 GT au-delà de 50 000 GT) ;
  • déhalage : 25 % du tarif ;
  • remorqueur sans propulsion du navire : +25 % ;
  • annulation : majoration paramétrable (en %) ;
  • majoration libre (%) saisie par enregistrement.
"""
from __future__ import annotations

import io
import uuid
from datetime import datetime

import pandas as pd

import tarifs_data as td

# Colonnes d'un enregistrement (ordre d'affichage / d'export)
COLUMNS = [
    "id", "debut", "fin", "duree_h", "escale", "visit_id", "navire", "imo", "gt",
    "mouvement", "de", "vers", "remorqueur", "bollard_pull", "prestataire",
    "activite", "annulation", "sans_propulsion", "dehalage", "majoration",
    "tarif_base", "majoration_totale", "montant", "source", "notes",
]

LABELS = {
    "debut": "Début", "fin": "Fin", "duree_h": "Durée (h)", "escale": "Escale",
    "visit_id": "Visite PMIS", "navire": "Navire", "imo": "IMO", "gt": "GT",
    "mouvement": "Mouvement", "de": "De", "vers": "Vers", "remorqueur": "Remorqueur",
    "bollard_pull": "Traction (t)", "prestataire": "Prestataire", "activite": "Activité",
    "annulation": "Annulation", "sans_propulsion": "Sans propulsion",
    "dehalage": "Déhalage", "majoration": "Maj. libre %", "tarif_base": "Tarif base",
    "majoration_totale": "Maj. totale %", "montant": "Montant", "source": "Source",
    "notes": "Notes",
}

MOVEMENTS = ["Arrival", "Internal", "Departure", "Autre"]


def _f(x, default=0.0) -> float:
    try:
        v = float(x)
        return default if v != v else v      # NaN → défaut
    except (TypeError, ValueError):
        return default


def _parse_dt(v):
    if v in (None, "") or (isinstance(v, float) and v != v):
        return None
    if isinstance(v, datetime):
        return v.replace(tzinfo=None)
    try:
        return datetime.fromisoformat(str(v).replace("Z", "").split(".")[0])
    except ValueError:
        return None


def _iso(d) -> str:
    return d.strftime("%Y-%m-%dT%H:%M:%S") if d else ""


# ═══════════════════════════════════════════════════════════════════════════════
#  TARIFICATION
# ═══════════════════════════════════════════════════════════════════════════════
def base_tariff(gt: float) -> float:
    """Tarif NWM d'un remorqueur pour un mouvement (barème par tranche de GT)."""
    return float(td.calc_remorquage(_f(gt), td.REMORQUAGE_NWM, td.REMORQUAGE_NWM_SUP))


def price(rec: dict, annul_pct: float = 100.0) -> dict:
    """Recalcule durée, tarif de base, majoration totale et montant d'un enregistrement."""
    r = dict(rec)
    d0, d1 = _parse_dt(r.get("debut")), _parse_dt(r.get("fin"))
    r["duree_h"] = round(max((d1 - d0).total_seconds() / 3600.0, 0.0), 2) if (d0 and d1) else 0.0
    base = base_tariff(r.get("gt"))
    if r.get("dehalage"):
        base *= 0.25
    maj = _f(r.get("majoration"))
    if r.get("sans_propulsion"):
        maj += 25.0
    if r.get("annulation"):
        maj += _f(annul_pct)
    r["tarif_base"] = round(base, 2)
    r["majoration_totale"] = round(maj, 2)
    r["montant"] = round(base * (1 + maj / 100.0), 2)
    return r


def new_record(**kw) -> dict:
    rec = {c: None for c in COLUMNS}
    rec.update({"id": str(uuid.uuid4()), "annulation": False, "sans_propulsion": False,
                "dehalage": False, "majoration": 0.0, "source": "Manuel", "notes": ""})
    rec.update(kw)
    return rec


# ═══════════════════════════════════════════════════════════════════════════════
#  IMPORT PMIS (réservations TOWG)
# ═══════════════════════════════════════════════════════════════════════════════
def records_from_visit(visit: dict) -> list[dict]:
    """Un enregistrement par remorqueur affecté à une réservation TOWG de la visite."""
    ship = visit.get("ship") or {}
    movements = {m.get("movement_id"): m for m in (visit.get("movements") or [])}
    out = []
    for b in (visit.get("resource_bookings") or []):
        if ((b.get("service_type") or {}).get("imo_code") or "").upper() != "TOWG":
            continue
        m = movements.get(b.get("fk_movement_id")) or {}
        if not m:   # réservation non rattachée : retrouver le mouvement par booking_ids
            m = next((mv for mv in movements.values()
                      if b.get("booking_id") in (mv.get("booking_ids") or [])), {})
        mname = (m.get("movements_type") or {}).get("movement_type_name") or "Autre"
        busage = b.get("resource_usage_details") or {}
        for res in (b.get("resources") or []):
            det = res.get("resource_details") or {}
            usage = (res.get("resource_properties") or {}).get("usage_details") or {}
            act = usage.get("activity_type") or ""
            start = _parse_dt(usage.get("actual_start") or busage.get("actual_start")
                              or usage.get("estimated_start") or busage.get("estimated_start"))
            end = _parse_dt(usage.get("actual_completion") or busage.get("actual_completion")
                            or usage.get("estimated_completion")
                            or busage.get("estimated_completion"))
            out.append(new_record(
                id=f"pmis-{visit.get('visit_id')}-{b.get('booking_id')}-{res.get('resource_id')}",
                debut=_iso(start), fin=_iso(end),
                escale=str(visit.get("business_id") or visit.get("visit_id") or ""),
                visit_id=visit.get("visit_id"),
                navire=(ship.get("target_name") or "").strip(), imo=ship.get("imo_number"),
                gt=_f(ship.get("gross_tonnage")),
                mouvement=mname,
                de=((m.get("location_from") or {}).get("name") or ""),
                vers=((m.get("location_to") or {}).get("name") or ""),
                remorqueur=(det.get("target_name") or det.get("alias") or "").strip(),
                bollard_pull=_f(det.get("bollard_pull_num"), None),
                prestataire=((res.get("organization") or {}).get("name") or ""),
                activite=act, annulation="annul" in str(act).lower(),
                source="PMIS",
            ))
    return out


def merge_records(existing: list[dict], incoming: list[dict]) -> tuple[list[dict], int, int]:
    """Ajoute les enregistrements PMIS absents (même id). Les enregistrements déjà
    présents ne sont pas écrasés (les corrections manuelles sont conservées).
    Renvoie (liste, nb_ajoutés, nb_ignorés)."""
    ids = {r.get("id") for r in existing}
    added = [r for r in incoming if r.get("id") not in ids]
    return existing + added, len(added), len(incoming) - len(added)


# ═══════════════════════════════════════════════════════════════════════════════
#  TABLEAU, FILTRES & SITUATION
# ═══════════════════════════════════════════════════════════════════════════════
def to_df(records: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(records, columns=COLUMNS)
    df["debut"] = pd.to_datetime(df["debut"], errors="coerce")
    df["fin"] = pd.to_datetime(df["fin"], errors="coerce")
    for c in ("annulation", "sans_propulsion", "dehalage"):
        df[c] = df[c].fillna(False).astype(bool)
    for c in ("gt", "majoration", "duree_h", "tarif_base", "majoration_totale", "montant",
              "bollard_pull"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    for c in ("escale", "navire", "imo", "mouvement", "de", "vers", "remorqueur",
              "prestataire", "activite", "source", "notes"):
        df[c] = df[c].astype(object).where(df[c].notna(), "").astype(str)
    return df


def from_df(df: pd.DataFrame) -> list[dict]:
    out = []
    for r in df.astype(object).where(pd.notna(df), None).to_dict("records"):
        r["debut"] = _iso(_parse_dt(r.get("debut")))
        r["fin"] = _iso(_parse_dt(r.get("fin")))
        r["id"] = r.get("id") or str(uuid.uuid4())
        out.append(r)
    return out


def filter_df(df: pd.DataFrame, search: str = "", date_from=None, date_to=None,
              tugs=None, calls=None, movements=None, sources=None,
              only_cancelled: bool = False) -> pd.DataFrame:
    m = pd.Series(True, index=df.index)
    if search:
        s = search.strip().lower()
        hay = df[["escale", "navire", "imo", "remorqueur", "prestataire", "mouvement", "de",
                  "vers", "activite", "notes"]].astype(str).agg(" ".join, axis=1).str.lower()
        m &= hay.str.contains(s, regex=False)
    if date_from is not None:
        m &= df["debut"].isna() | (df["debut"].dt.date >= date_from)
    if date_to is not None:
        m &= df["debut"].isna() | (df["debut"].dt.date <= date_to)
    if tugs:
        m &= df["remorqueur"].isin(tugs)
    if calls:
        m &= df["escale"].isin(calls)
    if movements:
        m &= df["mouvement"].isin(movements)
    if sources:
        m &= df["source"].isin(sources)
    if only_cancelled:
        m &= df["annulation"]
    return df[m]


def situation(df: pd.DataFrame, by: str) -> pd.DataFrame:
    """Synthèse : nb d'opérations, heures, montant (et escales / remorqueurs distincts)."""
    if df.empty:
        return pd.DataFrame()
    g = df.groupby(by, dropna=False)
    out = pd.DataFrame({
        "Opérations": g.size(),
        "Heures": g["duree_h"].sum().round(2),
        "Annulations": g["annulation"].sum().astype(int),
        "Montant": g["montant"].sum().round(2),
    })
    if by != "escale":
        out.insert(1, "Escales", g["escale"].nunique())
    if by != "remorqueur":
        out.insert(1, "Remorqueurs", g["remorqueur"].nunique())
    return out.sort_values("Montant", ascending=False).reset_index()


def export_df(df: pd.DataFrame) -> pd.DataFrame:
    out = df.drop(columns=["id"]).rename(columns=LABELS)
    for c in ("Début", "Fin"):
        out[c] = pd.to_datetime(out[c]).dt.strftime("%d/%m/%Y %H:%M").fillna("")
    return out


def to_excel(df: pd.DataFrame) -> bytes:
    """Classeur : détail filtré + situations par remorqueur, escale et mois."""
    buf = io.BytesIO()
    monthly = df.assign(mois=df["debut"].dt.strftime("%Y-%m").fillna("—"))
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        export_df(df).to_excel(xw, sheet_name="Détail", index=False)
        for name, frame, by in (("Par remorqueur", df, "remorqueur"),
                                ("Par escale", df, "escale"),
                                ("Par mois", monthly, "mois")):
            situation(frame, by).to_excel(xw, sheet_name=name, index=False)
        for ws in xw.book.worksheets:                     # largeur des colonnes
            for col in ws.columns:
                width = max(len(str(c.value or "")) for c in col)
                ws.column_dimensions[col[0].column_letter].width = min(max(width + 2, 8), 40)
    return buf.getvalue()
