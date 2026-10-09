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
import json
import math
import os
import uuid
from datetime import date, datetime, timedelta

import pandas as pd
import streamlit as st

import billing
import storage
import tarifs_data as td
import tugs

# ═══════════════════════════════════════════════════════════════════════════════
#  CONFIGURATION & THÈME
# ═══════════════════════════════════════════════════════════════════════════════
st.set_page_config(
    page_title="Escales & Facturation — NWM",
    page_icon="⚓",
    layout="wide",
    initial_sidebar_state="expanded",
)

LOGO_PATH = os.path.join(os.path.dirname(__file__), "assets", "nwm_logo.png")
if os.path.exists(LOGO_PATH):
    try:
        st.logo(LOGO_PATH, size="large")
    except Exception:
        pass

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
    "name": "Nador West Med Port Authority",
    "legal": "Société Anonyme — Capital social : 5 491 000 000 DH",
    "rc": "Nador 9387", "if": "40146682", "ice": "001597527000052",
    "address": "Zone Franche Betoya, 62000 Nador — Maroc",
    "tel": "", "web": "",
    "bank": "ATTIJARIWAFA BANK — Centre d'affaire Tanger Souriyenne",
    "rib": "007640000090500001426720", "swift": "",
    "multicanal": "Fatourati NWM", "conditions": "30J",
    "footer": "Les frais et commissions sont à la charge du client.",
    "show_mad": False,  # contre-valeur MAD sur les factures (optionnelle)
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
        ss.pmis_edits = persisted.get("pmis_edits", {})
        ss.tugs = persisted.get("tugs", [])
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
    if "pmis_edits" not in ss:
        ss.pmis_edits = {}
    if "tugs" not in ss:
        ss.tugs = []


init_state()
SS = st.session_state


def persist():
    """Enregistre l'état applicatif courant dans la base SQLite."""
    storage.save_state({k: SS[k] for k in storage.KEYS if k in SS})


# --- Sauvegarde / restauration (logique locale à app.py : le script d'entrée est
#     toujours ré-exécuté à neuf, ce qui évite tout souci de module importé « périmé »
#     après un redéploiement sur Streamlit Cloud).
BACKUP_VERSION = 1


def export_backup_json() -> str:
    """Sérialise l'état applicatif courant en JSON de sauvegarde."""
    payload = {
        "_backup": "nwm-portcall", "_version": BACKUP_VERSION,
        "_exported_at": datetime.now().isoformat(timespec="seconds"),
        "data": {k: SS[k] for k in storage.KEYS if k in SS},
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)


def parse_backup(raw) -> dict:
    """Valide un fichier de sauvegarde et renvoie les données reconnues.

    Accepte le format enveloppé {_backup, data:{…}} ou un dict à plat.
    Lève ValueError si le contenu est invalide.
    """
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8")
    try:
        obj = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError as e:
        raise ValueError(f"Fichier JSON invalide : {e}") from e
    if not isinstance(obj, dict):
        raise ValueError("Le fichier de sauvegarde doit être un objet JSON.")
    data = obj.get("data", obj)
    if not isinstance(data, dict):
        raise ValueError("Section « data » invalide dans la sauvegarde.")
    extracted = {k: data[k] for k in storage.KEYS if k in data}
    if not extracted:
        raise ValueError("Aucune donnée reconnue (navires, catalogue, escales…) "
                         "dans le fichier.")
    return extracted


# ═══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════════════════
def vessel_by_id(vid):
    return next((v for v in SS.vessels if v["id"] == vid), None)


def vessel_vg(v):
    return td.calc_vg(v["loa"], v["beam"], v["draft"]) if v else 0.0


def draught_info(v):
    """Renvoie (tirant_déclaré, tirant_min_théorique, tirant_retenu, min_appliqué).
    Toutes les valeurs sont arrondies à 2 décimales (cohérent avec calc_vg)."""
    if not v:
        return 0.0, 0.0, 0.0, False
    te_decl = round(v["draft"], 2)
    te_min = round(0.14 * math.sqrt(v["loa"] * v["beam"]), 2)
    te_ret = max(te_decl, te_min)
    return te_decl, te_min, te_ret, te_min > te_decl


def money(v, cur=None):
    cur = cur or SS.currency
    try:
        return f"{float(v):,.2f} {cur}"
    except Exception:
        return f"— {cur}"


def invoice_fx():
    """Taux EUR → MAD à imprimer sur la facture, ou None si la contre-valeur MAD est
    désactivée (option de la barre latérale) ou si la facture n'est pas en EUR."""
    if SS.currency == "EUR" and SS.company.get("show_mad") and SS.fx_mad:
        return SS.fx_mad
    return None


def terminals():
    return list(td.DROITS_PORT_NAVIRES_NWM.keys())


# Escale au mouillage seul → facturée au Terminal Marchandises Diverses (TMD).
ANCHORAGE_TERMINAL = "Terminal Marchandises Div"


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
_hc1, _hc2 = st.columns([1, 6])
with _hc1:
    if os.path.exists(LOGO_PATH):
        st.image(LOGO_PATH, use_container_width=True)
with _hc2:
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
    with st.expander("Mentions légales & banque"):
        SS.company["legal"] = st.text_input("Forme / capital", SS.company.get("legal", ""))
        SS.company["rc"] = st.text_input("R.C", SS.company.get("rc", ""))
        SS.company["bank"] = st.text_input("Banque", SS.company.get("bank", ""))
        SS.company["rib"] = st.text_input("RIB", SS.company.get("rib", ""))
        SS.company["swift"] = st.text_input("SWIFT", SS.company.get("swift", ""))
        SS.company["multicanal"] = st.text_input("Paiement multicanal",
                                                 SS.company.get("multicanal", ""))
        SS.company["conditions"] = st.text_input("Conditions de règlement",
                                                 SS.company.get("conditions", "30J"))

    st.divider()
    st.header("💱 Devise")
    SS.currency = st.selectbox("Devise de facturation", ["EUR", "MAD", "USD"], index=0)
    SS.company["show_mad"] = st.checkbox(
        "Afficher la contre-valeur en MAD sur les factures",
        value=bool(SS.company.get("show_mad", False)),
        help="Optionnel : ajoute sous le total la contre-valeur en dirhams (taux ci-dessous).")
    if SS.company["show_mad"]:
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

    # --- Sauvegarde / Restauration (protège du disque éphémère sur Streamlit Cloud)
    st.download_button(
        "⬇️ Exporter la sauvegarde (JSON)",
        export_backup_json().encode("utf-8"),
        file_name=f"sauvegarde_nwm_{datetime.now():%Y%m%d_%H%M}.json",
        mime="application/json", use_container_width=True,
        help="Télécharge tout l'état (navires, catalogue, escales, factures). "
             "À conserver pour restaurer après un redémarrage du serveur.")

    up = st.file_uploader("⬆️ Restaurer depuis une sauvegarde", type=["json"],
                          key="restore_uploader")
    if up is not None:
        try:
            restored = parse_backup(up.getvalue())
            if st.button("♻️ Restaurer ces données", type="primary",
                         use_container_width=True):
                for k in storage.KEYS:
                    if k == "company":
                        SS.company = {**_DEFAULT_COMPANY, **(restored.get("company") or {})}
                    elif k in restored:
                        SS[k] = restored[k]
                persist()
                for k in ["active_call_ref", "active_call", "active_invoice"]:
                    SS.pop(k, None)
                st.success(f"Sauvegarde restaurée : {len(restored.get('vessels', []))} "
                           f"navires, {len(restored.get('calls', []))} escales, "
                           f"{len(restored.get('invoices', []))} factures.")
                st.rerun()
            else:
                st.caption(f"✓ Fichier valide — {len(restored.get('vessels', []))} navires, "
                           f"{len(restored.get('calls', []))} escales prêts à restaurer.")
        except ValueError as e:
            st.error(f"Sauvegarde invalide : {e}")

    if st.button("↺ Réinitialiser les données", use_container_width=True):
        storage.clear_state()
        for k in ["vessels", "catalog", "calls", "invoices", "inv_seq", "company",
                  "_loaded", "active_call_ref", "active_call", "active_invoice"]:
            SS.pop(k, None)
        init_state()
        st.success("Données réinitialisées.")
        st.rerun()


tab_dash, tab_vessels, tab_catalog, tab_calls, tab_invoice, tab_tugs, tab_pmis = st.tabs(
    ["📈 Tableau de bord", "🚢 Navires", "📖 Catalogue tarifaire",
     "🛳️ Escales", "🧾 Factures", "🚤 Remorquage", "🔌 PMIS"]
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
                "VG (m³)": f"{vessel_vg(v):,.2f}",
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
                f"<span class='pill'>VG {vg:,.2f} m³</span>"
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
                     "l'itinéraire ; une escale **au mouillage seul** est facturée au "
                     "Terminal Marchandises Diverses (TMD).")
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
                # Escale au mouillage seul : facturée au Terminal Marchandises Diverses.
                term_principal = ANCHORAGE_TERMINAL
                st.info("Escale **au mouillage seul** : facturée au **Terminal "
                        "Marchandises Diverses (TMD)**. Choisissez un autre terminal de "
                        "facturation (section 1) si nécessaire.")
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
                "draught_used": round(max(round(vessel["draft"], 2),
                                          round(0.14 * math.sqrt(vessel["loa"] * vessel["beam"]), 2)), 2),
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
            + (f"<span class='pill'>VG {call.get('vg',0):,.2f} m³</span>" if call.get('vg') else "")
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
        d1, d2, d3 = st.columns(3)
        client_code = d1.text_input("Code client", "")
        po_ref = d2.text_input("Référence PO / commande", "")
        contract = d3.text_input("N° de contrat", "")
        e1, e2, e3 = st.columns(3)
        client_ice = e1.text_input("ICE client", "")
        client_city = e2.text_input("Ville client", "Casablanca")
        client_country = e3.text_input("Pays client", "Maroc")

        if st.button("🧾 Générer la facture", type="primary"):
            number = billing.next_invoice_number(SS.inv_seq, prefix)
            SS.inv_seq += 1
            inv = {
                "number": number,
                "date": inv_date.strftime("%d/%m/%Y"),
                "due": (inv_date + timedelta(days=int(due_days))).strftime("%d/%m/%Y"),
                "client_name": call["client_name"], "client_address": call["client_address"],
                "client_code": client_code, "client_ice": client_ice,
                "client_city": client_city, "client_country": client_country,
                "po": po_ref, "contract": contract,
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
            if invoice_fx():
                st.caption(f"Contre-valeur : **{tot['total_ht']*SS.fx_mad:,.2f} MAD** "
                           f"(taux {SS.fx_mad:.2f})")

            html = billing.render_invoice_html(
                inv, SS.company, currency=SS.currency,
                fx_mad=invoice_fx(),
            )

            with st.expander("👁️ Aperçu de la facture", expanded=True):
                st.components.v1.html(html, height=780, scrolling=True)

            try:
                pdf_bytes = billing.render_invoice_pdf(
                    inv, SS.company, currency=SS.currency,
                    fx_mad=invoice_fx(),
                )
            except Exception as e:  # reportlab manquant, etc.
                pdf_bytes = None
                st.warning(f"Génération PDF indisponible ({e}). Installez « reportlab ».")

            dl1, dl2 = st.columns(2)
            if pdf_bytes:
                dl1.download_button(
                    "⬇️ Télécharger la facture (PDF)",
                    pdf_bytes,
                    file_name=f"Facture_{inv['number']}.pdf", mime="application/pdf",
                    use_container_width=True,
                )
            else:
                dl1.download_button(
                    "⬇️ Télécharger la facture (HTML)",
                    html.encode("utf-8"),
                    file_name=f"Facture_{inv['number']}.html", mime="text/html",
                    use_container_width=True,
                )
            csv_buf = io.StringIO()
            pd.DataFrame(inv["lines"]).to_csv(csv_buf, index=False)
            dl2.download_button(
                "⬇️ Exporter les lignes (CSV)",
                csv_buf.getvalue().encode("utf-8"),
                file_name=f"Facture_{inv['number']}.csv", mime="text/csv",
                use_container_width=True,
            )
            st.caption("📄 La facture est générée en **PDF A4 portrait** prêt à l'impression.")

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
#  TAB : REMORQUAGE — suivi des remorqueurs par escale
# ═══════════════════════════════════════════════════════════════════════════════
def _tug_call_sources() -> dict:
    """Escales connues (escales de l'app, visites PMIS chargées, escales déjà saisies)
    → valeurs de pré-remplissage du formulaire."""
    src = {}
    for c in SS.calls:
        v = vessel_by_id(c.get("vessel_id")) or {}
        src[f"{c['ref']} · {v.get('name', '—')}"] = {
            "escale": c["ref"], "navire": v.get("name", ""), "imo": v.get("imo", ""),
            "gt": float(v.get("gt") or 0), "visit_id": None}
    for vis in SS.get("pmis_rows", []):
        ship = vis.get("ship") or {}
        ref = str(vis.get("business_id") or vis.get("visit_id"))
        src[f"{ref} · {(ship.get('target_name') or '').strip()} (PMIS)"] = {
            "escale": ref, "navire": (ship.get("target_name") or "").strip(),
            "imo": ship.get("imo_number") or "", "gt": float(ship.get("gross_tonnage") or 0),
            "visit_id": vis.get("visit_id")}
    for r in SS.tugs:
        key = f"{r.get('escale')} · {r.get('navire')}"
        if r.get("escale") and not any(k.startswith(f"{r.get('escale')} ·") for k in src):
            src[key] = {"escale": r.get("escale"), "navire": r.get("navire") or "",
                        "imo": r.get("imo") or "", "gt": float(r.get("gt") or 0),
                        "visit_id": r.get("visit_id")}
    return src


with tab_tugs:
    st.subheader("🚤 Remorquage — usages & tarification par escale")
    annul_pct = float(SS.company.get("tug_annul_pct", 100.0))
    st.caption("Un enregistrement = **un remorqueur sur un mouvement** d'une escale. "
               "Tarif NWM par remorqueur et par mouvement selon le **GT** du navire "
               "(barème + 150 € / 5 000 GT au-delà de 50 000 GT) ; déhalage = 25 % du "
               "tarif ; sans propulsion = +25 % ; annulation = "
               f"+{annul_pct:.0f} % ; majoration libre en %. Le remorquage n'est pas "
               "porté sur la facture d'escale NWM : ce module en assure le suivi.")

    with st.expander("⚙️ Règles de tarification"):
        SS.company["tug_annul_pct"] = st.number_input(
            "Majoration d'un remorqueur en annulation (%)", 0.0, 500.0, annul_pct, 5.0,
            key="tug_annul_pct_in")
        annul_pct = float(SS.company["tug_annul_pct"])
        bar = pd.DataFrame([{"GT de": lo, "GT à": hi, "Tarif (€)": t}
                            for lo, hi, t in td.REMORQUAGE_NWM])
        st.dataframe(bar, hide_index=True, use_container_width=True)
        st.caption(f"Au-delà de 50 000 GT : + {td.REMORQUAGE_NWM_SUP:.0f} € par tranche "
                   "de 5 000 GT.")
    SS.tugs = [tugs.price(r, annul_pct) for r in SS.tugs]

    # ---- 1 · Import PMIS
    ic1, ic2 = st.columns(2)
    with ic1.expander("🔌 Importer depuis PMIS (réservations TOWG)", expanded=not SS.tugs):
        prow = SS.get("pmis_rows", [])
        if not prow:
            st.info("Interrogez d'abord PMIS dans l'onglet **🔌 PMIS** : les remorqueurs "
                    "des visites chargées pourront ensuite être importés ici.")
        else:
            st.write(f"{len(prow)} visite(s) chargée(s) depuis PMIS.")
            if st.button("⬇️ Importer les remorqueurs", type="primary", key="tug_import"):
                incoming = [tugs.price(r, annul_pct) for v in prow
                            for r in tugs.records_from_visit(v)]
                SS.tugs, n_add, n_skip = tugs.merge_records(SS.tugs, incoming)
                SS.tug_ver = SS.get("tug_ver", 0) + 1
                st.success(f"{n_add} usage(s) importé(s)"
                           + (f", {n_skip} déjà présent(s)" if n_skip else "") + ".")

    # ---- 2 · Saisie manuelle
    with ic2.expander("➕ Enregistrer un remorqueur", expanded=False):
        sources = _tug_call_sources()
        pick = st.selectbox("Escale", ["— Saisie libre —"] + list(sources), key="tug_src")
        pre = sources.get(pick, {"escale": "", "navire": "", "imo": "", "gt": 0.0,
                                 "visit_id": None})
        known = sorted({r.get("remorqueur") for r in SS.tugs if r.get("remorqueur")})
        with st.form("tug_add", clear_on_submit=False):
            f1, f2, f3 = st.columns(3)
            esc = f1.text_input("Escale", pre["escale"], key=f"tug_esc_{pick}")
            nav = f2.text_input("Navire", pre["navire"], key=f"tug_nav_{pick}")
            gt_ = f3.number_input("GT", 0.0, None, float(pre["gt"]), 100.0,
                                  key=f"tug_gt_{pick}")
            f4, f5, f6 = st.columns(3)
            mv = f4.selectbox("Mouvement", tugs.MOVEMENTS)
            de_ = f5.text_input("De (poste)")
            vers_ = f6.text_input("Vers (poste)")
            f7, f8, f9 = st.columns(3)
            tug_pick = f7.selectbox("Remorqueur", known + ["➕ Nouveau…"])
            tug_new = f8.text_input("Nouveau remorqueur (si « Nouveau… »)")
            prest = f9.text_input("Prestataire", "Towing Service Provider")
            g1, g2, g3, g4 = st.columns(4)
            d_start = g1.date_input("Début — date", value=date.today())
            t_start = g2.time_input("Début — heure", value=datetime.now().time().replace(
                second=0, microsecond=0), step=300)
            d_end = g3.date_input("Fin — date", value=date.today())
            t_end = g4.time_input("Fin — heure", value=(datetime.now() + timedelta(hours=1))
                                  .time().replace(second=0, microsecond=0), step=300)
            h1, h2, h3, h4 = st.columns(4)
            ann = h1.checkbox("Annulation")
            sp = h2.checkbox("Sans propulsion (+25 %)")
            deh = h3.checkbox("Déhalage (25 %)")
            maj = h4.number_input("Majoration libre (%)", -100.0, 500.0, 0.0, 5.0)
            notes = st.text_input("Notes")
            if st.form_submit_button("💾 Enregistrer", type="primary"):
                name = (tug_new.strip() if tug_pick.startswith("➕") else tug_pick)
                if not name:
                    st.error("Indiquez le nom du remorqueur.")
                else:
                    rec = tugs.new_record(
                        debut=datetime.combine(d_start, t_start).isoformat(timespec="seconds"),
                        fin=datetime.combine(d_end, t_end).isoformat(timespec="seconds"),
                        escale=esc.strip(), visit_id=pre.get("visit_id"), navire=nav.strip(),
                        imo=pre.get("imo") or "", gt=gt_, mouvement=mv, de=de_, vers=vers_,
                        remorqueur=name, prestataire=prest, activite="Annulation" if ann
                        else "Normal", annulation=ann, sans_propulsion=sp, dehalage=deh,
                        majoration=maj, notes=notes)
                    SS.tugs.append(tugs.price(rec, annul_pct))
                    SS.tug_ver = SS.get("tug_ver", 0) + 1
                    st.success(f"{name} enregistré sur l'escale {esc or '—'} "
                               f"({money(SS.tugs[-1]['montant'])}).")

    if not SS.tugs:
        st.info("Aucun usage de remorqueur enregistré pour l'instant.")
    else:
        df_all = tugs.to_df(SS.tugs)

        # ---- 3 · Filtres, recherche, tri
        st.markdown("##### 🔎 Registre des remorqueurs")
        r1, r2, r3 = st.columns([2, 1, 1])
        q = r1.text_input("Rechercher (navire, escale, remorqueur, poste, notes…)",
                          key="tug_q")
        dmin = df_all["debut"].min()
        dmax = df_all["debut"].max()
        dmin = dmin.date() if pd.notna(dmin) else date.today()
        dmax = dmax.date() if pd.notna(dmax) else date.today()
        period = r2.date_input("Période (début)", value=(dmin, dmax), key="tug_period")
        sort_cols = {"Début": "debut", "Montant": "montant", "Remorqueur": "remorqueur",
                     "Escale": "escale", "Navire": "navire", "Durée": "duree_h", "GT": "gt"}
        sc1, sc2 = r3.columns(2)
        sort_by = sc1.selectbox("Trier par", list(sort_cols), key="tug_sort")
        desc = sc2.selectbox("Ordre", ["↓", "↑"], key="tug_order") == "↓"
        s1, s2, s3, s4, s5 = st.columns([2, 2, 2, 1, 1])
        f_tugs = s1.multiselect("Remorqueurs", sorted(df_all["remorqueur"].unique()),
                                key="tug_f_tug")
        f_calls = s2.multiselect("Escales", sorted(df_all["escale"].unique()),
                                 key="tug_f_call")
        f_mv = s3.multiselect("Mouvements", sorted(df_all["mouvement"].unique()),
                              key="tug_f_mv")
        f_src = s4.multiselect("Source", sorted(df_all["source"].unique()), key="tug_f_src")
        f_ann = s5.checkbox("Annulations seules", key="tug_f_ann")
        d_from, d_to = (period if isinstance(period, (list, tuple)) and len(period) == 2
                        else (None, None))
        view = tugs.filter_df(df_all, q, d_from, d_to, f_tugs, f_calls, f_mv, f_src, f_ann)
        view = view.sort_values(sort_cols[sort_by], ascending=not desc, na_position="last")

        k1, k2, k3, k4, k5 = st.columns(5)
        k1.metric("Opérations", len(view))
        k2.metric("Remorqueurs", view["remorqueur"].nunique())
        k3.metric("Escales", view["escale"].nunique())
        k4.metric("Heures", f"{view['duree_h'].sum():,.1f}")
        k5.metric("Montant", money(view["montant"].sum()))

        st.caption("Modifiez les cellules, ajoutez (+) ou supprimez des lignes puis "
                   "**enregistrez**. Durée, tarif et montant sont recalculés. Cliquez sur un "
                   "en-tête de colonne pour trier.")
        ed_key = f"tug_editor_{SS.get('tug_ver', 0)}_{hash(tuple(view['id']))}"
        edited = st.data_editor(
            view, key=ed_key, num_rows="dynamic", hide_index=True, use_container_width=True,
            column_order=[c for c in tugs.COLUMNS if c not in ("id", "visit_id", "imo")],
            disabled=["duree_h", "tarif_base", "majoration_totale", "montant", "source"],
            column_config={
                "debut": st.column_config.DatetimeColumn("Début", format="DD/MM/YYYY HH:mm"),
                "fin": st.column_config.DatetimeColumn("Fin", format="DD/MM/YYYY HH:mm"),
                "duree_h": st.column_config.NumberColumn("Durée (h)", format="%.2f"),
                "escale": st.column_config.TextColumn("Escale"),
                "navire": st.column_config.TextColumn("Navire"),
                "gt": st.column_config.NumberColumn("GT", format="%.0f"),
                "mouvement": st.column_config.SelectboxColumn("Mouvement",
                                                              options=tugs.MOVEMENTS),
                "de": st.column_config.TextColumn("De"),
                "vers": st.column_config.TextColumn("Vers"),
                "remorqueur": st.column_config.TextColumn("Remorqueur"),
                "bollard_pull": st.column_config.NumberColumn("Traction (t)", format="%.0f"),
                "prestataire": st.column_config.TextColumn("Prestataire"),
                "activite": st.column_config.TextColumn("Activité"),
                "annulation": st.column_config.CheckboxColumn("Annulation"),
                "sans_propulsion": st.column_config.CheckboxColumn("Sans propulsion"),
                "dehalage": st.column_config.CheckboxColumn("Déhalage"),
                "majoration": st.column_config.NumberColumn("Maj. libre %", format="%.0f"),
                "tarif_base": st.column_config.NumberColumn("Tarif base", format="%.2f"),
                "majoration_totale": st.column_config.NumberColumn("Maj. totale %",
                                                                   format="%.0f"),
                "montant": st.column_config.NumberColumn("Montant", format="%.2f"),
                "source": st.column_config.TextColumn("Source"),
                "notes": st.column_config.TextColumn("Notes", width="medium"),
            })

        b1, b2, b3 = st.columns(3)
        if b1.button("💾 Enregistrer les modifications", type="primary", key="tug_save"):
            shown = set(view["id"])
            kept = [r for r in SS.tugs if r.get("id") not in shown]
            changed = []
            for r in tugs.from_df(edited):
                r["source"] = r.get("source") or "Manuel"
                r["annulation"] = bool(r.get("annulation"))
                r["sans_propulsion"] = bool(r.get("sans_propulsion"))
                r["dehalage"] = bool(r.get("dehalage"))
                changed.append(tugs.price(r, annul_pct))
            SS.tugs = kept + changed
            SS.tug_ver = SS.get("tug_ver", 0) + 1
            st.success(f"{len(changed)} ligne(s) enregistrée(s).")
            st.rerun()
        b2.download_button("⬇️ Exporter le tableau filtré (CSV)",
                           tugs.export_df(view).to_csv(index=False, sep=";").encode("utf-8-sig"),
                           file_name=f"remorquage_{date.today():%Y%m%d}.csv", mime="text/csv",
                           use_container_width=True)
        try:
            b3.download_button("⬇️ Exporter + situation (Excel)", tugs.to_excel(view),
                               file_name=f"remorquage_{date.today():%Y%m%d}.xlsx",
                               mime="application/vnd.openxmlformats-officedocument."
                                    "spreadsheetml.sheet", use_container_width=True)
        except Exception as e:  # openpyxl manquant
            b3.warning(f"Export Excel indisponible ({e})")

        # ---- 4 · Situation
        st.markdown("##### 📊 Situation des remorqueurs")
        st.caption("Calculée sur le tableau filtré ci-dessus.")
        monthly = view.assign(mois=view["debut"].dt.strftime("%Y-%m").fillna("—"))
        st_t, st_c, st_m, st_p = st.tabs(["Par remorqueur", "Par escale", "Par mois",
                                          "Par prestataire"])
        for tab_, frame, by in ((st_t, view, "remorqueur"), (st_c, view, "escale"),
                                (st_m, monthly, "mois"), (st_p, view, "prestataire")):
            with tab_:
                sit = tugs.situation(frame, by)
                if sit.empty:
                    st.info("Aucune donnée.")
                    continue
                cc1, cc2 = st.columns([3, 2])
                cc1.dataframe(sit, hide_index=True, use_container_width=True,
                              column_config={"Montant": st.column_config.NumberColumn(
                                  "Montant", format="%.2f")})
                cc2.bar_chart(sit.set_index(by)[["Montant"]], height=260)


# ═══════════════════════════════════════════════════════════════════════════════
#  TAB : PMIS — récupération des visites & factures dynamiques
# ═══════════════════════════════════════════════════════════════════════════════
def _ts(v):
    """ISO → Timestamp (NaT si vide) pour les éditeurs de dates."""
    return pd.to_datetime(v, errors="coerce") if v else pd.NaT


def _iso_or_empty(v) -> str:
    try:
        return "" if pd.isna(v) else pd.Timestamp(v).strftime("%Y-%m-%dT%H:%M:%S")
    except Exception:
        return ""


def _records(df: pd.DataFrame) -> list[dict]:
    return df.astype(object).where(pd.notna(df), None).to_dict("records")


def pmis_invoice_editor(_pmis, visit: dict):
    """Paramètres éditables d'une visite PMIS + articles ajoutés → facture recalculée.

    Les éditeurs sont initialisés une fois par session (instantané stable) ; leurs
    valeurs courantes sont enregistrées dans SS.pmis_edits[visit_id] (SQLite)."""
    vid = str(visit.get("visit_id"))
    base = _pmis.visit_params(visit)
    ver = SS.setdefault("pmis_ver", {}).get(vid, 0)
    snap_key = f"pmis_snap_{vid}_{ver}"
    if snap_key not in SS:
        saved = SS.pmis_edits.get(vid) or {}
        SS[snap_key] = {"params": saved.get("params") or base,
                        "extras": saved.get("extras") or []}
    snap = SS[snap_key]
    p0 = snap["params"]
    k = f"pmis_{vid}_{ver}_"
    cat_opts = [f"{it['code']} · {it['label']}" for it in SS.catalog if it.get("active", True)]

    st.markdown("##### 4 · Paramètres de l'escale")
    st.caption("Toute modification recalcule immédiatement la facture. Les modifications "
               "sont conservées pour cette visite.")

    # --- Navire & tirant
    n1, n2, n3, n4 = st.columns(4)
    loa = n1.number_input("LOA (m)", 0.0, 500.0, float(p0["loa"]), 0.1, key=k + "loa")
    beam = n2.number_input("Largeur (m)", 0.0, 80.0, float(p0["beam"]), 0.1, key=k + "beam")
    gt = n3.number_input("GT", 0.0, 400000.0, float(p0["gt"]), 100.0, key=k + "gt")
    draft = n4.number_input("Tirant d'eau déclaré TE (m)", 0.0, 30.0, float(p0["draft"]),
                            0.1, key=k + "draft")

    # --- Client & terminal
    c1, c2, c3 = st.columns(3)
    client_name = c1.text_input("Client / Armateur", p0.get("client_name", ""), key=k + "cli")
    client_ice = c2.text_input("ICE client", p0.get("client_ice", ""), key=k + "ice")
    client_addr = c3.text_input("Adresse client", p0.get("client_address", ""), key=k + "addr")
    term_opts = ["Auto"] + terminals()
    bt0 = p0.get("bill_terminal")
    bill_sel = st.selectbox(
        "Terminal de facturation (droits nautique / port & tarif rade)", term_opts,
        index=term_opts.index(bt0) if bt0 in term_opts else 0, key=k + "term",
        help="« Auto » = terminal du 1er poste à quai ; escale au mouillage seul ⇒ "
             "Terminal Marchandises Diverses (TMD). Chaque poste à quai garde le taux "
             "de stationnement de son propre terminal.")

    # --- Itinéraire (postes & dates) → stationnement
    st.markdown("**🗺️ Itinéraire — postes & dates** (séjour ATA → ATD)")
    st.caption("Un tronçon par emplacement. Le terminal est déduit du nom du poste "
               "(TCE/TCO, TRV, PP, TGL, TMD/TVS) ; un nom contenant ANCH, MOUILL ou RADE "
               "est traité comme du mouillage en rade.")
    legs_df = pd.DataFrame([{"location": l["location"], "start": _ts(l["start"]),
                             "end": _ts(l["end"])} for l in p0["legs"]],
                           columns=["location", "start", "end"])
    legs_df["start"] = pd.to_datetime(legs_df["start"])
    legs_df["end"] = pd.to_datetime(legs_df["end"])
    legs_ed = st.data_editor(
        legs_df, num_rows="dynamic", hide_index=True, use_container_width=True,
        key=k + "legs",
        column_config={
            "location": st.column_config.TextColumn("Poste / emplacement", width="medium"),
            "start": st.column_config.DatetimeColumn("Début", format="DD/MM/YYYY HH:mm"),
            "end": st.column_config.DatetimeColumn("Fin", format="DD/MM/YYYY HH:mm"),
        })

    # --- Pilotage
    st.markdown("**🧭 Pilotage** (remorquage et amarrage exclus)")
    pil_df = pd.DataFrame(p0["pilotage"], columns=["mouvement", "de", "vers", "date", "type",
                                                   "annulation", "facturer"])
    pil_df["type"] = pil_df["type"].map(lambda t: _pmis.PILOT_TYPES.get(t, t))
    pil_df["date"] = pd.to_datetime(pil_df["date"].map(_ts))
    pil_df["annulation"] = pil_df["annulation"].astype(bool)
    pil_df["facturer"] = pil_df["facturer"].astype(bool)
    pil_ed = st.data_editor(
        pil_df, num_rows="dynamic", hide_index=True, use_container_width=True,
        key=k + "pil",
        column_config={
            "mouvement": st.column_config.TextColumn("Mouvement"),
            "de": st.column_config.TextColumn("De"),
            "vers": st.column_config.TextColumn("Vers"),
            "date": st.column_config.DatetimeColumn("Date", format="DD/MM/YYYY HH:mm"),
            "type": st.column_config.SelectboxColumn(
                "Barème", options=list(_pmis.PILOT_TYPES.values()), required=True),
            "annulation": st.column_config.CheckboxColumn("Annulation (+100 %)"),
            "facturer": st.column_config.CheckboxColumn("Facturer"),
        })

    # --- Articles ajoutés
    st.markdown("**➕ Articles supplémentaires**")
    a1, a2 = st.columns(2)
    with a1:
        st.caption("Articles du **catalogue** — chiffrés selon les paramètres de l'escale "
                   "(VG, GT, LOA, jours…).")
        ex_cat = [e for e in snap["extras"] if e.get("kind") == "catalog"]
        lbl = {o.split(" · ")[0]: o for o in cat_opts}
        cat_df = pd.DataFrame([{"article": lbl.get(e.get("code"), e.get("code")),
                                "quantite": float(e.get("quantite") or 1),
                                "majoration": float(e.get("majoration") or 0)} for e in ex_cat],
                              columns=["article", "quantite", "majoration"])
        cat_ed = st.data_editor(
            cat_df, num_rows="dynamic", hide_index=True, use_container_width=True,
            key=k + "xcat",
            column_config={
                "article": st.column_config.SelectboxColumn("Article", options=cat_opts,
                                                            width="large"),
                "quantite": st.column_config.NumberColumn("Qté", min_value=0.0, default=1.0,
                                                          format="%.2f"),
                "majoration": st.column_config.NumberColumn("Maj %", default=0.0,
                                                            format="%.0f"),
            })
    with a2:
        st.caption("**Lignes libres** — désignation et prix unitaire saisis.")
        ex_free = [e for e in snap["extras"] if e.get("kind") == "free"]
        free_df = pd.DataFrame([{c: e.get(c) for c in
                                 ("designation", "unite", "quantite", "pu", "majoration")}
                                for e in ex_free],
                               columns=["designation", "unite", "quantite", "pu", "majoration"])
        free_df = free_df.astype({"designation": object, "unite": object, "quantite": float,
                                  "pu": float, "majoration": float})
        free_ed = st.data_editor(
            free_df, num_rows="dynamic", hide_index=True, use_container_width=True,
            key=k + "xfree",
            column_config={
                "designation": st.column_config.TextColumn("Désignation", width="large"),
                "unite": st.column_config.TextColumn("Unité", default="u"),
                "quantite": st.column_config.NumberColumn("Qté", min_value=0.0, default=1.0,
                                                          format="%.2f"),
                "pu": st.column_config.NumberColumn("P.U.", min_value=0.0, default=0.0,
                                                    format="%.2f"),
                "majoration": st.column_config.NumberColumn("Maj %", default=0.0,
                                                            format="%.0f"),
            })

    # --- Paramètres courants → recalcul
    pil_code = {v_: c_ for c_, v_ in _pmis.PILOT_TYPES.items()}
    params = {
        **base,
        "loa": loa, "beam": beam, "gt": gt, "draft": draft,
        "client_name": client_name, "client_ice": client_ice, "client_address": client_addr,
        "bill_terminal": None if bill_sel == "Auto" else bill_sel,
        "legs": [{"location": (r.get("location") or "").strip(),
                  "start": _iso_or_empty(r.get("start")), "end": _iso_or_empty(r.get("end"))}
                 for r in _records(legs_ed)],
        "pilotage": [{"mouvement": r.get("mouvement") or "Mouvement", "de": r.get("de") or "",
                      "vers": r.get("vers") or "", "date": _iso_or_empty(r.get("date")),
                      "type": pil_code.get(r.get("type"), "ES"),
                      "annulation": bool(r.get("annulation")),
                      "facturer": r.get("facturer") is not False}
                     for r in _records(pil_ed)],
    }
    extras = [{"kind": "catalog", "code": str(r["article"]).split(" · ")[0],
               "quantite": r.get("quantite") if r.get("quantite") is not None else 1.0,
               "majoration": r.get("majoration") or 0.0}
              for r in _records(cat_ed) if r.get("article")]
    extras += [{"kind": "free", "designation": r.get("designation"),
                "unite": r.get("unite") or "u",
                "quantite": r.get("quantite") if r.get("quantite") is not None else 1.0,
                "pu": r.get("pu") or 0.0, "majoration": r.get("majoration") or 0.0}
               for r in _records(free_ed) if (r.get("designation") or "").strip()]

    # Mémorise les modifications de cette visite (persistées en SQLite)
    if params != base or extras:
        SS.pmis_edits[vid] = {"params": params, "extras": extras}
    else:
        SS.pmis_edits.pop(vid, None)
    if vid in SS.pmis_edits:
        if st.button("↺ Revenir aux données PMIS", key=k + "reset"):
            SS.pmis_edits.pop(vid, None)
            SS.pmis_ver[vid] = ver + 1
            st.rerun()

    call, lines = _pmis.build_from_params(params, SS.catalog, extras)

    # --- Résultat
    st.markdown("##### 5 · Facture recalculée")
    if call["terminal_mode"] == "mouillage":
        st.info("⚓ Escale **au mouillage seul** : facturée au **Terminal Marchandises "
                "Diverses (TMD)**.")
    elif call["terminal_mode"] == "défaut":
        st.warning("Aucun poste reconnu dans l'itinéraire : terminal par défaut "
                   f"**{call['terminal']}**. Choisissez le terminal de facturation ou "
                   "corrigez le nom du poste.")
    tot = billing.invoice_totals(lines)
    te_warn = call["draught_used"] > call["draught_declared"]
    st.markdown(
        f"<span class='pill'>{call['vessel_inline']['name']}</span>"
        f"<span class='pill'>{call['terminal']}</span>"
        f"<span class='pill'>{call['berth']}</span>"
        f"<span class='pill'>VG {call['vg']:,.2f} m³</span>"
        f"<span class='pill{' warn' if te_warn else ''}'>TE retenu "
        f"{call['draught_used']:.2f} m</span>"
        f"<span class='pill'>Séjour {call['sejour_h']:.1f} h"
        + (f" (rade {call['rade_h']:.0f} h)" if call["rade_h"] else "") + "</span>"
        f"<span class='pill ok'>Total {money(tot['total_ht'])}</span>",
        unsafe_allow_html=True)
    if te_warn:
        st.caption(f"⚓ TE déclaré {call['draught_declared']:.2f} m < minimum théorique "
                   f"0,14·√(L·B) = **{call['draught_min']:.2f} m** → TE retenu pour le VG.")
    st.dataframe(pd.DataFrame(lines, columns=["code", "designation", "quantite", "unite", "pu",
                                              "majoration", "montant_ht"]),
                 hide_index=True, use_container_width=True)
    if call.get("stationnement_detail"):
        with st.expander("🅿️ Détail du stationnement par tranche"):
            sd = pd.DataFrame(call["stationnement_detail"])
            sd["montant"] = sd["montant"].map(lambda x: money(x))
            st.dataframe(sd, hide_index=True, use_container_width=True)

    p1, p2, p3 = st.columns(3)
    inv_date = p1.date_input("Date de facture", value=date.today(), key="pmis_invdate")
    due_days = p2.number_input("Échéance (jours)", 0, 120, 30, key="pmis_due")
    prefix = p3.text_input("Préfixe n° facture", "NWM", key="pmis_prefix")

    number = billing.next_invoice_number(SS.inv_seq, prefix)
    vi = call["vessel_inline"]
    inv = {
        "number": number, "date": inv_date.strftime("%d/%m/%Y"),
        "due": (inv_date + timedelta(days=int(due_days))).strftime("%d/%m/%Y"),
        "client_name": call["client_name"], "client_address": call["client_address"],
        "client_code": "", "client_ice": call["client_ice"], "client_city": "",
        "client_country": "", "po": call["ref"], "contract": "",
        "vessel": {**vi, "vg": call["vg"], "draught_used": call["draught_used"],
                   "draught_declared": call["draught_declared"],
                   "draught_min": call["draught_min"]},
        "call": call, "lines": lines,
    }
    fxm = invoice_fx()
    html = billing.render_invoice_html(inv, SS.company, currency=SS.currency, fx_mad=fxm)
    with st.expander("👁️ Aperçu de la facture", expanded=True):
        st.components.v1.html(html, height=760, scrolling=True)

    d1, d2 = st.columns(2)
    try:
        pdfb = billing.render_invoice_pdf(inv, SS.company, currency=SS.currency, fx_mad=fxm)
        d1.download_button("⬇️ Télécharger la facture (PDF)", pdfb,
                           file_name=f"Facture_{number}.pdf", mime="application/pdf",
                           use_container_width=True)
    except Exception as e:
        d1.warning(f"PDF indisponible ({e})")
    if d2.button("💾 Enregistrer dans l'historique", use_container_width=True):
        SS.inv_seq += 1
        SS.invoices.append(inv)
        st.success(f"Facture {number} enregistrée (visite PMIS {call['ref']}).")


with tab_pmis:
    st.subheader("🔌 PMIS — escales & factures dynamiques")
    st.caption("Connexion à PMIS pour récupérer les visites facturables et générer "
               "les factures automatiquement. Prestations facturées : **droits de port** "
               "(nautique / port / stationnement) + **pilotage** ; remorqueurs et "
               "lamanage **exclus**. Pilotage en *annulation* ⇒ majoration +100 %. "
               "Les paramètres de l'escale (postes, dates, TE, dimensions, client…) sont "
               "modifiables et des articles peuvent être ajoutés à la facture.")

    _SECRETS_EXAMPLE = (
        "[pmis]\n"
        'auth_url    = "https://PMIS_IP/pmisAuthServer/api"\n'
        'backend_url = "https://PMIS_IP/pmisBackend/api"\n'
        'username    = "mon_utilisateur"   # ou : mail = "user@exemple.ma"\n'
        'password    = "••••••••"\n'
        'verify_ssl  = true\n'
    )

    try:
        import pmis as _pmis
    except Exception as _e:
        _pmis = None
        st.error(f"Module PMIS indisponible ({_e}). Vérifiez que « requests » est installé.")

    if _pmis is not None:
        client = _pmis.PMISClient()
        rep = client.config_report()
        cc = st.columns(4)
        cc[0].metric("Auth URL", "✓" if rep["auth_url"] else "—")
        cc[1].metric("Backend URL", "✓" if rep["backend_url"] else "—")
        cc[2].metric("Identifiant", "✓" if rep["identifiant"] else "—")
        cc[3].metric("Mot de passe", "✓" if rep["password"] else "—")
        if rep.get("login_endpoint"):
            st.caption(f"Appels : `POST {rep['login_endpoint']}` · "
                       f"`GET {rep['visits_endpoint']}`"
                       + ("" if rep["verify_ssl"] else " · ⚠️ TLS non vérifié"))

        if not client.configured():
            st.warning("Connexion PMIS non configurée. Renseignez les **secrets** dans "
                       "*Settings → Secrets* de l'application Streamlit (ou un fichier "
                       "`.streamlit/secrets.toml` en local). Aucun secret n'est stocké "
                       "dans le code.")
            st.code(_SECRETS_EXAMPLE, language="toml")
        else:
            st.markdown("##### 1 · Rechercher des visites")
            f1, f2, f3 = st.columns(3)
            eta_after = f1.date_input("ETA après le", value=date.today() - timedelta(days=15),
                                      key="pmis_eta_after")
            etd_before = f2.date_input("ETD avant le", value=date.today() + timedelta(days=15),
                                       key="pmis_etd_before")
            ship_name = f3.text_input("Nom du navire (optionnel)", key="pmis_ship")
            g1, g2, g3 = st.columns(3)
            only_billable = g1.checkbox("Facturables uniquement", value=True)
            status_lbl = g2.selectbox("Statut", ["Tous"] + list(_pmis.STATUS_LABELS.values()))
            page_size = g3.number_input("Taille de page", 1, 200, 50)

            if st.button("🔍 Interroger PMIS", type="primary"):
                params = {"etaAfterDate": eta_after.strftime("%Y-%m-%d"),
                          "etdBeforeDate": etd_before.strftime("%Y-%m-%d"),
                          "pageSize": int(page_size)}
                if ship_name:
                    params["shipName"] = ship_name
                if only_billable:
                    params["billable"] = "true"
                if status_lbl != "Tous":
                    inv_map = {v: k for k, v in _pmis.STATUS_LABELS.items()}
                    params["visitStatus"] = inv_map[status_lbl]
                try:
                    with st.spinner("Connexion à PMIS…"):
                        res = client.get_visits(**params)
                    SS.pmis_rows = res["rows"]
                    st.success(f"{len(res['rows'])} visite(s) récupérée(s)"
                               + (f" sur {res['total']} au total" if res.get("total") else ""))
                except _pmis.PMISError as e:
                    st.error(str(e))

            rows = SS.get("pmis_rows", [])
            if rows:
                st.markdown("##### 2 · Visites")
                st.dataframe(pd.DataFrame([_pmis.visit_summary(v) for v in rows]),
                             hide_index=True, use_container_width=True)

                billables = [v for v in rows if _pmis.is_billable(v)]
                st.markdown("##### 3 · Générer la facture d'une visite facturable")
                if not billables:
                    st.info("Aucune visite facturable (billable = true et billing_status vide) "
                            "dans les résultats.")
                else:
                    opts = {f"{_pmis.visit_summary(v)['business_id']} · "
                            f"{_pmis.visit_summary(v)['navire']}": v for v in billables}
                    sel = st.selectbox("Visite facturable", list(opts.keys()))
                    pmis_invoice_editor(_pmis, opts[sel])


# ═══════════════════════════════════════════════════════════════════════════════
#  PERSISTANCE — enregistre l'état courant à chaque exécution (fin de script)
# ═══════════════════════════════════════════════════════════════════════════════
persist()
