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

import math
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

    Modèle (transparent) conforme au Cahier Tarifaire NWM Avril 2025 :
      • franchise de 24 h appliquée aux toutes premières heures de l'escale ;
      • taux de base au prorata horaire (VG × taux / 24) au-delà de la franchise ;
      • mouillage en rade : 50 % du taux dès le 5ᵉ jour d'utilisation (au-delà de 96 h cumulées).

    Renvoie (montant, détail_par_tronçon).
    """
    elapsed = 0.0        # heures écoulées depuis l'arrivée
    rade_elapsed = 0.0   # heures cumulées passées en rade
    total = 0.0
    detail: list[dict] = []
    for leg in legs:
        taux = float(leg.get("taux", 0) or 0)
        dur = float(leg.get("dur_h", 0) or 0)
        is_rade = bool(leg.get("is_rade"))
        hourly = vg * taux / 24.0
        seg_cost = 0.0
        seg_franchise = 0.0
        seg_rade_red = 0.0
        remaining = dur
        while remaining > 1e-9:
            step = min(1.0, remaining)
            remaining -= step
            in_franchise = elapsed < franchise_h
            elapsed += step
            if is_rade:
                rade_elapsed += step
            if in_franchise:
                seg_franchise += step
                continue
            reduced = is_rade and rade_elapsed > rade_seuil_h
            rate = hourly * (0.5 if reduced else 1.0)
            seg_cost += rate * step
            if reduced:
                seg_rade_red += step
        total += seg_cost
        detail.append({
            "tronçon": leg.get("label", ""), "rade": is_rade,
            "durée_h": round(dur, 1), "franchise_h": round(seg_franchise, 1),
            "rade_réduit_h": round(seg_rade_red, 1), "montant": round(seg_cost, 2),
        })
    return round(total, 2), detail


# ═══════════════════════════════════════════════════════════════════════════════
#  RENDU HTML DE LA FACTURE (imprimable / export PDF navigateur)
# ═══════════════════════════════════════════════════════════════════════════════
def _fmt(v, cur="EUR"):
    try:
        return f"{float(v):,.2f}".replace(",", " ").replace(".", ",") + f" {cur}"
    except Exception:
        return str(v)


def render_invoice_html(inv: dict, company: dict, currency: str = "EUR",
                        fx_mad: float | None = None) -> str:
    """Génère une facture HTML autonome, imprimable (Ctrl+P → PDF)."""
    lines = inv.get("lines", [])
    tot = invoice_totals(lines)

    rows = ""
    for i, l in enumerate(lines, 1):
        maj = f' <span class="maj">{l["majoration"]:+.0f}%</span>' if l.get("majoration") else ""
        rows += f"""
        <tr>
          <td class="c">{i}</td>
          <td><span class="code">{l.get('code','')}</span> {l.get('designation','')}{maj}</td>
          <td class="r">{l.get('quantite',0):,.2f}</td>
          <td class="c">{l.get('unite','')}</td>
          <td class="r">{l.get('pu',0):,.4f}</td>
          <td class="r b">{_fmt(l.get('montant_ht',0), currency)}</td>
        </tr>"""

    fx_block = ""
    if fx_mad:
        fx_block = f"""
        <tr><td class="lbl">Contre-valeur (MAD)</td>
        <td class="val">{_fmt(tot['total_ht']*fx_mad, 'MAD')}</td></tr>"""

    v = inv.get("vessel", {})
    c = inv.get("call", {})

    # Tirant d'eau retenu pour le calcul du VG (min théorique 0,14·√(L·B) si supérieur)
    te_used = v.get("draught_used")
    te_decl = v.get("draught_declared")
    if te_used is not None:
        if te_decl is not None and te_used > te_decl:
            draught_str = (f"{te_used:.2f} m <span style='color:#c0392b'>(min. théorique ; "
                           f"déclaré {te_decl:.2f} m)</span>")
        else:
            draught_str = f"{te_used:.2f} m"
        draught_row = f'<p><span class="k">Tirant retenu</span>{draught_str}</p>'
    else:
        draught_row = ""

    return f"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<title>Facture {inv.get('number','')}</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{ font-family: 'Segoe UI', Arial, sans-serif; color:#1a2b3c; margin:0; padding:32px;
         background:#fff; }}
  .wrap {{ max-width: 900px; margin:0 auto; }}
  header {{ display:flex; justify-content:space-between; align-items:flex-start;
           border-bottom:3px solid #0b6e99; padding-bottom:18px; }}
  .brand h1 {{ margin:0; font-size:22px; color:#0b3c5d; letter-spacing:.5px; }}
  .brand p  {{ margin:2px 0; font-size:12px; color:#5a6b7a; }}
  .doc {{ text-align:right; }}
  .doc h2 {{ margin:0; font-size:28px; color:#0b6e99; letter-spacing:2px; }}
  .doc .num {{ font-size:14px; font-weight:600; }}
  .doc .meta {{ font-size:12px; color:#5a6b7a; }}
  .parties {{ display:flex; gap:24px; margin:24px 0; }}
  .card {{ flex:1; background:#f4f8fb; border:1px solid #dce7ef; border-radius:8px; padding:14px 16px; }}
  .card h3 {{ margin:0 0 8px; font-size:11px; text-transform:uppercase; letter-spacing:1px;
            color:#0b6e99; }}
  .card p {{ margin:2px 0; font-size:13px; }}
  .card .k {{ color:#7a8b99; display:inline-block; min-width:92px; }}
  table.items {{ width:100%; border-collapse:collapse; margin-top:8px; font-size:12.5px; }}
  table.items thead th {{ background:#0b3c5d; color:#fff; padding:9px 8px; text-align:left;
                          font-weight:600; font-size:11px; text-transform:uppercase; }}
  table.items td {{ padding:8px; border-bottom:1px solid #e6edf2; }}
  table.items tbody tr:nth-child(even) {{ background:#f8fbfd; }}
  .r {{ text-align:right; }} .c {{ text-align:center; }} .b {{ font-weight:600; }}
  .code {{ display:inline-block; background:#e3f0f7; color:#0b6e99; font-size:10px;
          padding:1px 6px; border-radius:4px; font-weight:600; margin-right:4px; }}
  .maj {{ color:#c0392b; font-size:11px; font-weight:600; }}
  .totals {{ margin-top:18px; margin-left:auto; width:340px; }}
  .totals table {{ width:100%; border-collapse:collapse; font-size:13px; }}
  .totals td {{ padding:7px 10px; }}
  .totals .lbl {{ color:#5a6b7a; }} .totals .val {{ text-align:right; font-weight:600; }}
  .totals .grand td {{ background:#0b6e99; color:#fff; font-size:16px; font-weight:700;
                       border-radius:6px; }}
  .fz {{ text-align:right; font-size:11px; color:#7a8b99; margin-top:8px; font-style:italic; }}
  footer {{ margin-top:32px; border-top:1px solid #dce7ef; padding-top:14px; font-size:11px;
           color:#7a8b99; text-align:center; }}
  @media print {{ body {{ padding:0; }} .noprint {{ display:none; }} }}
</style></head><body><div class="wrap">
  <header>
    <div class="brand">
      <h1>{company.get('name','Nador West Med')}</h1>
      <p>{company.get('address','Port de Nador West Med, Maroc')}</p>
      <p>ICE : {company.get('ice','—')} &nbsp;•&nbsp; IF : {company.get('if','—')}</p>
    </div>
    <div class="doc">
      <h2>FACTURE</h2>
      <p class="num">N° {inv.get('number','')}</p>
      <p class="meta">Date : {inv.get('date','')}</p>
      <p class="meta">Échéance : {inv.get('due','')}</p>
    </div>
  </header>

  <div class="parties">
    <div class="card">
      <h3>Client / Armateur</h3>
      <p><strong>{inv.get('client_name','—')}</strong></p>
      <p>{inv.get('client_address','')}</p>
      <p><span class="k">Réf. escale</span>{c.get('ref','')}</p>
    </div>
    <div class="card">
      <h3>Navire & Escale</h3>
      <p><span class="k">Navire</span><strong>{v.get('name','—')}</strong></p>
      <p><span class="k">IMO / Pavillon</span>{v.get('imo','—')} / {v.get('flag','—')}</p>
      <p><span class="k">GT / VG</span>{v.get('gt',0):,.0f} / {v.get('vg',0):,.0f} m³</p>
      {draught_row}
      <p><span class="k">Terminal</span>{c.get('terminal','—')}</p>
      <p><span class="k">Poste / Séjour</span>{c.get('berth','—')} • {c.get('sejour_h',0):.0f} h</p>
    </div>
  </div>

  <table class="items">
    <thead><tr>
      <th style="width:32px">#</th><th>Désignation</th><th class="r">Qté</th>
      <th class="c">Unité</th><th class="r">P.U.</th><th class="r">Montant</th>
    </tr></thead>
    <tbody>{rows}</tbody>
  </table>

  <div class="totals"><table>
    <tr class="grand"><td>TOTAL À PAYER</td><td class="r">{_fmt(tot['total_ht'], currency)}</td></tr>
    {fx_block}
  </table>
  <p class="fz">Exonéré de TVA — Zone Franche (art. régime de zone franche).</p>
  </div>

  <footer>
    {company.get('name','Nador West Med')} — {company.get('footer','Merci pour votre confiance. Règlement à 30 jours par virement bancaire.')}<br>
    Facture générée par le Simulateur d'Escales NWM le {datetime.now():%d/%m/%Y à %H:%M}.
  </footer>
</div></body></html>"""
