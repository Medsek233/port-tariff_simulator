"""
billing.py — Moteur de tarification & facturation des escales portuaires (NWM)

Ce module contient :
  - Le catalogue tarifaire par défaut (rate card) dérivé du Cahier Tarifaire NWM 2025
  - Les fonctions de calcul des prestations d'une escale
  - La génération des lignes de facture et le rendu HTML de la facture

Toutes les prestations sont modélisées par une "base de calcul" (basis) ce qui rend
le moteur entièrement dynamique : l'utilisateur peut ajouter / modifier des articles.
"""
from __future__ import annotations

import base64
import functools
import math
import os
from dataclasses import dataclass, field
from datetime import datetime

import tarifs_data as td

# ═══════════════════════════════════════════════════════════════════════════════
#  BASES DE CALCUL (unit basis) — comment un article est chiffré
# ═══════════════════════════════════════════════════════════════════════════════
#   fixed          : montant = tarif                      (forfait)
#   per_unit       : montant = tarif × quantité           (qté saisie : EVP, tonne, u…)
#   per_gt         : montant = tarif × GT
#   per_vg         : montant = tarif × Volume Géométrique (m³)
#   per_vg_day     : montant = tarif × VG × nb_jours
#   per_day        : montant = tarif × nb_jours
#   pilotage_es    : formule pilotage NWM entrée/sortie   (fonction du GT)
#   pilotage_cq    : formule pilotage NWM changement quai (fonction du GT)
#   remorquage     : barème remorquage NWM par tranche GT
#   lamanage       : formule lamanage NWM                 (fonction du GT)
#   stationnement  : droit de stationnement (franchise 24h, règles rade)

BASES = [
    "fixed", "per_unit", "per_gt", "per_vg", "per_vg_day", "per_day",
    "pilotage_es", "pilotage_cq", "remorquage", "lamanage", "stationnement",
]

BASIS_LABEL = {
    "fixed":         "Forfait",
    "per_unit":      "× Quantité",
    "per_gt":        "× GT",
    "per_vg":        "× Volume Géom.",
    "per_vg_day":    "× VG × Jours",
    "per_day":       "× Jours",
    "pilotage_es":   "Pilotage (formule GT)",
    "pilotage_cq":   "Pilotage chgt quai (GT)",
    "remorquage":    "Remorquage (barème GT)",
    "lamanage":      "Lamanage (formule GT)",
    "stationnement": "Stationnement (VG/durée)",
}

TVA_DEFAULT = 0.0  # Zone Franche — exonération de TVA


# ═══════════════════════════════════════════════════════════════════════════════
#  CATALOGUE TARIFAIRE PAR DÉFAUT (rate card NWM 2025)
# ═══════════════════════════════════════════════════════════════════════════════
def default_catalog() -> list[dict]:
    """Construit le catalogue tarifaire NWM par défaut à partir de tarifs_data."""
    cat: list[dict] = []

    def add(code, category, label, unit, rate, basis, vat=TVA_DEFAULT, taxable=True):
        cat.append({
            "code": code, "category": category, "label": label, "unit": unit,
            "rate": round(float(rate), 5), "basis": basis, "vat": vat,
            "taxable": taxable, "active": True,
        })

    # --- Droits de port sur navires (par terminal) : nautique / port / stationnement
    for term, r in td.DROITS_PORT_NAVIRES_NWM.items():
        pref = term.split()[-1][:3].upper()
        add(f"DN-{pref}", "Droits de Port Navire", f"Droit Nautique — {term}",
            "m³ VG", r["nautique"], "per_vg")
        add(f"DP-{pref}", "Droits de Port Navire", f"Droit de Port — {term}",
            "m³ VG", r["port"], "per_vg")
        add(f"DS-{pref}", "Droits de Port Navire", f"Droit de Stationnement — {term}",
            "m³ VG/j", r["stationnement"], "stationnement")

    # --- Pilotage
    add("PIL-ES", "Pilotage", "Pilotage entrée / sortie", "mouvement", 0, "pilotage_es")
    add("PIL-CQ", "Pilotage", "Pilotage changement de quai", "mouvement", 0, "pilotage_cq")

    # --- Remorquage & Lamanage
    add("REM", "Remorquage", "Remorquage (par remorqueur / mouvement)", "remorqueur", 0, "remorquage")
    add("LAM", "Lamanage", "Lamanage (par mouvement)", "mouvement", 0, "lamanage")

    # --- Droits de port marchandise : conteneurs
    for op, rate in td.CONTENEURS_NWM.items():
        unit = "m³ VG" if op == "Transbordement" else "EVP"
        basis = "per_vg" if op == "Transbordement" else "per_unit"
        add(f"CTN-{op[:3].upper()}", "Marchandise — Conteneurs",
            f"Droit marchandise conteneur — {op}", unit, rate, basis)

    # --- Marchandises diverses (€/T)
    for lib, rate in td.MARCHANDISES_DIV_NWM.items():
        unit = "m³" if "m³" in lib else ("EVP" if "EVP" in lib else "tonne")
        clean = lib.split(" (")[0]
        add(f"MD-{clean[:4].upper()}", "Marchandise — Diverses",
            f"MD — {clean}", unit, rate, "per_unit")

    # --- Hydrocarbures (€/T)
    for prod, ops in td.HYDROCARBURES_NWM.items():
        short = "Blancs" if "blancs" in prod.lower() else "Noirs"
        for op, rate in ops.items():
            add(f"HC-{short[:1]}{op[:3].upper()}", "Marchandise — Hydrocarbures",
                f"Hydrocarbures {short} — {op}", "tonne", rate, "per_unit")

    # --- Services divers / fournitures (forfaits & unités usuelles)
    add("DECH", "Services", "Réception des déchets liquides commerce", "m³", 66.0, "per_unit")
    add("VEIL", "Services", "Veille sécurité pétrolier", "heure",
        td.VEILLE_SECURITE.get("NWM", 330.0), "per_unit")
    _eau = td.FOURNITURES.get("Eau potable", {}).get("tarif", 1.235)
    add("EAU", "Fournitures", "Fourniture d'eau potable", "m³", _eau, "per_unit")
    _elec = td.FOURNITURES.get("Électricité BT", {}).get("tarif", 0.1623)
    add("ELEC", "Fournitures", "Fourniture électricité (BT)", "kWh", _elec, "per_unit")

    return cat


# ═══════════════════════════════════════════════════════════════════════════════
#  CALCUL D'UNE LIGNE
# ═══════════════════════════════════════════════════════════════════════════════
@dataclass
class CallContext:
    """Contexte d'une escale nécessaire au calcul des prestations."""
    gt: float = 0.0
    vg: float = 0.0
    loa: float = 0.0
    sejour_h: float = 24.0
    jours: int = 1
    en_rade: bool = False
    jour_rade: int = 0
    lamanage_h: float = 2.0  # durée de la manœuvre d'amarrage (supplément +30 %/h > 2 h)


def compute_amount(item: dict, qty: float, ctx: CallContext) -> float:
    """Calcule le montant HT d'une ligne selon la base de calcul de l'article."""
    basis = item.get("basis", "per_unit")
    rate = float(item.get("rate", 0) or 0)
    q = float(qty or 0)

    if basis == "fixed":
        return rate
    if basis == "per_unit":
        return rate * q
    if basis == "per_gt":
        return rate * ctx.gt
    if basis == "per_vg":
        return rate * ctx.vg
    if basis == "per_vg_day":
        return rate * ctx.vg * ctx.jours
    if basis == "per_day":
        return rate * ctx.jours
    if basis == "pilotage_es":
        return td.calc_pilotage_nwm_entree_sortie(ctx.vg) * max(q, 1)
    if basis == "pilotage_cq":
        return td.calc_pilotage_nwm_chg_quai(ctx.vg) * max(q, 1)
    if basis == "remorquage":
        unit = td.calc_remorquage(ctx.gt, td.REMORQUAGE_NWM, td.REMORQUAGE_NWM_SUP)
        return unit * max(q, 1)
    if basis == "lamanage":
        # Supplément de durée +30 %/h au-delà de 2 h (durée de manœuvre d'amarrage).
        return td.calc_lamanage_nwm(ctx.loa, ctx.lamanage_h) * max(q, 1)
    if basis == "stationnement":
        return td.calc_stationnement(ctx.vg, rate, ctx.sejour_h, ctx.en_rade, ctx.jour_rade)
    return rate * q


def make_line(item: dict, qty: float, ctx: CallContext, majoration: float = 0.0) -> dict:
    """Construit une ligne de facture prête à l'emploi."""
    base = compute_amount(item, qty, ctx)
    montant = round(base * (1 + majoration / 100.0), 2)
    return {
        "code": item["code"],
        "designation": item["label"],
        "quantite": round(float(qty or 0), 3),
        "unite": item.get("unit", ""),
        "pu": round(float(item.get("rate", 0) or 0), 5),
        "majoration": majoration,
        "montant_ht": montant,
        "tva": float(item.get("vat", TVA_DEFAULT)) if item.get("taxable", True) else 0.0,
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  TOTAUX D'UNE FACTURE
# ═══════════════════════════════════════════════════════════════════════════════
def invoice_totals(lines: list[dict]) -> dict:
    total_ht = sum(float(l.get("montant_ht", 0) or 0) for l in lines)
    total_tva = sum(float(l.get("montant_ht", 0) or 0) * float(l.get("tva", 0) or 0) / 100.0
                    for l in lines)
    return {
        "total_ht": round(total_ht, 2),
        "total_tva": round(total_tva, 2),
        "total_ttc": round(total_ht + total_tva, 2),
    }


def next_invoice_number(seq: int, prefix: str = "NWM") -> str:
    return f"{prefix}-{datetime.now():%Y}-{seq:05d}"


# ═══════════════════════════════════════════════════════════════════════════════
#  STATIONNEMENT SUR ITINÉRAIRE (escale complexe multi-mouvements / multi-terminaux)
# ═══════════════════════════════════════════════════════════════════════════════
def calc_stationnement_legs(vg: float, legs: list[dict], franchise_h: float = 24.0,
                            rade_seuil_h: float = 96.0) -> tuple[float, list[dict]]:
    """Calcule le droit de stationnement sur une escale décomposée en tronçons (legs).

    legs : liste ordonnée de dicts {label, is_rade, taux, dur_h} où
      - taux  = taux de stationnement du terminal (€/m³/jour)
      - is_rade = True si le tronçon est passé au mouillage (rade)
      - dur_h = durée du tronçon en heures

    Règles appliquées (Cahier Tarifaire NWM — Avril 2025) :
      • franchise de 24 h à partir du franchissement de la limite administrative ;
      • au-delà, facturation par **tranche indivisible de 24 h** : une période
        résiduelle ≤ 8 h = 1/3 du taux de base ; une période > 8 h = tranche pleine ;
      • mouillage en rade : **50 %** du taux de base dès le 5ᵉ jour (au-delà de 96 h
        cumulées d'utilisation de la zone de mouillage) ;
      • taux propre à chaque terminal : une tranche à cheval sur plusieurs terminaux
        est répartie au prorata des heures passées sur chacun.

    Renvoie (montant, détail_par_tranche).
    """
    # File d'attente des tronçons : [is_rade, taux, heures_restantes]
    queue = [[bool(l.get("is_rade")), float(l.get("taux", 0) or 0),
              max(float(l.get("dur_h", 0) or 0), 0.0)] for l in legs]
    pos = {"i": 0}
    rade_cum = 0.0  # heures cumulées en rade (seuil des 4 jours, franchise incluse)

    def take(hours: float) -> list[tuple[bool, float, float]]:
        """Consomme jusqu'à `hours` de la file ; renvoie [(is_rade, taux, h), …]."""
        segs, need = [], hours
        while need > 1e-9 and pos["i"] < len(queue):
            seg = queue[pos["i"]]
            if seg[2] <= 1e-9:
                pos["i"] += 1
                continue
            use = min(seg[2], need)
            segs.append((seg[0], seg[1], use))
            seg[2] -= use
            need -= use
        return segs

    def window_cost(segs, day_factor, denom):
        """Coût d'une fenêtre : `day_factor` jour(s) au taux moyen (pondéré par les
        heures) des tronçons de la fenêtre ; applique la réduction rade au-delà de 96 h."""
        nonlocal rade_cum
        eff_rate = 0.0   # Σ (part d'heures) × taux × facteur_rade  → taux journalier effectif
        red_h = 0.0
        for is_rade, taux, h in segs:
            if is_rade:
                over = max(0.0, (rade_cum + h) - rade_seuil_h)
                over_in_seg = min(over, h)
                rade_cum += h
                eff_h = (h - over_in_seg) + 0.5 * over_in_seg
                red_h += over_in_seg
            else:
                eff_h = h
            eff_rate += (eff_h / denom) * vg * taux
        return eff_rate * day_factor, red_h

    # 1) Franchise 24 h (consommée, mais comptée dans l'occupation rade)
    for is_rade, _taux, h in take(franchise_h):
        if is_rade:
            rade_cum += h

    # 2) Tranches indivisibles de 24 h
    total = 0.0
    detail: list[dict] = []
    n = 0
    while pos["i"] < len(queue) and any(q[2] > 1e-9 for q in queue[pos["i"]:]):
        segs = take(24.0)
        win_h = sum(s[2] for s in segs)
        if win_h <= 1e-9:
            break
        n += 1
        if win_h >= 24.0 - 1e-9:
            cost, red_h = window_cost(segs, 1.0, 24.0)
            regle = "tranche pleine (24 h)"
        elif win_h <= 8.0:
            cost, red_h = window_cost(segs, 1.0 / 3.0, win_h)
            regle = f"résiduel {win_h:.1f} h ≤ 8 h → 1/3"
        else:
            cost, red_h = window_cost(segs, 1.0, win_h)
            regle = f"résiduel {win_h:.1f} h > 8 h → tranche pleine"
        total += cost
        detail.append({
            "tranche": n, "durée_h": round(win_h, 1), "règle": regle,
            "rade_réduit_h": round(red_h, 1), "montant": round(cost, 2),
        })
    return round(total, 2), detail


# ═══════════════════════════════════════════════════════════════════════════════
#  RENDU HTML DE LA FACTURE — mise en page « Autorité Portuaire » (imprimable / PDF)
# ═══════════════════════════════════════════════════════════════════════════════
def _num(v) -> str:
    """Nombre au format français : 12 345,67 (espace milliers, virgule décimale)."""
    try:
        return f"{float(v):,.2f}".replace(",", " ").replace(".", ",")
    except Exception:
        return ""


def _fmt(v, cur="EUR") -> str:
    return f"{_num(v)} {cur}"


def _plain(v) -> str:
    """Nombre « brut » façon Tanger Med : point décimal, sans séparateur de milliers,
    sans zéros inutiles (249.9, 44, 164274.26, 14.94)."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "" if v is None else str(v)
    if f == int(f):
        return str(int(f))
    return f"{f:.2f}".rstrip("0").rstrip(".")


@functools.lru_cache(maxsize=1)
def _logo_data_uri() -> str:
    """Logo NWM encodé en data URI (embarqué dans la facture autonome)."""
    path = os.path.join(os.path.dirname(__file__), "assets", "nwm_logo.png")
    try:
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("ascii")
        return f"data:image/png;base64,{b64}"
    except Exception:
        return ""


# --- Conversion d'un montant en toutes lettres (français) ---
_UNITS = ["zéro", "un", "deux", "trois", "quatre", "cinq", "six", "sept", "huit", "neuf",
          "dix", "onze", "douze", "treize", "quatorze", "quinze", "seize", "dix-sept",
          "dix-huit", "dix-neuf"]
_TENS = {20: "vingt", 30: "trente", 40: "quarante", 50: "cinquante", 60: "soixante",
         70: "soixante", 80: "quatre-vingt", 90: "quatre-vingt"}


def _below_100(n: int) -> str:
    if n < 20:
        return _UNITS[n]
    ten, unit = (n // 10) * 10, n % 10
    if ten in (70, 90):
        base = _TENS[ten] + "-" + _below_100(10 + unit)
        return base
    word = _TENS[ten]
    if unit == 1 and ten in (20, 30, 40, 50, 60):
        return word + "-et-un"
    if ten == 80 and unit == 0:
        return word + "s"
    return word + ("-" + _UNITS[unit] if unit else "")


def _below_1000(n: int) -> str:
    if n < 100:
        return _below_100(n)
    cent, rest = n // 100, n % 100
    prefix = "" if cent == 1 else _UNITS[cent] + " "
    if rest == 0:
        return (prefix + "cent" + ("s" if cent > 1 else "")).strip()
    return (prefix + "cent " + _below_100(rest)).strip()


def _int_en_lettres(n: int) -> str:
    if n == 0:
        return "zéro"
    parts, scales = [], [(10**9, "milliard"), (10**6, "million"), (1000, "mille")]
    for value, name in scales:
        if n >= value:
            count = n // value
            n %= value
            if name == "mille":
                head = "" if count == 1 else _below_1000(count) + " "
                parts.append((head + "mille").strip())
            else:
                plural = "s" if count > 1 else ""
                parts.append(_below_1000(count) + " " + name + plural)
    if n > 0:
        parts.append(_below_1000(n))
    return " ".join(parts)


def montant_en_lettres(total: float, devise: str = "EUR") -> str:
    """Ex. : 14 587,56 → 'Quatorze mille cinq cent quatre-vingt-sept Euros cinquante-six Cents'."""
    total = round(float(total), 2)
    euros = int(total)
    cents = int(round((total - euros) * 100))
    unite = {"EUR": ("Euro", "Euros"), "USD": ("Dollar", "Dollars"),
             "MAD": ("Dirham", "Dirhams")}.get(devise, ("Euro", "Euros"))
    mots = _int_en_lettres(euros).capitalize() + " " + (unite[1] if euros != 1 else unite[0])
    if cents:
        mots += " " + _int_en_lettres(cents) + (" Cents" if cents > 1 else " Cent")
    return mots


def render_invoice_html(inv: dict, company: dict, currency: str = "EUR",
                        fx_mad: float | None = None) -> str:
    """Génère une facture HTML autonome (mise en page Autorité Portuaire), imprimable."""
    lines = inv.get("lines", [])
    tot = invoice_totals(lines)
    total_ht = tot["total_ht"]
    v = inv.get("vessel", {})
    c = inv.get("call", {})
    logo = _logo_data_uri()

    # Lignes de prestations : Qté × Tarif unitaire = Montant (tarif unitaire effectif)
    body_rows = ""
    for l in lines:
        qte = float(l.get("quantite", 1) or 1)
        montant = float(l.get("montant_ht", 0) or 0)
        tarif_u = montant / qte if qte else montant
        maj = l.get("majoration") or 0
        nature = l.get("designation", "")
        if maj:
            nature += f' <span class="maj">({maj:+.0f} %)</span>'
        body_rows += (
            "<tr>"
            f'<td class="code">{l.get("code","")}</td>'
            f'<td>{nature}</td>'
            f'<td class="c">{l.get("unite","")}</td>'
            f'<td class="c">{_num(qte)}</td>'
            f'<td class="r">{_num(tarif_u)}</td>'
            f'<td class="r"></td>'
            f'<td class="r">{_num(montant)}</td>'
            "</tr>"
        )
    # Remplissage pour garder une hauteur de tableau stable
    filler = max(0, 8 - len(lines))
    for _ in range(filler):
        body_rows += ("<tr class='empty'><td></td><td></td><td></td><td></td>"
                      "<td></td><td></td><td></td></tr>")

    ttc = total_ht  # Zone Franche : pas de TVA
    mad_line = ""
    if fx_mad and currency == "EUR":
        mad_line = (f'<div class="cv">Contre-valeur : <b>{_fmt(total_ht*fx_mad, "MAD")}</b> '
                    f'(taux {fx_mad:.2f})</div>')

    swift = company.get("swift", "")
    rib_line = f"RIB : {company.get('rib','')}" + (f" — SWIFT : {swift}" if swift else "")
    multicanal = company.get("multicanal", "")
    multi_line = (f'<div class="pay">Paiement multicanal : <b>{multicanal}</b></div>'
                  if multicanal else "")

    tel = company.get("tel", "")
    web = company.get("web", "")
    foot_contact = " &nbsp;·&nbsp; ".join([x for x in [tel, web] if x])
    foot_contact = f"<br>{foot_contact}" if foot_contact else ""

    return f"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<title>Facture {inv.get('number','')}</title>
<style>
  @page {{ size:A4 portrait; margin:11mm 12mm; }}
  * {{ box-sizing:border-box; }}
  body {{ font-family:'Times New Roman', Georgia, serif; color:#1a1a1a; margin:0;
         padding:24px 26px; background:#fff; font-size:11px; line-height:1.3; }}
  .wrap {{ width:100%; max-width:190mm; margin:0 auto; min-height:273mm;
          display:flex; flex-direction:column; }}
  .top {{ display:flex; justify-content:space-between; align-items:flex-start; }}
  .top img {{ height:60px; }}
  .formcode {{ font-family:Arial, sans-serif; font-size:9.5px; color:#8a8a8a;
              letter-spacing:.5px; }}
  .page {{ text-align:right; font-weight:bold; font-size:13px; margin-top:16px;
          margin-bottom:6px; }}
  table {{ border-collapse:collapse; width:100%; }}
  .headgrid {{ display:flex; gap:18px; align-items:stretch; }}
  .headgrid > div {{ flex:1; display:flex; flex-direction:column; }}
  .bx td, .bx th {{ border:1px solid #111; padding:4px 7px; vertical-align:top; }}
  .facture-title {{ text-align:center; font-size:21px; font-weight:bold; letter-spacing:1px;
                    border:1px solid #111; border-bottom:none; padding:6px; }}
  .lbl {{ font-weight:bold; text-align:center; }}
  .client {{ border:1px solid #111; flex:1; display:flex; flex-direction:column;
            padding:8px 10px; }}
  .client .name {{ font-size:14px; font-weight:bold; }}
  .client .addr {{ margin-top:2px; }}
  .client .icebox {{ margin-top:auto; }}
  .client .icebox table td {{ border:1px solid #111; padding:4px 7px; text-align:center; }}
  .meta {{ margin-top:12px; }}
  .meta td {{ text-align:center; }}
  .info {{ margin-top:12px; }}
  .info td {{ padding:3px 5px; border:none; }}
  .info .k {{ font-weight:bold; white-space:nowrap; }}
  .info .val {{ border:1px solid #111; padding:3px 7px; min-width:96px; font-family:Arial, sans-serif;
              font-size:11.5px; }}
  table.items {{ margin-top:14px; border:1px solid #111; }}
  table.items th {{ border:1px solid #111; padding:6px 7px; font-weight:bold; text-align:center;
                    background:#ebedf0; }}
  table.items td {{ border-left:1px solid #111; border-right:1px solid #111; padding:5px 7px; }}
  table.items tbody tr:first-child td {{ padding-top:7px; }}
  table.items .code {{ font-weight:bold; white-space:nowrap; }}
  table.items tbody tr.empty td {{ height:20px; }}
  table.items tbody tr:last-child td {{ border-bottom:1px solid #111; }}
  .r {{ text-align:right; }} .c {{ text-align:center; }}
  .maj {{ color:#b00020; font-weight:bold; font-size:11px; }}
  table.totals {{ margin-top:14px; }}
  table.totals th {{ border:1px solid #111; background:#ebedf0; padding:6px; text-align:center; }}
  table.totals td {{ border:1px solid #111; padding:8px 10px; text-align:right; font-weight:bold;
                    font-size:13px; }}
  .charge {{ font-family:Arial, sans-serif; font-size:10px; color:#333; margin:6px 0 2px; }}
  .words {{ text-align:center; margin-top:14px; }}
  .words b {{ font-size:12.5px; }}
  .amount-words {{ font-size:14px; }}
  .reg {{ text-align:center; font-weight:bold; margin-top:5px; }}
  .pay, .cv {{ text-align:center; margin-top:4px; }}
  .fz {{ text-align:center; font-family:Arial, sans-serif; font-size:10px; color:#555;
        margin-top:8px; font-style:italic; }}
  .rule {{ border-top:2.5px solid #111; height:3px;
          border-bottom:1px solid #111; }}
  .pagefoot {{ margin-top:auto; padding-top:26px; }}
  .company {{ font-family:Arial, Helvetica, sans-serif; font-size:9.5px; color:#222;
             line-height:1.5; margin-top:6px; }}
  .company b {{ font-size:10px; }}
  @media print {{ body {{ padding:0; }} }}
</style></head><body><div class="wrap">

  <div class="top">
    <div>{f'<img src="{logo}" alt="NWM">' if logo else f"<b>{company.get('name','')}</b>"}</div>
    <div class="formcode">SUP_FAC_NWM_01</div>
  </div>
  <div class="page">Page 1 / 1</div>

  <div class="headgrid">
    <div>
      <div class="facture-title">FACTURE</div>
      <table class="bx"><tr>
        <td class="lbl">N° Pièce</td><td class="lbl">Date</td><td class="lbl">Code Client</td>
      </tr><tr>
        <td class="c">{inv.get('number','')}</td><td class="c">{inv.get('date','')}</td>
        <td class="c">{inv.get('client_code','')}</td>
      </tr><tr>
        <td class="lbl" colspan="2">Numéro du contrat</td><td class="c">{inv.get('contract','')}</td>
      </tr></table>
    </div>
    <div class="client">
      <div class="name">{inv.get('client_name','—')}</div>
      <div class="addr">{inv.get('client_address','')}</div>
      <div class="icebox">
        <table><tr>
          <td>ICE : {inv.get('client_ice','')}</td>
          <td>{inv.get('client_city','')}</td>
          <td>{inv.get('client_country','')}</td>
        </tr></table>
      </div>
    </div>
  </div>

  <table class="bx meta"><tr>
    <td class="lbl">Réf. Commande Client</td><td class="lbl">Date Commande</td>
    <td class="lbl">Mode Règlement</td><td class="lbl">Échéance</td><td class="lbl">Devise</td>
  </tr><tr>
    <td>{inv.get('po','')}</td><td>{inv.get('order_date','')}</td>
    <td>{company.get('conditions','30J')}</td><td>{inv.get('due','')}</td><td>{currency}</td>
  </tr></table>

  <table class="info"><tr>
    <td class="k">Numéro d'escale</td><td class="val">{c.get('ref','')}</td>
    <td class="k">Longueur hors tout</td><td class="val">{_plain(v.get('loa',0))}</td>
    <td class="k">Date / H d'entrée du port</td><td class="val">{c.get('eta','')}</td>
  </tr><tr>
    <td class="k">Nom du navire</td><td class="val">{v.get('name','')}</td>
    <td class="k">Gross Tonnage</td><td class="val">{_plain(v.get('gt',0))}</td>
    <td class="k">Date / H de sortie du port</td><td class="val">{c.get('etd','')}</td>
  </tr><tr>
    <td class="k">Référence PO</td><td class="val">{inv.get('po','')}</td>
    <td class="k">Volume Taxable</td><td class="val">{_plain(v.get('vg',0))}</td>
    <td class="k">Postes Occupés</td><td class="val">{c.get('berth','')}</td>
  </tr><tr>
    <td class="k">Largeur</td><td class="val">{_plain(v.get('beam',0))}</td>
    <td class="k">Tirant d'eau</td><td class="val">{_plain(v.get('draught_used',0))}</td>
    <td class="k">Terminal Arrivé</td><td class="val">{c.get('terminal','')}</td>
  </tr></table>

  <table class="items">
    <thead><tr>
      <th style="width:9%">Code</th><th>Nature</th><th style="width:8%">Unité</th>
      <th style="width:9%">Quantité</th><th style="width:13%">Tarif&nbsp;Unitaire</th>
      <th style="width:11%">Ristourne</th><th style="width:15%">Montant&nbsp;H.T</th>
    </tr></thead>
    <tbody>{body_rows}</tbody>
  </table>

  <table class="totals"><tr>
    <th style="width:40%">Total HT</th><th style="width:12%">TR</th>
    <th style="width:20%">Montant TR</th><th style="width:28%">Montant TTC</th>
  </tr><tr>
    <td>{_num(total_ht)}</td><td class="c">0 %</td><td></td><td>{_num(ttc)}</td>
  </tr></table>

  <div class="charge">{company.get('footer','Les frais et commissions sont à la charge du client.')}</div>
  <div class="words"><b>Arrêté la présente facture à la somme :</b>
    <span class="amount-words">{montant_en_lettres(total_ht, currency)}</span></div>
  <div class="reg">En votre aimable règlement, par virement au compte {company.get('bank','')}</div>
  <div class="reg">{rib_line}</div>
  {multi_line}
  {mad_line}
  <div class="fz">Zone Franche — montants exonérés de TVA.</div>

  <div class="pagefoot">
    <div class="rule"></div>
    <div class="company">
      <b>{company.get('name','')} — {company.get('legal','')}</b><br>
      R.C : {company.get('rc','')} &nbsp;-&nbsp; I.F : {company.get('if','')} &nbsp;-&nbsp;
      I.C.E : {company.get('ice','')}<br>
      {company.get('address','')}{foot_contact}
    </div>
  </div>
</div></body></html>"""

