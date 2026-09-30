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



# ═══════════════════════════════════════════════════════════════════════════════
#  RENDU PDF DE LA FACTURE (reportlab) — A4 portrait, pied de page en bas
# ═══════════════════════════════════════════════════════════════════════════════
def _s(v) -> str:
    """Nettoie le texte pour les polices standard PDF (WinAnsi) : remplace les
    caractères hors jeu (flèches, tirets longs, etc.) et garde les accents latins."""
    if v is None:
        return ""
    s = str(v)
    repl = {"→": ">", "←": "<", "↔": "<>", "–": "-", "—": "-",
            "•": "-", "√": "sqrt", "≈": "~", "²": "2", "³": "3",
            "…": "...", " ": " ", "’": "'", "‘": "'",
            "“": '"', "”": '"', "×": "x"}
    for a, b in repl.items():
        s = s.replace(a, b)
    try:
        s.encode("latin-1")
    except UnicodeEncodeError:
        s = s.encode("latin-1", "replace").decode("latin-1")
    return s


def render_invoice_pdf(inv: dict, company: dict, currency: str = "EUR",
                       fx_mad: float | None = None) -> bytes:
    """Génère la facture en PDF (A4 portrait) avec reportlab.

    Le pied de page légal (double filet + mentions NWM) est dessiné au bas de la
    page, sur toute la largeur, quelle que soit la longueur de la facture.
    """
    import io as _io
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle, Paragraph,
                                    Spacer, Image)

    lines = inv.get("lines", [])
    tot = invoice_totals(lines)
    total_ht = tot["total_ht"]
    v = inv.get("vessel", {})
    c = inv.get("call", {})

    PAGE_W, PAGE_H = A4
    L = 12 * mm
    U = PAGE_W - 2 * L                       # largeur utile
    GREY = colors.HexColor("#ebedf0")
    BLACK = colors.HexColor("#111111")
    RED = colors.HexColor("#b00020")

    def P(txt, font="Times-Roman", size=9, align=TA_LEFT, bold=False, color=BLACK,
          leading=None):
        st = ParagraphStyle("x", fontName=("Times-Bold" if bold else font), fontSize=size,
                            leading=leading or size + 1.5, alignment=align, textColor=color)
        return Paragraph(_s(txt), st)

    story = []

    # --- Bandeau logo + Page 1/1 ---
    logo_path = os.path.join(os.path.dirname(__file__), "assets", "nwm_logo.png")
    logo_cell = ""
    if os.path.exists(logo_path):
        img = Image(logo_path, width=34 * mm, height=34 * mm * 322 / 630)
        img.hAlign = "LEFT"
        logo_cell = img
    head = Table([[logo_cell, P("SUP_FAC_NWM_01", "Helvetica", 8, TA_RIGHT,
                                color=colors.HexColor("#8a8a8a"))]],
                 colWidths=[U * 0.6, U * 0.4])
    head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                              ("LEFTPADDING", (0, 0), (-1, -1), 0),
                              ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    story.append(head)
    story.append(Spacer(1, 10))
    story.append(P("Page 1 / 1", "Times-Bold", 10, TA_RIGHT))
    story.append(Spacer(1, 4))

    # --- En-tête : bloc FACTURE + bloc client ---
    LB = U * 0.47                            # largeur du bloc FACTURE (gauche)
    fact = Table(
        [[P("FACTURE", "Times-Bold", 16, TA_CENTER), "", ""],
         [P("N° Pièce", bold=True, align=TA_CENTER), P("Date", bold=True, align=TA_CENTER),
          P("Code Client", bold=True, align=TA_CENTER)],
         [P(inv.get("number", ""), align=TA_CENTER), P(inv.get("date", ""), align=TA_CENTER),
          P(inv.get("client_code", ""), align=TA_CENTER)],
         [P("Numéro du contrat", bold=True, align=TA_CENTER), "",
          P(inv.get("contract", ""), align=TA_CENTER)]],
        colWidths=[LB * 0.34, LB * 0.33, LB * 0.33],
        rowHeights=[26, 16, 20, 18])
    fact.setStyle(TableStyle([
        ("SPAN", (0, 0), (2, 0)), ("SPAN", (0, 3), (1, 3)),
        ("BOX", (0, 0), (-1, -1), 0.7, BLACK),
        ("INNERGRID", (0, 1), (-1, -1), 0.5, BLACK),
        ("LINEBELOW", (0, 0), (-1, 0), 0.7, BLACK),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))

    client = Table(
        [[P(inv.get("client_name", "—"), "Times-Bold", 11)],
         [P(inv.get("client_address", ""), size=9)],
         [""],
         [Table([[P("ICE : " + _s(inv.get("client_ice", "")), size=8.5, align=TA_CENTER),
                  P(inv.get("client_city", ""), size=8.5, align=TA_CENTER),
                  P(inv.get("client_country", ""), size=8.5, align=TA_CENTER)]],
                colWidths=[(U - LB - 6 * mm) * 0.5, (U - LB - 6 * mm) * 0.25,
                           (U - LB - 6 * mm) * 0.25])]],
        colWidths=[U - LB - 6 * mm], rowHeights=[18, 16, 22, 24])
    client.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.7, BLACK), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, 2), 6), ("TOPPADDING", (0, 0), (0, 0), 5),
        ("LEFTPADDING", (0, 3), (0, 3), 0), ("RIGHTPADDING", (0, 3), (0, 3), 0),
        ("BOTTOMPADDING", (0, 3), (0, 3), 0),
    ]))
    # nested ICE table borders
    client._cellvalues[3][0].setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.6, BLACK), ("INNERGRID", (0, 0), (-1, -1), 0.6, BLACK),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))

    header_row = Table([[fact, "", client]], colWidths=[LB, 6 * mm, U - LB - 6 * mm])
    header_row.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                    ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    story.append(header_row)
    story.append(Spacer(1, 10))

    # --- Ligne Réf commande / Devise ---
    meta = Table(
        [[P("Réf. Commande Client", bold=True, align=TA_CENTER),
          P("Date Commande", bold=True, align=TA_CENTER),
          P("Mode Règlement", bold=True, align=TA_CENTER),
          P("Échéance", bold=True, align=TA_CENTER), P("Devise", bold=True, align=TA_CENTER)],
         [P(inv.get("po", ""), align=TA_CENTER), P(inv.get("order_date", ""), align=TA_CENTER),
          P(company.get("conditions", "30J"), align=TA_CENTER),
          P(inv.get("due", ""), align=TA_CENTER), P(currency, align=TA_CENTER)]],
        colWidths=[U * 0.28, U * 0.2, U * 0.2, U * 0.18, U * 0.14])
    meta.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, BLACK),
                              ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                              ("TOPPADDING", (0, 0), (-1, -1), 3),
                              ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    story.append(meta)
    story.append(Spacer(1, 10))

    # --- Grille navire & escale ---
    def kv(label, value):
        return (P(label, "Helvetica-Bold", 8.5),
                Table([[P(_plain(value) if isinstance(value, (int, float)) else value,
                          "Helvetica", 8.5)]],
                      colWidths=[U / 3 - 78],
                      style=[("BOX", (0, 0), (-1, -1), 0.5, BLACK),
                             ("TOPPADDING", (0, 0), (-1, -1), 2),
                             ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                             ("LEFTPADDING", (0, 0), (-1, -1), 4)]))

    def kv_row(a, b, cc):
        return [kv(*a)[0], kv(*a)[1], kv(*b)[0], kv(*b)[1], kv(*cc)[0], kv(*cc)[1]]

    info = Table([
        kv_row(("Numéro d'escale", c.get("ref", "")),
               ("Longueur hors tout", v.get("loa", 0)),
               ("Date / H d'entrée du port", c.get("eta", ""))),
        kv_row(("Nom du navire", v.get("name", "")),
               ("Gross Tonnage", v.get("gt", 0)),
               ("Date / H de sortie du port", c.get("etd", ""))),
        kv_row(("Référence PO", inv.get("po", "")),
               ("Volume Taxable", v.get("vg", 0)),
               ("Postes Occupés", c.get("berth", ""))),
        kv_row(("Largeur", v.get("beam", 0)),
               ("Tirant d'eau", v.get("draught_used", 0)),
               ("Terminal Arrivé", c.get("terminal", ""))),
    ], colWidths=[78, U / 3 - 78, 78, U / 3 - 78, 78, U / 3 - 78])
    info.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                              ("LEFTPADDING", (0, 0), (-1, -1), 2),
                              ("RIGHTPADDING", (0, 0), (-1, -1), 2),
                              ("TOPPADDING", (0, 0), (-1, -1), 2.5),
                              ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5)]))
    story.append(info)
    story.append(Spacer(1, 12))

    # --- Tableau des prestations ---
    data = [[P("Code", bold=True, align=TA_CENTER), P("Nature", bold=True, align=TA_CENTER),
             P("Unité", bold=True, align=TA_CENTER), P("Quantité", bold=True, align=TA_CENTER),
             P("Tarif Unitaire", bold=True, align=TA_CENTER),
             P("Ristourne", bold=True, align=TA_CENTER),
             P("Montant H.T", bold=True, align=TA_CENTER)]]
    for l in lines:
        qte = float(l.get("quantite", 1) or 1)
        montant = float(l.get("montant_ht", 0) or 0)
        tarif_u = montant / qte if qte else montant
        maj = l.get("majoration") or 0
        nat = _s(l.get("designation", ""))
        nat_p = (nat + f'  <font color="#b00020"><b>({maj:+.0f} %)</b></font>') if maj else nat
        data.append([P(l.get("code", ""), bold=True),
                     P(nat_p),
                     P(l.get("unite", ""), align=TA_CENTER),
                     P(_num(qte), align=TA_CENTER),
                     P(_num(tarif_u), align=TA_RIGHT),
                     P("", align=TA_RIGHT),
                     P(_num(montant), align=TA_RIGHT)])
    for _ in range(max(0, 8 - len(lines))):
        data.append(["", "", "", "", "", "", ""])
    cw = [0.09, 0.365, 0.075, 0.085, 0.13, 0.10, 0.155]
    items = Table(data, colWidths=[U * x for x in cw])
    items.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), GREY),
        ("BOX", (0, 0), (-1, -1), 0.7, BLACK),
        ("LINEBELOW", (0, 0), (-1, 0), 0.7, BLACK),
        ("LINEAFTER", (0, 0), (-2, -1), 0.5, BLACK),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(items)
    story.append(Spacer(1, 12))

    # --- Totaux ---
    totals = Table(
        [[P("Total HT", bold=True, align=TA_CENTER), P("TR", bold=True, align=TA_CENTER),
          P("Montant TR", bold=True, align=TA_CENTER),
          P("Montant TTC", bold=True, align=TA_CENTER)],
         [P(_num(total_ht), bold=True, align=TA_RIGHT), P("0 %", bold=True, align=TA_CENTER),
          P("", align=TA_RIGHT), P(_num(total_ht), bold=True, align=TA_RIGHT)]],
        colWidths=[U * 0.4, U * 0.12, U * 0.2, U * 0.28])
    totals.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.6, BLACK),
                                ("BACKGROUND", (0, 0), (-1, 0), GREY),
                                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                                ("TOPPADDING", (0, 0), (-1, -1), 5),
                                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                                ("RIGHTPADDING", (0, 1), (0, 1), 8),
                                ("RIGHTPADDING", (3, 1), (3, 1), 8)]))
    story.append(totals)
    story.append(Spacer(1, 6))

    story.append(P("Les frais et commissions sont à la charge du client.", "Helvetica", 8))
    story.append(Spacer(1, 8))
    words = f'<b>Arrêté la présente facture à la somme :</b> <font size="12">{_s(montant_en_lettres(total_ht, currency))}</font>'
    story.append(P(words, size=11, align=TA_CENTER))
    story.append(Spacer(1, 3))
    story.append(P("En votre aimable règlement, par virement au compte " +
                   _s(company.get("bank", "")), bold=True, align=TA_CENTER))
    swift = company.get("swift", "")
    rib = "RIB : " + _s(company.get("rib", "")) + (" - SWIFT : " + _s(swift) if swift else "")
    story.append(P(rib, bold=True, align=TA_CENTER))
    if company.get("multicanal"):
        story.append(P("Paiement multicanal : <b>" + _s(company["multicanal"]) + "</b>",
                       align=TA_CENTER))
    if fx_mad and currency == "EUR":
        story.append(P(f'Contre-valeur : <b>{_num(total_ht*fx_mad)} MAD</b> (taux {fx_mad:.2f})',
                       align=TA_CENTER))
    story.append(P("Zone Franche — montants exonérés de TVA.", "Helvetica-Oblique", 8.5,
                   TA_CENTER, color=colors.HexColor("#555555")))

    # --- Pied de page (dessiné en bas à chaque page) ---
    def _footer(canvas, doc):
        canvas.saveState()
        x0, x1 = L, PAGE_W - L
        yr = 26 * mm
        canvas.setStrokeColor(BLACK)
        canvas.setLineWidth(2.2)
        canvas.line(x0, yr, x1, yr)
        canvas.setLineWidth(0.6)
        canvas.line(x0, yr - 2.4, x1, yr - 2.4)
        y = yr - 12
        canvas.setFillColor(BLACK)
        canvas.setFont("Helvetica-Bold", 8)
        canvas.drawString(x0, y, _s(f"{company.get('name','')} — {company.get('legal','')}"))
        canvas.setFont("Helvetica", 7.5)
        y -= 10
        canvas.drawString(x0, y, _s(
            f"R.C : {company.get('rc','')}  -  I.F : {company.get('if','')}  -  "
            f"I.C.E : {company.get('ice','')}"))
        y -= 10
        canvas.drawString(x0, y, _s(company.get("address", "")))
        extra = "  ".join(x for x in [company.get("tel", ""), company.get("web", "")] if x)
        if extra:
            y -= 10
            canvas.drawString(x0, y, _s(extra))
        canvas.restoreState()

    buf = _io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=L, rightMargin=L,
                            topMargin=12 * mm, bottomMargin=34 * mm,
                            title=f"Facture {inv.get('number','')}")
    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buf.getvalue()
