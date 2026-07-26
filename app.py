"""
app.py — Simulateur d'Escales & Facturation Portuaire (Nador West Med)
=====================================================================

Application Streamlit permettant de :
  • Gérer une flotte de navires (référentiel)
  • Gérer un catalogue tarifaire éditable (ajouter / modifier / supprimer des articles)
  • Créer des escales pour différents navires, terminaux et types de mouvement
  • Générer automatiquement les prestations puis les éditer (ajout de lignes libres)
  • Émettre des factures dynamiques et les exporter (HTML imprimable + CSV)

Lancement :  streamlit run app.py
"""
from __future__ import annotations

import io
import math
import uuid
from datetime import date, datetime, timedelta

import pandas as pd
import streamlit as st

import billing
import storage
import tarifs_data as td

# ═══════════════════════════════════════════════════════════════════════════════
#  CONFIGURATION & THÈME
# ═══════════════════════════════════════════════════════════════════════════════
st.set_page_config(
    page_title="Escales & Facturation — NWM",
    page_icon="⚓",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
  .main .block-container { padding-top: 1.6rem; max-width: 1400px; }
  h1, h2, h3 { color: #0b3c5d; }
  div[data-testid="stMetric"] {
      background: linear-gradient(135deg,#f4f8fb,#e9f2f8);
      border: 1px solid #dce7ef; border-radius: 12px; padding: 14px 16px;
  }
  div[data-testid="stMetricValue"] { color:#0b6e99; font-weight:700; }
  .stTabs [data-baseweb="tab-list"] { gap: 4px; }
  .stTabs [data-baseweb="tab"] {
      background:#eef4f8; border-radius:8px 8px 0 0; padding:8px 16px; font-weight:600;
  }
  .stTabs [aria-selected="true"] { background:#0b6e99; color:#fff; }
  .pill { display:inline-block; background:#e3f0f7; color:#0b6e99; padding:2px 10px;
          border-radius:20px; font-size:12px; font-weight:600; margin:2px; }
  .pill.warn { background:#fdecea; color:#c0392b; }
  .pill.ok   { background:#e8f5e9; color:#2e7d32; }
</style>
""", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════════
#  ÉTAT / SEED
# ═══════════════════════════════════════════════════════════════════════════════
def _seed_vessels() -> list[dict]:
    return [
        {"id": str(uuid.uuid4()), "name": "MSC LEONI", "type": "Porte-conteneurs",
         "imo": "9401234", "flag": "Panama", "gt": 95000, "loa": 300.0, "beam": 40.0, "draft": 14.5},
        {"id": str(uuid.uuid4()), "name": "STENA FORECASTER", "type": "Roulier / RoRo",
         "imo": "9337123", "flag": "Chypre", "gt": 24000, "loa": 195.0, "beam": 26.5, "draft": 7.4},
        {"id": str(uuid.uuid4()), "name": "GAS VENTURE", "type": "Gazier (LPG)",
         "imo": "9512345", "flag": "Libéria", "gt": 48000, "loa": 230.0, "beam": 36.0, "draft": 11.2},
    ]


_DEFAULT_COMPANY = {
    "name": "Nador West Med — Autorité Portuaire",
    "address": "Port de Nador West Med, Betoya, Maroc",
    "ice": "0027 5896 000 084", "if": "5289 3410",
    "footer": "Règlement à 30 jours par virement bancaire. Zone Franche — "
              "montants exonérés de TVA.",
}


def init_state():
    """Charge l'état persisté (SQLite) une fois par session ; sème les valeurs par
    défaut et initialise la base si celle-ci est vide."""
    ss = st.session_state
    if not ss.get("_loaded"):
        persisted = storage.load_state()
        ss.vessels = persisted.get("vessels", _seed_vessels())
        ss.catalog = persisted.get("catalog", billing.default_catalog())
        ss.calls = persisted.get("calls", [])
        ss.invoices = persisted.get("invoices", [])
        ss.inv_seq = persisted.get("inv_seq", 1)
        # Fusion avec les valeurs par défaut : garantit la présence de toutes les clés
        # même si un enregistrement antérieur était partiel ou d'un ancien modèle.
        ss.company = {**_DEFAULT_COMPANY, **(persisted.get("company") or {})}
        ss._loaded = True
        if not persisted:  # première exécution : on initialise la base
            storage.save_state({k: ss[k] for k in storage.KEYS if k in ss})
    if "currency" not in ss:
        ss.currency = "EUR"
    if "fx_mad" not in ss:
        ss.fx_mad = 10.85


init_state()
SS = st.session_state


def persist():
    """Enregistre l'état applicatif courant dans la base SQLite."""
    storage.save_state({k: SS[k] for k in storage.KEYS if k in SS})


# ═══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════════════════
def vessel_by_id(vid):
    return next((v for v in SS.vessels if v["id"] == vid), None)


def vessel_vg(v):
    return td.calc_vg(v["loa"], v["beam"], v["draft"]) if v else 0.0


def draught_info(v):
    """Renvoie (tirant_déclaré, tirant_min_théorique, tirant_retenu, min_appliqué)."""
    if not v:
        return 0.0, 0.0, 0.0, False
    te_min = 0.14 * math.sqrt(v["loa"] * v["beam"])
    te_ret = max(v["draft"], te_min)
    return v["draft"], te_min, te_ret, te_min > v["draft"]


def money(v, cur=None):
    cur = cur or SS.currency
    try:
        return f"{float(v):,.2f} {cur}"
    except Exception:
        return f"— {cur}"


def terminals():
    return list(td.DROITS_PORT_NAVIRES_NWM.keys())


MOVEMENTS = [
    "Arrivée / Mouillage", "Accostage", "Changement de quai (shifting)",
    "Retour mouillage", "Appareillage / Départ", "Autre mouvement",
]


def default_itinerary() -> pd.DataFrame:
    """Itinéraire d'exemple : mouillage → accostage → shifting → mouillage → départ,
    sur plusieurs terminaux."""
    t0 = datetime.combine(date.today(), datetime.min.time()) + timedelta(hours=8)
    #        mouvement, emplacement, datetime, pilotage, pil_h, pil_maj, remorqueurs, rem_maj, lamanage, lam_h
    rows = [
        ("Arrivée / Mouillage",           "Rade (mouillage)",       t0,                       True,  2.0, 0.0, 0, 0.0, False, 2.0),
        ("Accostage",                     "TCE — Conteneurs Est",   t0 + timedelta(hours=10), True,  2.0, 0.0, 2, 0.0, True,  2.0),
        ("Changement de quai (shifting)", "TCO — Conteneurs Ouest", t0 + timedelta(hours=28), True,  2.0, 0.0, 2, 0.0, True,  2.0),
        ("Retour mouillage",              "Rade (mouillage)",       t0 + timedelta(hours=40), True,  2.0, 0.0, 1, 0.0, True,  2.0),
        ("Appareillage / Départ",         "Rade (mouillage)",       t0 + timedelta(hours=58), True,  2.0, 0.0, 2, 0.0, False, 2.0),
    ]
    return pd.DataFrame(rows, columns=[
        "mouvement", "emplacement", "datetime", "pilotage", "pil_h", "pil_maj",
        "remorqueurs", "rem_maj", "lamanage", "lam_h"])


def catalog_df():
    return pd.DataFrame(SS.catalog)


# ═══════════════════════════════════════════════════════════════════════════════
#  EN-TÊTE & SIDEBAR
# ═══════════════════════════════════════════════════════════════════════════════
st.markdown(
    "<h1 style='margin-bottom:0'>⚓ Simulateur d'Escales & Facturation Portuaire</h1>"
    "<p style='color:#5a6b7a;margin-top:4px;font-size:15px'>"
    "Nador West Med · création d'escales, chiffrage automatique des prestations et "
    "génération de factures dynamiques</p>",
    unsafe_allow_html=True,
)

with st.sidebar:
    st.header("🏢 Émetteur")
    SS.company["name"] = st.text_input("Raison sociale", SS.company["name"])
    SS.company["address"] = st.text_input("Adresse", SS.company["address"])
    c1, c2 = st.columns(2)
    SS.company["ice"] = c1.text_input("ICE", SS.company["ice"])
    SS.company["if"] = c2.text_input("IF", SS.company["if"])

    st.divider()
    st.header("💱 Devise")
    SS.currency = st.selectbox("Devise de facturation", ["EUR", "MAD", "USD"], index=0)
    SS.fx_mad = st.number_input("Taux EUR → MAD (contre-valeur)", value=float(SS.fx_mad),
                                step=0.05, format="%.2f")

    st.divider()
    st.caption(
        f"📊 {len(SS.vessels)} navires · {len(SS.catalog)} articles · "
        f"{len(SS.calls)} escales · {len(SS.invoices)} factures"
    )
    _dbi = storage.db_info()
    st.caption(f"💾 Données persistées (SQLite) · {_dbi['size_kb']} Ko"
               if _dbi["exists"] else "💾 Persistance SQLite active")
    if st.button("↺ Réinitialiser les données", use_container_width=True):
        storage.clear_state()
        for k in ["vessels", "catalog", "calls", "invoices", "inv_seq", "company",
                  "_loaded", "active_call_ref", "active_call", "active_invoice"]:
            SS.pop(k, None)
        init_state()
        st.success("Données réinitialisées.")
        st.rerun()


tab_dash, tab_vessels, tab_catalog, tab_calls, tab_invoice = st.tabs(
    ["📈 Tableau de bord", "🚢 Navires", "📖 Catalogue tarifaire",
     "🛳️ Escales", "🧾 Factures"]
)


# ═══════════════════════════════════════════════════════════════════════════════
#  TAB : TABLEAU DE BORD
# ═══════════════════════════════════════════════════════════════════════════════
with tab_dash:
    n_calls = len(SS.calls)
    n_inv = len(SS.invoices)
    ca_ht = sum(billing.invoice_totals(c["lines"])["total_ht"] for c in SS.calls)
    n_vessels = len(SS.vessels)

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Navires", n_vessels)
    k2.metric("Escales", n_calls)
    k3.metric("Factures émises", n_inv)
    k4.metric("CA prévisionnel", money(ca_ht))

    st.divider()

    if SS.calls:
        # Répartition du CA par catégorie de prestation
        rows = []
        for c in SS.calls:
            for l in c["lines"]:
                cat = next((it["category"] for it in SS.catalog if it["code"] == l["code"]),
                           "Divers")
                rows.append({"Catégorie": cat, "Montant HT": l["montant_ht"]})
        if rows:
            dfc = pd.DataFrame(rows).groupby("Catégorie", as_index=False)["Montant HT"].sum()
            dfc = dfc.sort_values("Montant HT", ascending=False)
            cc1, cc2 = st.columns([3, 2])
            with cc1:
                st.subheader("Revenu par catégorie de prestation")
                st.bar_chart(dfc.set_index("Catégorie"), height=340)
            with cc2:
                st.subheader("Détail")
                st.dataframe(
                    dfc.assign(**{"Montant HT": dfc["Montant HT"].map(lambda x: money(x))}),
                    hide_index=True, use_container_width=True,
                )

        st.subheader("Escales récentes")
        recap = []
        for c in SS.calls:
            v = vessel_by_id(c["vessel_id"])
            t = billing.invoice_totals(c["lines"])
            recap.append({
                "Réf": c["ref"], "Navire": v["name"] if v else "—",
                "Terminal": c["terminal"], "Arrivée": c["eta"],
                "Lignes": len(c["lines"]),
                "Total": money(t["total_ht"]),
                "Statut": c.get("status", "Brouillon"),
            })
        st.dataframe(pd.DataFrame(recap), hide_index=True, use_container_width=True)
    else:
        st.info("Aucune escale enregistrée. Rendez-vous dans l'onglet **🛳️ Escales** "
                "pour créer votre première escale et générer une facture.")


# ═══════════════════════════════════════════════════════════════════════════════
#  TAB : NAVIRES
# ═══════════════════════════════════════════════════════════════════════════════
with tab_vessels:
    st.subheader("🚢 Référentiel des navires")
    st.caption("Le Volume Géométrique (VG) est calculé automatiquement : "
               "VG = LOA × largeur × tirant d'eau (avec tirant minimum réglementaire).")

    with st.expander("➕ Ajouter un navire", expanded=not SS.vessels):
        with st.form("add_vessel", clear_on_submit=True):
            a, b, c = st.columns(3)
            name = a.text_input("Nom du navire *")
            vtype = b.selectbox("Type", ["Porte-conteneurs", "Roulier / RoRo", "Vraquier",
                                         "Pétrolier", "Gazier (LPG)", "Marchandises diverses",
                                         "Ferry / Passagers", "Autre"])
            flag = c.text_input("Pavillon", "Maroc")
            d, e, f, g, h = st.columns(5)
            imo = d.text_input("N° IMO", "")
            gt = e.number_input("GT", min_value=0.0, value=20000.0, step=500.0)
            loa = f.number_input("LOA (m)", min_value=0.0, value=180.0, step=1.0)
            beam = g.number_input("Largeur (m)", min_value=0.0, value=28.0, step=0.5)
            draft = h.number_input("Tirant d'eau (m)", min_value=0.0, value=9.0, step=0.1)
            if st.form_submit_button("Enregistrer le navire", type="primary"):
                if not name:
                    st.error("Le nom du navire est obligatoire.")
                else:
                    SS.vessels.append({
                        "id": str(uuid.uuid4()), "name": name, "type": vtype, "imo": imo,
                        "flag": flag, "gt": gt, "loa": loa, "beam": beam, "draft": draft,
                    })
                    st.success(f"Navire « {name} » ajouté.")
                    st.rerun()

    if SS.vessels:
        disp = []
        for v in SS.vessels:
            _decl, _min, _ret, _applied = draught_info(v)
            disp.append({
                "Navire": v["name"], "Type": v["type"], "IMO": v["imo"], "Pavillon": v["flag"],
                "GT": f"{v['gt']:,.0f}", "LOA": v["loa"], "Largeur": v["beam"],
                "TE déclaré (m)": f"{_decl:.2f}",
                "Tirant retenu (m)": f"{_ret:.2f}{' ⚠️' if _applied else ''}",
                "VG (m³)": f"{vessel_vg(v):,.0f}",
            })
        st.dataframe(pd.DataFrame(disp), hide_index=True, use_container_width=True)
        if any(draught_info(v)[3] for v in SS.vessels):
            st.caption("⚠️ Tirant retenu = minimum théorique 0,14·√(L·B), supérieur au "
                       "tirant déclaré (appliqué au calcul du VG).")

        col_del, _ = st.columns([2, 4])
        with col_del:
            todel = st.selectbox("Supprimer un navire",
                                 ["—"] + [v["name"] for v in SS.vessels])
            if todel != "—" and st.button("🗑️ Supprimer", key="del_vessel"):
                SS.vessels = [v for v in SS.vessels if v["name"] != todel]
                st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
#  TAB : CATALOGUE TARIFAIRE
# ═══════════════════════════════════════════════════════════════════════════════
with tab_catalog:
    st.subheader("📖 Catalogue tarifaire (rate card NWM)")
    st.caption("Ajoutez, modifiez ou supprimez des articles. La colonne **base de calcul** "
               "détermine comment le montant est chiffré lors d'une escale.")

    with st.expander("ℹ️ Bases de calcul disponibles"):
        st.dataframe(
            pd.DataFrame([{"Base": k, "Signification": v} for k, v in billing.BASIS_LABEL.items()]),
            hide_index=True, use_container_width=True,
        )

    with st.expander("➕ Ajouter un article au catalogue"):
        with st.form("add_item", clear_on_submit=True):
            a, b, c = st.columns([1, 2, 2])
            code = a.text_input("Code *", "")
            category = b.text_input("Catégorie", "Services")
            label = c.text_input("Désignation *", "")
            d, e, f = st.columns(3)
            unit = d.text_input("Unité", "u")
            rate = e.number_input("Tarif unitaire", min_value=0.0, value=0.0, step=0.01,
                                  format="%.5f")
            basis = f.selectbox("Base de calcul", billing.BASES,
                                format_func=lambda x: f"{x} — {billing.BASIS_LABEL[x]}")
            if st.form_submit_button("Ajouter l'article", type="primary"):
                if not code or not label:
                    st.error("Code et désignation sont obligatoires.")
                elif any(it["code"] == code for it in SS.catalog):
                    st.error(f"Le code « {code} » existe déjà.")
                else:
                    SS.catalog.append({
                        "code": code, "category": category, "label": label, "unit": unit,
                        "rate": rate, "basis": basis, "vat": 0.0, "taxable": False,
                        "active": True,
                    })
                    st.success(f"Article « {code} » ajouté.")
                    st.rerun()

    st.markdown("##### Articles du catalogue (édition en place)")
    edited = st.data_editor(
        catalog_df(),
        hide_index=True, use_container_width=True, num_rows="dynamic",
        key="catalog_editor",
        column_config={
            "code": st.column_config.TextColumn("Code", width="small"),
            "category": st.column_config.TextColumn("Catégorie"),
            "label": st.column_config.TextColumn("Désignation", width="large"),
            "unit": st.column_config.TextColumn("Unité", width="small"),
            "rate": st.column_config.NumberColumn("Tarif", format="%.5f"),
            "basis": st.column_config.SelectboxColumn("Base", options=billing.BASES),
            "vat": None,
            "taxable": None,
            "active": st.column_config.CheckboxColumn("Actif"),
        },
    )
    cc1, cc2 = st.columns([1, 5])
    if cc1.button("💾 Enregistrer le catalogue", type="primary"):
        SS.catalog = edited.to_dict("records")
        st.success("Catalogue mis à jour.")
    if cc2.button("↺ Recharger tarifs NWM par défaut"):
        SS.catalog = billing.default_catalog()
        st.rerun()

    st.download_button(
        "⬇️ Exporter le catalogue (CSV)",
        catalog_df().to_csv(index=False).encode("utf-8"),
        file_name="catalogue_tarifaire_nwm.csv", mime="text/csv",
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  TAB : ESCALES
# ═══════════════════════════════════════════════════════════════════════════════
with tab_calls:
    st.subheader("🛳️ Créer / gérer une escale")

    if not SS.vessels:
        st.warning("Ajoutez d'abord un navire dans l'onglet **🚢 Navires**.")
    else:
        left, right = st.columns([1, 1])

        # ---- Paramètres de l'escale
        with left:
            st.markdown("##### 1 · Navire & escale")
            vname = st.selectbox("Navire", [v["name"] for v in SS.vessels])
            vessel = next(v for v in SS.vessels if v["name"] == vname)
            vg = vessel_vg(vessel)
            te_decl, te_min, te_ret, te_applied = draught_info(vessel)
            st.markdown(
                f"<span class='pill'>GT {vessel['gt']:,.0f}</span>"
                f"<span class='pill'>VG {vg:,.0f} m³</span>"
                f"<span class='pill{' warn' if te_applied else ''}'>Tirant retenu {te_ret:.2f} m</span>"
                f"<span class='pill'>{vessel['type']}</span>",
                unsafe_allow_html=True,
            )
            if te_applied:
                st.caption(f"⚓ Tirant déclaré {te_decl:.2f} m < minimum théorique "
                           f"0,14·√(L·B) = **{te_min:.2f} m** → tirant retenu **{te_ret:.2f} m** "
                           f"pour le calcul du VG.")
            client_name = st.text_input("Client / Armateur", "MSC Maroc SARL")
            client_addr = st.text_input("Adresse client", "Casablanca, Maroc")
            bill_terminal = st.selectbox(
                "Terminal de facturation (droits navire & tarif rade)",
                ["Auto — 1er terminal accosté"] + terminals(),
                help="Détermine le taux des droits nautique/port et le tarif de "
                     "stationnement en rade. « Auto » = déduit du 1er accostage de "
                     "l'itinéraire. Pour une escale **au mouillage seul**, choisissez "
                     "explicitement le terminal ici.")
            st.caption("🗺️ Construisez l'itinéraire complet de l'escale ci-dessous "
                       "(mouillage → accostage → shifting → mouillage → départ…). "
                       "Chaque tronçon peut se trouver sur un terminal différent. Le droit "
                       "de stationnement applique la franchise de 24 h, puis la facturation "
                       "par **tranche indivisible de 24 h** (1/3 du taux si résiduel ≤ 8 h, "
                       "tranche pleine si > 8 h) au taux de chaque terminal, avec réduction "
                       "rade de 50 % au-delà de 4 jours de mouillage.")

        # ---- Prestations à générer
        with right:
            st.markdown("##### 2 · Services à facturer")
            svc = st.multiselect(
                "Services rendus",
                ["Droits de port navire", "Pilotage", "Remorquage", "Lamanage",
                 "Marchandise", "Fournitures / Services"],
                default=["Droits de port navire", "Pilotage", "Remorquage", "Lamanage"],
                help="Le pilotage, le remorquage et le lamanage sont facturés par "
                     "mouvement selon l'itinéraire (cases à cocher par tronçon).",
            )

            st.markdown("**Marchandise (optionnel)**")
            mtype = st.selectbox("Type de marchandise",
                                 ["Aucune", "Conteneurs (EVP)", "Marchandises diverses (T)",
                                  "Hydrocarbures (T)"])
            mqty = 0.0
            mcode = None
            if mtype != "Aucune":
                mqty = st.number_input("Quantité", min_value=0.0, value=500.0, step=10.0)
                if mtype == "Conteneurs (EVP)":
                    opt = [it for it in SS.catalog if it["category"] == "Marchandise — Conteneurs"]
                elif mtype == "Marchandises diverses (T)":
                    opt = [it for it in SS.catalog if it["category"] == "Marchandise — Diverses"]
                else:
                    opt = [it for it in SS.catalog if it["category"] == "Marchandise — Hydrocarbures"]
                if opt:
                    msel = st.selectbox("Article marchandise",
                                        [f"{it['code']} · {it['label']}" for it in opt])
                    mcode = msel.split(" · ")[0]

        # ---- Itinéraire de l'escale (pleine largeur) — majorations PAR MOUVEMENT
        st.markdown("##### 3 · Itinéraire de l'escale (mouvements)")
        st.caption("Une ligne par mouvement, dans l'ordre chronologique. `Emplacement` = "
                   "où se trouve le navire **à partir** de ce mouvement jusqu'au suivant. "
                   "Les majorations et suppléments de durée sont saisis **par mouvement** : "
                   "`Pil. h` / `Lam. h` = durée de la manœuvre (dépassement pilotage +50 %/h, "
                   "lamanage +30 %/h au-delà de 2 h) ; `Pil. maj%` = retard/désemparé "
                   "(+50 % / +100 %) ; `Rem. maj%` = sans propulsion (+25 %) ou déhalage (−75 %).")
        itin_df = st.data_editor(
            default_itinerary(), hide_index=True, use_container_width=True,
            num_rows="dynamic", key="itin_editor",
            column_config={
                "mouvement": st.column_config.SelectboxColumn(
                    "Mouvement", options=MOVEMENTS, width="medium", required=True),
                "emplacement": st.column_config.SelectboxColumn(
                    "Emplacement", options=list(td.BERTHS_NWM.keys()), width="medium",
                    required=True),
                "datetime": st.column_config.DatetimeColumn(
                    "Date & heure", format="DD/MM/YYYY HH:mm", step=60, width="medium"),
                "pilotage": st.column_config.CheckboxColumn("Pilotage"),
                "pil_h": st.column_config.NumberColumn("Pil. h", min_value=0.0,
                    max_value=48.0, step=0.5, help="Durée opération pilotage (+50 %/h > 2 h)"),
                "pil_maj": st.column_config.NumberColumn("Pil. maj%", min_value=0.0,
                    max_value=300.0, step=50.0, help="Retard confirmé +50 %, retard >20 min "
                    "ou désemparé +100 %"),
                "remorqueurs": st.column_config.NumberColumn("Remorq.", min_value=0,
                                                             max_value=4, step=1),
                "rem_maj": st.column_config.NumberColumn("Rem. maj%", min_value=-100.0,
                    max_value=100.0, step=25.0, help="Sans propulsion +25 %, déhalage −75 %"),
                "lamanage": st.column_config.CheckboxColumn("Lamanage"),
                "lam_h": st.column_config.NumberColumn("Lam. h", min_value=0.0,
                    max_value=48.0, step=0.5, help="Durée manœuvre lamanage (+30 %/h > 2 h)"),
            },
        )

        st.divider()
        if st.button("⚙️ Générer les prestations", type="primary", use_container_width=True):
            itin = itin_df.copy()
            itin = itin.dropna(subset=["datetime"])
            itin["datetime"] = pd.to_datetime(itin["datetime"])
            itin = itin.sort_values("datetime").reset_index(drop=True)

            if len(itin) < 2:
                st.error("L'itinéraire doit comporter au moins 2 mouvements "
                         "(arrivée et départ) avec une date/heure.")
                st.stop()

            dt_a = itin["datetime"].iloc[0].to_pydatetime()
            dt_d = itin["datetime"].iloc[-1].to_pydatetime()
            sejour_h = max((dt_d - dt_a).total_seconds() / 3600.0, 0.0)
            jours = max(1, -(-int(sejour_h) // 24))

            # Terminal de facturation (droits navire & tarif rade) :
            #   - explicite si l'utilisateur l'a choisi,
            #   - sinon déduit du 1er accostage de l'itinéraire.
            inferred_terminal = next(
                (td.BERTHS_NWM[e] for e in itin["emplacement"] if td.BERTHS_NWM.get(e)), None)
            if bill_terminal.startswith("Auto"):
                term_principal = inferred_terminal
            else:
                term_principal = bill_terminal
            if term_principal is None:
                # Escale au mouillage seul et aucun terminal choisi : on ne peut pas
                # deviner le taux des droits navire / rade.
                st.error("Escale **au mouillage seul** : aucun terminal accosté détecté. "
                         "Choisissez un **terminal de facturation** (section 1) pour "
                         "appliquer le taux des droits navire et du stationnement en rade.")
                st.stop()
            pref = term_principal.split()[-1][:3].upper()
            rade_taux = td.DROITS_PORT_NAVIRES_NWM[term_principal]["stationnement"]

            # lamanage_h reste à 2 h : le supplément de durée est appliqué par mouvement
            # (colonne `lam_h` de l'itinéraire) via la majoration de chaque ligne.
            ctx = billing.CallContext(gt=vessel["gt"], vg=vg, loa=vessel["loa"],
                                      sejour_h=sejour_h, jours=jours, lamanage_h=2.0)
            cat_by_code = {it["code"]: it for it in SS.catalog if it.get("active", True)}

            def find(code):
                return cat_by_code.get(code)

            lines = []

            # --- Droits de port navire : nautique + port (une fois, terminal principal)
            if "Droits de port navire" in svc:
                for pre in ("DN", "DP"):
                    it = find(f"{pre}-{pref}")
                    if it:
                        lines.append(billing.make_line(it, 1, ctx))

            # --- Droit de stationnement calculé sur l'itinéraire (par terminal / tronçon)
            legs = []
            for i in range(len(itin) - 1):
                r, nxt = itin.iloc[i], itin.iloc[i + 1]
                dur = (nxt["datetime"] - r["datetime"]).total_seconds() / 3600.0
                empl = r["emplacement"]
                tk = td.BERTHS_NWM.get(empl)
                legs.append({
                    "label": empl, "is_rade": tk is None,
                    "taux": (td.DROITS_PORT_NAVIRES_NWM[tk]["stationnement"] if tk else rade_taux),
                    "dur_h": max(dur, 0.0),
                })
            stat_amount, stat_detail = billing.calc_stationnement_legs(vg, legs)
            if "Droits de port navire" in svc and stat_amount > 0:
                lines.append({
                    "code": "DS", "designation": f"Droit de stationnement (itinéraire, "
                    f"{sejour_h:.0f} h / {len(legs)} tronçons)", "quantite": 1,
                    "unite": "escale", "pu": round(stat_amount, 2), "majoration": 0,
                    "montant_ht": round(stat_amount, 2), "tva": 0.0,
                })

            # --- Pilotage / Remorquage / Lamanage PAR MOUVEMENT (majorations propres à chaque mvt)
            def _num(x, default=0.0):
                try:
                    return float(x)
                except (TypeError, ValueError):
                    return default

            for _, r in itin.iterrows():
                mv = str(r["mouvement"])
                is_shift = ("shifting" in mv.lower()) or ("changement" in mv.lower())
                if "Pilotage" in svc and bool(r.get("pilotage")):
                    code = "PIL-CQ" if is_shift else "PIL-ES"
                    if find(code):
                        pil_h = _num(r.get("pil_h"), 2.0)
                        maj = _num(r.get("pil_maj"), 0.0)
                        if pil_h > 2:  # dépassement de durée +50 %/h entamée
                            maj += 50 * math.ceil(pil_h - 2)
                        l = billing.make_line(find(code), 1, ctx, maj)
                        l["designation"] = f"{l['designation']} — {mv} ({r['emplacement']})"
                        lines.append(l)
                ntug = int(_num(r.get("remorqueurs"), 0))
                if "Remorquage" in svc and ntug > 0 and find("REM"):
                    l = billing.make_line(find("REM"), ntug, ctx, _num(r.get("rem_maj"), 0.0))
                    l["designation"] = f"{l['designation']} — {mv}"
                    lines.append(l)
                if "Lamanage" in svc and bool(r.get("lamanage")) and find("LAM"):
                    lam_h = _num(r.get("lam_h"), 2.0)
                    lam_maj = 30 * math.ceil(lam_h - 2) if lam_h > 2 else 0.0
                    l = billing.make_line(find("LAM"), 1, ctx, lam_maj)
                    l["designation"] = f"{l['designation']} — {mv}"
                    lines.append(l)

            # --- Marchandise (une fois)
            if "Marchandise" in svc and mcode and mqty > 0 and find(mcode):
                lines.append(billing.make_line(find(mcode), mqty, ctx))

            itinerary_store = [{
                "mouvement": str(r["mouvement"]), "emplacement": str(r["emplacement"]),
                "datetime": r["datetime"].strftime("%d/%m/%Y %H:%M"),
                "pilotage": bool(r.get("pilotage")),
                "pil_h": _num(r.get("pil_h"), 2.0), "pil_maj": _num(r.get("pil_maj"), 0.0),
                "remorqueurs": int(_num(r.get("remorqueurs"), 0)),
                "rem_maj": _num(r.get("rem_maj"), 0.0),
                "lamanage": bool(r.get("lamanage")), "lam_h": _num(r.get("lam_h"), 2.0),
            } for _, r in itin.iterrows()]
            emplacements = list(dict.fromkeys(itin["emplacement"].tolist()))

            call = {
                "id": str(uuid.uuid4()),
                "ref": f"ESC-{datetime.now():%Y%m%d}-{len(SS.calls)+1:03d}",
                "vessel_id": vessel["id"], "terminal": term_principal,
                "berth": " → ".join(emplacements),
                "eta": dt_a.strftime("%d/%m/%Y %H:%M"), "etd": dt_d.strftime("%d/%m/%Y %H:%M"),
                "sejour_h": sejour_h, "jours": jours, "movements": [r["mouvement"] for r in itinerary_store],
                "itinerary": itinerary_store, "stationnement_detail": stat_detail,
                "vg": vg, "draught_declared": round(vessel["draft"], 2),
                "draught_min": round(0.14 * math.sqrt(vessel["loa"] * vessel["beam"]), 2),
                "draught_used": round(max(vessel["draft"],
                                          0.14 * math.sqrt(vessel["loa"] * vessel["beam"])), 2),
                "client_name": client_name, "client_address": client_addr,
                "lines": lines, "status": "Brouillon",
            }
            SS.calls.append(call)
            SS.active_call = call["id"]
            st.success(f"Escale **{call['ref']}** générée : {len(lines)} prestations sur "
                       f"{len(itinerary_store)} mouvements ({sejour_h:.0f} h).")
            st.rerun()

    # ---- Éditer une escale existante
    if SS.calls:
        st.divider()
        st.markdown("##### 4 · Détail & édition des prestations d'une escale")
        refs = [c["ref"] for c in SS.calls]
        default_idx = refs.index(SS.get("active_call_ref")) if SS.get("active_call_ref") in refs else len(refs) - 1
        sel_ref = st.selectbox("Escale", refs, index=default_idx)
        call = next(c for c in SS.calls if c["ref"] == sel_ref)
        SS.active_call_ref = sel_ref
        v = vessel_by_id(call["vessel_id"])

        _te_used = call.get("draught_used")
        _te_warn = _te_used is not None and _te_used > call.get("draught_declared", _te_used)
        st.markdown(
            f"<span class='pill'>{v['name'] if v else '—'}</span>"
            f"<span class='pill'>{call['terminal']}</span>"
            f"<span class='pill'>{call.get('berth','—')}</span>"
            + (f"<span class='pill'>VG {call.get('vg',0):,.0f} m³</span>" if call.get('vg') else "")
            + (f"<span class='pill{' warn' if _te_warn else ''}'>Tirant "
               f"{_te_used:.2f} m</span>" if _te_used is not None else "")
            + f"<span class='pill'>Arr. {call['eta']}</span>"
            f"<span class='pill'>Dép. {call['etd']}</span>"
            f"<span class='pill ok'>{call.get('status','Brouillon')}</span>",
            unsafe_allow_html=True,
        )
        if _te_warn:
            st.caption(f"⚓ Tirant retenu **{_te_used:.2f} m** (tirant déclaré "
                       f"{call['draught_declared']:.2f} m < minimum théorique "
                       f"0,14·√(L·B) = {call['draught_min']:.2f} m).")

        if call.get("itinerary"):
            with st.expander("🗺️ Itinéraire & détail du stationnement"):
                st.markdown("**Mouvements**")
                st.dataframe(pd.DataFrame(call["itinerary"]), hide_index=True,
                             use_container_width=True)
                if call.get("stationnement_detail"):
                    st.markdown("**Stationnement par tronçon**")
                    sd = pd.DataFrame(call["stationnement_detail"])
                    sd["montant"] = sd["montant"].map(lambda x: money(x))
                    st.dataframe(sd, hide_index=True, use_container_width=True)

        st.caption("Vous pouvez **ajouter des lignes** (bouton +), modifier les montants "
                   "ou en supprimer. Les modifications sont enregistrées ci-dessous.")
        lines_df = pd.DataFrame(call["lines"]) if call["lines"] else pd.DataFrame(
            columns=["code", "designation", "quantite", "unite", "pu", "majoration",
                     "montant_ht", "tva"])
        edited_lines = st.data_editor(
            lines_df, hide_index=True, use_container_width=True, num_rows="dynamic",
            key=f"lines_{call['id']}",
            column_config={
                "code": st.column_config.TextColumn("Code", width="small"),
                "designation": st.column_config.TextColumn("Désignation", width="large"),
                "quantite": st.column_config.NumberColumn("Qté", format="%.2f"),
                "unite": st.column_config.TextColumn("Unité", width="small"),
                "pu": st.column_config.NumberColumn("P.U.", format="%.4f"),
                "majoration": st.column_config.NumberColumn("Maj %", format="%.0f"),
                "montant_ht": st.column_config.NumberColumn("Montant", format="%.2f"),
                "tva": None,
            },
        )

        tot = billing.invoice_totals(edited_lines.to_dict("records"))
        m1, m2 = st.columns(2)
        m1.metric("Total escale", money(tot["total_ht"]))
        m2.metric("Nombre de lignes", len(edited_lines))
        st.caption("💡 Zone Franche — montants exonérés de TVA.")

        b1, b2, b3 = st.columns([1, 1, 2])
        if b1.button("💾 Enregistrer l'escale", type="primary"):
            call["lines"] = edited_lines.fillna(0).to_dict("records")
            st.success("Prestations enregistrées.")
            st.rerun()
        if b2.button("🗑️ Supprimer l'escale"):
            SS.calls = [c for c in SS.calls if c["id"] != call["id"]]
            st.rerun()
        # Ajout rapide d'un article du catalogue
        with b3:
            add_codes = [f"{it['code']} · {it['label']}" for it in SS.catalog
                         if it.get("active", True)]
            pick = st.selectbox("Ajouter un article du catalogue", ["—"] + add_codes,
                                key=f"pick_{call['id']}")
            if pick != "—" and st.button("➕ Ajouter à l'escale", key=f"addline_{call['id']}"):
                code = pick.split(" · ")[0]
                it = next(x for x in SS.catalog if x["code"] == code)
                ctx = billing.CallContext(gt=v["gt"], vg=vessel_vg(v), loa=v["loa"],
                                          sejour_h=call["sejour_h"], jours=call["jours"])
                call["lines"] = edited_lines.fillna(0).to_dict("records")
                call["lines"].append(billing.make_line(it, 1, ctx))
                st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
#  TAB : FACTURES
# ═══════════════════════════════════════════════════════════════════════════════
with tab_invoice:
    st.subheader("🧾 Génération de factures")

    if not SS.calls:
        st.info("Créez d'abord une escale dans l'onglet **🛳️ Escales**.")
    else:
        sel = st.selectbox("Escale à facturer", [c["ref"] for c in SS.calls])
        call = next(c for c in SS.calls if c["ref"] == sel)
        v = vessel_by_id(call["vessel_id"])

        c1, c2, c3 = st.columns(3)
        inv_date = c1.date_input("Date de facture", value=date.today())
        due_days = c2.number_input("Échéance (jours)", 0, 120, 30)
        prefix = c3.text_input("Préfixe n° facture", "NWM")

        if st.button("🧾 Générer la facture", type="primary"):
            number = billing.next_invoice_number(SS.inv_seq, prefix)
            SS.inv_seq += 1
            inv = {
                "number": number,
                "date": inv_date.strftime("%d/%m/%Y"),
                "due": (inv_date + timedelta(days=int(due_days))).strftime("%d/%m/%Y"),
                "client_name": call["client_name"], "client_address": call["client_address"],
                "vessel": {**v, "vg": vessel_vg(v),
                           "draught_used": call.get("draught_used"),
                           "draught_declared": call.get("draught_declared"),
                           "draught_min": call.get("draught_min")} if v else {},
                "call": call, "lines": call["lines"],
            }
            call["status"] = "Facturée"
            SS.invoices.append(inv)
            SS.active_invoice = number
            st.success(f"Facture **{number}** générée.")

        # Affichage de la facture active ou de la dernière pour cette escale
        inv_for_call = [i for i in SS.invoices if i["call"]["ref"] == call["ref"]]
        if inv_for_call:
            inv = inv_for_call[-1]
            tot = billing.invoice_totals(inv["lines"])

            st.divider()
            st.markdown(f"### Facture {inv['number']}")
            hc1, hc2 = st.columns(2)
            hc1.metric("Total à payer", money(tot["total_ht"]))
            hc2.metric("Nombre de lignes", len(inv["lines"]))
            st.caption("Exonéré de TVA — Zone Franche.")
            if SS.currency == "EUR" and SS.fx_mad:
                st.caption(f"Contre-valeur : **{tot['total_ht']*SS.fx_mad:,.2f} MAD** "
                           f"(taux {SS.fx_mad:.2f})")

            html = billing.render_invoice_html(
                inv, SS.company, currency=SS.currency,
                fx_mad=SS.fx_mad if SS.currency == "EUR" else None,
            )

            with st.expander("👁️ Aperçu de la facture", expanded=True):
                st.components.v1.html(html, height=780, scrolling=True)

            dl1, dl2 = st.columns(2)
            dl1.download_button(
                "⬇️ Télécharger la facture (HTML imprimable → PDF)",
                html.encode("utf-8"),
                file_name=f"facture_{inv['number']}.html", mime="text/html",
                use_container_width=True,
            )
            csv_buf = io.StringIO()
            pd.DataFrame(inv["lines"]).to_csv(csv_buf, index=False)
            dl2.download_button(
                "⬇️ Exporter les lignes (CSV)",
                csv_buf.getvalue().encode("utf-8"),
                file_name=f"facture_{inv['number']}.csv", mime="text/csv",
                use_container_width=True,
            )
            st.caption("💡 Ouvrez le fichier HTML puis **Ctrl/Cmd + P → Enregistrer en PDF** "
                       "pour obtenir une facture PDF professionnelle.")

    # Historique des factures
    if SS.invoices:
        st.divider()
        st.markdown("##### Historique des factures")
        hist = []
        for i in SS.invoices:
            t = billing.invoice_totals(i["lines"])
            hist.append({
                "N° Facture": i["number"], "Date": i["date"], "Client": i["client_name"],
                "Navire": i["vessel"].get("name", "—"), "Escale": i["call"]["ref"],
                "Total": money(t["total_ht"]),
            })
        st.dataframe(pd.DataFrame(hist), hide_index=True, use_container_width=True)


# ═══════════════════════════════════════════════════════════════════════════════
#  PERSISTANCE — enregistre l'état courant à chaque exécution (fin de script)
# ═══════════════════════════════════════════════════════════════════════════════
persist()
