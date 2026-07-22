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
import uuid
from datetime import date, datetime, timedelta

import pandas as pd
import streamlit as st

import billing
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


def init_state():
    ss = st.session_state
    if "vessels" not in ss:
        ss.vessels = _seed_vessels()
    if "catalog" not in ss:
        ss.catalog = billing.default_catalog()
    if "calls" not in ss:
        ss.calls = []
    if "invoices" not in ss:
        ss.invoices = []
    if "inv_seq" not in ss:
        ss.inv_seq = 1
    if "company" not in ss:
        ss.company = {
            "name": "Nador West Med — Autorité Portuaire",
            "address": "Port de Nador West Med, Betoya, Maroc",
            "ice": "0027 5896 000 084", "if": "5289 3410",
            "footer": "Règlement à 30 jours par virement bancaire. Tous tarifs HT en EUR.",
        }
    if "currency" not in ss:
        ss.currency = "EUR"
    if "fx_mad" not in ss:
        ss.fx_mad = 10.85


init_state()
SS = st.session_state


# ═══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════════════════
def vessel_by_id(vid):
    return next((v for v in SS.vessels if v["id"] == vid), None)


def vessel_vg(v):
    return td.calc_vg(v["loa"], v["beam"], v["draft"]) if v else 0.0


def money(v, cur=None):
    cur = cur or SS.currency
    try:
        return f"{float(v):,.2f} {cur}"
    except Exception:
        return f"— {cur}"


def terminals():
    return list(td.DROITS_PORT_NAVIRES_NWM.keys())


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
    if st.button("↺ Réinitialiser les données", use_container_width=True):
        for k in ["vessels", "catalog", "calls", "invoices", "inv_seq"]:
            SS.pop(k, None)
        init_state()
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
    ca_ttc = sum(billing.invoice_totals(c["lines"])["total_ttc"] for c in SS.calls)

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Escales", n_calls)
    k2.metric("Factures émises", n_inv)
    k3.metric("CA prévisionnel HT", money(ca_ht))
    k4.metric("CA prévisionnel TTC", money(ca_ttc))

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
                "Total HT": money(t["total_ht"]), "Total TTC": money(t["total_ttc"]),
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
            disp.append({
                "Navire": v["name"], "Type": v["type"], "IMO": v["imo"], "Pavillon": v["flag"],
                "GT": f"{v['gt']:,.0f}", "LOA": v["loa"], "Largeur": v["beam"],
                "TE": v["draft"], "VG (m³)": f"{vessel_vg(v):,.0f}",
            })
        st.dataframe(pd.DataFrame(disp), hide_index=True, use_container_width=True)

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
            d, e, f, g = st.columns(4)
            unit = d.text_input("Unité", "u")
            rate = e.number_input("Tarif unitaire", min_value=0.0, value=0.0, step=0.01,
                                  format="%.5f")
            basis = f.selectbox("Base de calcul", billing.BASES,
                                format_func=lambda x: f"{x} — {billing.BASIS_LABEL[x]}")
            vat = g.number_input("TVA %", min_value=0.0, max_value=100.0,
                                 value=billing.TVA_DEFAULT, step=1.0)
            if st.form_submit_button("Ajouter l'article", type="primary"):
                if not code or not label:
                    st.error("Code et désignation sont obligatoires.")
                elif any(it["code"] == code for it in SS.catalog):
                    st.error(f"Le code « {code} » existe déjà.")
                else:
                    SS.catalog.append({
                        "code": code, "category": category, "label": label, "unit": unit,
                        "rate": rate, "basis": basis, "vat": vat, "taxable": vat > 0,
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
            "vat": st.column_config.NumberColumn("TVA %", format="%.0f"),
            "taxable": st.column_config.CheckboxColumn("Taxable"),
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
            st.markdown(
                f"<span class='pill'>GT {vessel['gt']:,.0f}</span>"
                f"<span class='pill'>VG {vg:,.0f} m³</span>"
                f"<span class='pill'>{vessel['type']}</span>",
                unsafe_allow_html=True,
            )
            terminal = st.selectbox("Terminal", terminals())
            berth = st.text_input("Poste à quai", "P1")
            d1, d2 = st.columns(2)
            eta = d1.date_input("Arrivée (ETA)", value=date.today())
            etd = d2.date_input("Départ (ETD)", value=date.today() + timedelta(days=2))
            h1, h2 = st.columns(2)
            eta_h = h1.number_input("Heure ETA", 0, 23, 8)
            etd_h = h2.number_input("Heure ETD", 0, 23, 14)
            dt_a = datetime.combine(eta, datetime.min.time()) + timedelta(hours=eta_h)
            dt_d = datetime.combine(etd, datetime.min.time()) + timedelta(hours=etd_h)
            sejour_h = max((dt_d - dt_a).total_seconds() / 3600.0, 0.0)
            jours = max(1, -(-int(sejour_h) // 24))
            st.caption(f"⏱️ Séjour : **{sejour_h:.0f} h** (~{jours} j)")

            client_name = st.text_input("Client / Armateur", "MSC Maroc SARL")
            client_addr = st.text_input("Adresse client", "Casablanca, Maroc")

        # ---- Prestations à générer
        with right:
            st.markdown("##### 2 · Prestations & mouvements")
            movements = st.multiselect(
                "Mouvements pilotage / remorquage / lamanage",
                ["Entrée", "Sortie", "Changement de quai"],
                default=["Entrée", "Sortie"],
            )
            nb_mvt = sum(1 for m in movements if m in ("Entrée", "Sortie"))
            nb_cq = sum(1 for m in movements if m == "Changement de quai")

            svc = st.multiselect(
                "Services rendus",
                ["Droits de port navire", "Pilotage", "Remorquage", "Lamanage",
                 "Marchandise", "Fournitures / Services"],
                default=["Droits de port navire", "Pilotage", "Remorquage", "Lamanage"],
            )

            nb_tugs = st.number_input("Remorqueurs par mouvement", 1, 4, 2)
            en_rade = st.checkbox("Séjour en rade (réduction stationnement)")
            jour_rade = st.number_input("Jours en rade", 0, 60, 0) if en_rade else 0

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

            maj_pilotage = st.slider("Majoration pilotage (%)", 0, 100, 0,
                                     help="Ex : navire désemparé = +100%")

        st.divider()
        if st.button("⚙️ Générer les prestations", type="primary", use_container_width=True):
            ctx = billing.CallContext(gt=vessel["gt"], vg=vg, loa=vessel["loa"],
                                      sejour_h=sejour_h, jours=jours,
                                      en_rade=en_rade, jour_rade=jour_rade)
            lines = []
            cat_by_code = {it["code"]: it for it in SS.catalog if it.get("active", True)}
            term_pref = terminal.split()[-1][:3].upper()

            def find(code):
                return cat_by_code.get(code)

            # Droits de port navire (selon terminal)
            if "Droits de port navire" in svc:
                for pre in ("DN", "DP", "DS"):
                    it = find(f"{pre}-{term_pref}")
                    if it:
                        lines.append(billing.make_line(it, 1, ctx))
            # Pilotage
            if "Pilotage" in svc:
                if nb_mvt and find("PIL-ES"):
                    lines.append(billing.make_line(find("PIL-ES"), nb_mvt, ctx, maj_pilotage))
                if nb_cq and find("PIL-CQ"):
                    lines.append(billing.make_line(find("PIL-CQ"), nb_cq, ctx, maj_pilotage))
            # Remorquage
            if "Remorquage" in svc and find("REM"):
                total_mvt = nb_mvt + nb_cq
                lines.append(billing.make_line(find("REM"), nb_tugs * max(total_mvt, 1), ctx))
            # Lamanage
            if "Lamanage" in svc and find("LAM"):
                lines.append(billing.make_line(find("LAM"), nb_mvt + nb_cq, ctx))
            # Marchandise
            if "Marchandise" in svc and mcode and mqty > 0 and find(mcode):
                lines.append(billing.make_line(find(mcode), mqty, ctx))

            call = {
                "id": str(uuid.uuid4()),
                "ref": f"ESC-{datetime.now():%Y%m%d}-{len(SS.calls)+1:03d}",
                "vessel_id": vessel["id"], "terminal": terminal, "berth": berth,
                "eta": dt_a.strftime("%d/%m/%Y %H:%M"), "etd": dt_d.strftime("%d/%m/%Y %H:%M"),
                "sejour_h": sejour_h, "jours": jours, "movements": movements,
                "client_name": client_name, "client_address": client_addr,
                "lines": lines, "status": "Brouillon",
            }
            SS.calls.append(call)
            SS.active_call = call["id"]
            st.success(f"Escale **{call['ref']}** générée avec {len(lines)} prestations.")
            st.rerun()

    # ---- Éditer une escale existante
    if SS.calls:
        st.divider()
        st.markdown("##### 3 · Détail & édition des prestations d'une escale")
        refs = [c["ref"] for c in SS.calls]
        default_idx = refs.index(SS.get("active_call_ref")) if SS.get("active_call_ref") in refs else len(refs) - 1
        sel_ref = st.selectbox("Escale", refs, index=default_idx)
        call = next(c for c in SS.calls if c["ref"] == sel_ref)
        SS.active_call_ref = sel_ref
        v = vessel_by_id(call["vessel_id"])

        st.markdown(
            f"<span class='pill'>{v['name'] if v else '—'}</span>"
            f"<span class='pill'>{call['terminal']}</span>"
            f"<span class='pill'>Arr. {call['eta']}</span>"
            f"<span class='pill'>Dép. {call['etd']}</span>"
            f"<span class='pill ok'>{call.get('status','Brouillon')}</span>",
            unsafe_allow_html=True,
        )

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
                "montant_ht": st.column_config.NumberColumn("Montant HT", format="%.2f"),
                "tva": st.column_config.NumberColumn("TVA %", format="%.0f"),
            },
        )

        tot = billing.invoice_totals(edited_lines.to_dict("records"))
        m1, m2, m3 = st.columns(3)
        m1.metric("Total HT", money(tot["total_ht"]))
        m2.metric("TVA", money(tot["total_tva"]))
        m3.metric("Total TTC", money(tot["total_ttc"]))

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
                "vessel": {**v, "vg": vessel_vg(v)} if v else {},
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
            hc1, hc2, hc3 = st.columns(3)
            hc1.metric("Total HT", money(tot["total_ht"]))
            hc2.metric("TVA", money(tot["total_tva"]))
            hc3.metric("Total TTC", money(tot["total_ttc"]))
            if SS.currency == "EUR" and SS.fx_mad:
                st.caption(f"Contre-valeur TTC : **{tot['total_ttc']*SS.fx_mad:,.2f} MAD** "
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
                "Total HT": money(t["total_ht"]), "Total TTC": money(t["total_ttc"]),
            })
        st.dataframe(pd.DataFrame(hist), hide_index=True, use_container_width=True)
