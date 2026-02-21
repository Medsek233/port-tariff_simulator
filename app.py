"""
🚢 Simulateur de Tarifs Portuaires — Tanger Med vs Nador West Med
Cahiers tarifaires 2025
"""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import math
from tarifs_data import *

# ─── CONFIG ──────────────────────────────────────────────────────────────────
st.set_page_config(page_title="Simulateur Tarifs TM vs NWM 2025", page_icon="🚢", layout="wide")
TM_C, NWM_C = "#1B4F72", "#C0392B"
TAUX_DH_EUR_DEFAULT = 10.85

# ─── CSS ─────────────────────────────────────────────────────────────────────
st.markdown("""<style>
[data-testid="stMetric"] {border:1px solid #e0e0e0;border-radius:8px;padding:10px 14px;background:#fafafa}
.stTabs [data-baseweb="tab-list"] {gap: 4px;}
.stTabs [data-baseweb="tab"] {padding: 6px 16px; font-size: 0.85rem;}
</style>""", unsafe_allow_html=True)

# ─── HELPERS ─────────────────────────────────────────────────────────────────
def fmt(v): return f"{v:,.2f} €"
def pct(tm, nwm):
    if tm == 0: return "—"
    d = (nwm - tm) / tm * 100
    return f"{'+' if d > 0 else ''}{d:.1f}%"

def bar2(label, vtm, vnwm, title=""):
    fig = go.Figure()
    fig.add_trace(go.Bar(name="Tanger Med", x=[title or ""], y=[vtm], marker_color=TM_C, text=[fmt(vtm)], textposition="outside"))
    fig.add_trace(go.Bar(name="NWM", x=[title or ""], y=[vnwm], marker_color=NWM_C, text=[fmt(vnwm)], textposition="outside"))
    fig.update_layout(barmode="group", height=320, margin=dict(t=30, b=20, l=40, r=20), legend=dict(orientation="h", y=1.15), yaxis_title="€")
    return fig

def stacked_bar(labels, vtm, vnwm):
    colors = ["#2980B9","#27AE60","#F39C12","#8E44AD","#E74C3C","#1ABC9C","#D35400","#2C3E50"]
    fig = go.Figure()
    for i, l in enumerate(labels):
        fig.add_trace(go.Bar(name=l, x=["Tanger Med","NWM"], y=[vtm[i], vnwm[i]], marker_color=colors[i % len(colors)]))
    fig.update_layout(barmode="stack", height=480, margin=dict(t=30,b=20), yaxis_title="€", legend=dict(orientation="h", y=1.12))
    return fig

# ─── SIDEBAR ─────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("⚙️ Paramètres Navire")
    loa = st.number_input("LOA (m)", 40.0, 400.0, 190.94, 0.5, help="Longueur hors tout")
    beam = st.number_input("Largeur (m)", 8.0, 65.0, 32.20, 0.1)
    draft = st.number_input("Tirant d'eau max (m)", 2.0, 25.0, 6.50, 0.1)
    gt = st.number_input("Gross Tonnage", 200, 300000, 22341, 100)
    vg = calc_vg(loa, beam, draft)
    st.metric("Volume Géométrique", f"{vg:,.0f} m³")
    st.divider()
    sejour_h = st.number_input("Séjour au port (h)", 1.0, 720.0, 12.0, 0.5)
    nb_rem = st.number_input("Remorqueurs", 0, 6, 2)
    nb_mvt = st.number_input("Mouvements (E+S)", 1, 8, 2)
    st.divider()
    taux_dh = st.number_input("Taux DH/EUR", 9.0, 12.0, TAUX_DH_EUR_DEFAULT, 0.01)

# ─── TITRE ───────────────────────────────────────────────────────────────────
st.title("🚢 Simulateur de Tarifs Portuaires 2025")
st.caption("**Tanger Med Port Authority** vs **Nador West Med** — Tous les éléments de facturation extraits des cahiers tarifaires")

# ─── TABS ────────────────────────────────────────────────────────────────────
tabs = st.tabs(["🏗️ Droits Port","🧭 Pilotage","⚓ Remorquage","🪢 Lamanage",
                "📦 Conteneurs","🚛 Marchandises Div.","🛢️ Hydrocarbures",
                "🚗 Roulier","📊 Stockage","🔧 Services & Divers","💰 Coût Total Escale"])

# ═════════════════════════════════════════════════════════════════════════════
# TAB 0 — DROITS DE PORT SUR NAVIRES
# ═════════════════════════════════════════════════════════════════════════════
with tabs[0]:
    st.header("Droits de Port sur Navires")
    st.info(f"LOA={loa}m · Beam={beam}m · Te={draft}m → **VG = {vg:,.0f} m³** | Séjour = {sejour_h}h")

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("🔵 Tanger Med")
        t_tm = st.selectbox("Terminal TM", list(DROITS_PORT_NAVIRES_TM.keys()), key="dp_tm")
        r = DROITS_PORT_NAVIRES_TM[t_tm]
        dp_n_tm = vg * r["nautique"]
        dp_p_tm = vg * r["port"]
        dp_s_tm = calc_stationnement(vg, r["stationnement"], sejour_h)
        tot_dp_tm = dp_n_tm + dp_p_tm + dp_s_tm
        st.metric("Droit Nautique", fmt(dp_n_tm), f"{r['nautique']} €/m³")
        st.metric("Droit de Port", fmt(dp_p_tm), f"{r['port']} €/m³")
        st.metric("Stationnement", fmt(dp_s_tm), f"{r['stationnement']} €/m³/j")
        st.metric("**TOTAL**", fmt(tot_dp_tm))

    with c2:
        st.subheader("🔴 Nador West Med")
        t_nwm = st.selectbox("Terminal NWM", list(DROITS_PORT_NAVIRES_NWM.keys()), key="dp_nwm")
        r2 = DROITS_PORT_NAVIRES_NWM[t_nwm]
        dp_n_nwm = vg * r2["nautique"]
        dp_p_nwm = vg * r2["port"]
        dp_s_nwm = calc_stationnement(vg, r2["stationnement"], sejour_h)
        tot_dp_nwm = dp_n_nwm + dp_p_nwm + dp_s_nwm
        st.metric("Droit Nautique", fmt(dp_n_nwm), f"{r2['nautique']} €/m³")
        st.metric("Droit de Port", fmt(dp_p_nwm), f"{r2['port']} €/m³")
        st.metric("Stationnement", fmt(dp_s_nwm), f"{r2['stationnement']} €/m³/j")
        st.metric("**TOTAL**", fmt(tot_dp_nwm))

    st.plotly_chart(bar2("", tot_dp_tm, tot_dp_nwm, "Droits de Port Total"), use_container_width=True)
    st.markdown(f"**Écart NWM vs TM : {pct(tot_dp_tm, tot_dp_nwm)}**")

    with st.expander("📋 Grille complète des taux (€/m³)"):
        rows = []
        mapping = [("TC", "Terminaux à Conteneurs (TC1-TC4)", "Terminal à Conteneurs"),
                   ("Vrac/MD", "Terminal Vrac & MD", "Terminal Marchandises Div"),
                   ("Hydrocarbures", "Terminal Hydrocarbures", "Terminal Hydrocarbures"),
                   ("GPL/GAZ", "Navires GPL", "Terminal GAZ")]
        for label, tm_k, nwm_k in mapping:
            a = DROITS_PORT_NAVIRES_TM.get(tm_k, {})
            b = DROITS_PORT_NAVIRES_NWM.get(nwm_k, {})
            if a and b:
                rows.append({"Terminal": label,
                    "TM Naut.": a["nautique"], "NWM Naut.": b["nautique"],
                    "TM Port": a["port"], "NWM Port": b["port"],
                    "TM Stat.": a["stationnement"], "NWM Stat.": b["stationnement"]})
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    with st.expander("📜 Règles de modulation — Stationnement"):
        st.markdown("""
        **Règles communes TM & NWM:**
        - **Franchise 24h** à partir du franchissement de la limite administrative
        - ≤8h après franchise → **1/3** du taux de base
        - >8h après franchise → taux plein par tranche indivisible de 24h

        **Différences:**
        - **TM:** Rade 50% dès le **6ème jour** | Exonération soutage **48h** à l'ancre
        - **NWM:** Rade 50% dès le **5ème jour** (1 jour plus tôt)
        """)

# ═════════════════════════════════════════════════════════════════════════════
# TAB 1 — PILOTAGE
# ═════════════════════════════════════════════════════════════════════════════
with tabs[1]:
    st.header("🧭 Pilotage")
    st.info(f"VG = {vg:,.0f} m³ | GT = {gt:,}")

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("🔵 Tanger Med — Barème par tranche VG")
        mvts_tm = st.multiselect("Mouvements TM", list(PILOTAGE_TM.keys()), default=["Entrée","Sortie"], key="pil_tm")
        pec = st.checkbox("PEC (Capitaine-Pilote)", key="pec")
        ret_tm = st.checkbox("Retard >20min (+100%)", key="ret_tm")
        des_tm = st.checkbox("Navire désemparé (+100%)", key="des_tm")
        dur_dep = st.checkbox("Dépassement durée 2h (+50%/h)", key="dur_dep")
        tot_pil_tm = 0
        det = []
        for m in mvts_tm:
            t = calc_pilotage_tm(vg, m)
            if pec:
                if m == "Sortie": t *= 0.5  # RoRo/Night ferry = 50% sortie
                else: t = 0
            if ret_tm: t *= 2
            if des_tm: t *= 2
            if dur_dep: t *= 1.5
            tot_pil_tm += t
            det.append({"Mouvement": m, "Tarif (€)": f"{t:,.2f}"})
        st.dataframe(pd.DataFrame(det), use_container_width=True, hide_index=True)
        st.metric("**TOTAL Pilotage TM**", fmt(tot_pil_tm))

    with c2:
        st.subheader("🔴 NWM — Formule linéaire GTs")
        mvts_nwm = st.multiselect("Mouvements NWM", ["Entrée/Sortie","Changement de Quai"], default=["Entrée/Sortie","Entrée/Sortie"], key="pil_nwm")
        des_nwm = st.checkbox("Navire désemparé (×2)", key="des_nwm")
        p_es = calc_pilotage_nwm_entree_sortie(gt)
        p_cq = calc_pilotage_nwm_chg_quai(gt)
        st.caption(f"E/S: 0.022641 × {gt:,} + 21.26 = **{p_es:,.2f} €** | Chg.Quai: {p_cq:,.2f} € | Min: 261,10 €")
        tot_pil_nwm = 0
        det2 = []
        for m in mvts_nwm:
            t = p_es if m == "Entrée/Sortie" else p_cq
            if des_nwm: t *= 2
            tot_pil_nwm += t
            det2.append({"Mouvement": m, "Tarif (€)": f"{t:,.2f}"})
        st.dataframe(pd.DataFrame(det2), use_container_width=True, hide_index=True)
        st.metric("**TOTAL Pilotage NWM**", fmt(tot_pil_nwm))

    st.plotly_chart(bar2("", tot_pil_tm, tot_pil_nwm, "Pilotage"), use_container_width=True)

    with st.expander("📈 Courbe pilotage E+S par taille navire"):
        gts_r = list(range(5000, 120001, 5000))
        c_tm, c_nwm = [], []
        for g in gts_r:
            v = g * 4.5
            c_tm.append(calc_pilotage_tm(v, "Entrée") + calc_pilotage_tm(v, "Sortie"))
            c_nwm.append(calc_pilotage_nwm_entree_sortie(g) * 2)
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=gts_r, y=c_tm, name="Tanger Med", line=dict(color=TM_C, width=3)))
        fig.add_trace(go.Scatter(x=gts_r, y=c_nwm, name="NWM", line=dict(color=NWM_C, width=3)))
        fig.update_layout(xaxis_title="GT", yaxis_title="Pilotage E+S (€)", height=380)
        st.plotly_chart(fig, use_container_width=True)

    with st.expander("📜 Majorations & Exonérations"):
        st.markdown("""
        **Tanger Med:**
        - Durée forfaitaire: 2h. Au-delà: +50% par heure entamée
        - Retard confirmé: +50% | Retard >20min après embarquement: +100%
        - Navire désemparé: +100%
        - **PEC**: exonération totale (RoRo/Night ferry: 50% sortie)
        - Vedette: 100€/h (intérieur), 175€/h (rade, min 300€)

        **NWM:**
        - Navire désemparé: tarif doublé (×2)
        - **Pas de mention PEC** ⚠️
        """)

# ═════════════════════════════════════════════════════════════════════════════
# TAB 2 — REMORQUAGE
# ═════════════════════════════════════════════════════════════════════════════
with tabs[2]:
    st.header("⚓ Remorquage")
    st.info(f"GT = {gt:,} | Remorqueurs: {nb_rem} | Mouvements: {nb_mvt}")
    sans_prop = st.checkbox("Navire sans propulsion (+25%)", key="sp_rem")
    dehalage = st.checkbox("Opération de déhalage (25% du tarif)", key="deh")

    t_r_tm = calc_remorquage(gt, REMORQUAGE_TM, REMORQUAGE_TM_SUP)
    t_r_nwm = calc_remorquage(gt, REMORQUAGE_NWM, REMORQUAGE_NWM_SUP)
    if sans_prop: t_r_tm *= 1.25; t_r_nwm *= 1.25
    if dehalage: t_r_tm *= 0.25; t_r_nwm *= 0.25
    tot_r_tm = t_r_tm * nb_rem * nb_mvt
    tot_r_nwm = t_r_nwm * nb_rem * nb_mvt

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("🔵 Tanger Med")
        st.metric("Tarif unitaire/rem./mvt", fmt(t_r_tm))
        st.metric(f"**TOTAL** ({nb_rem}×{nb_mvt})", fmt(tot_r_tm))
    with c2:
        st.subheader("🔴 NWM")
        st.metric("Tarif unitaire/rem./mvt", fmt(t_r_nwm))
        st.metric(f"**TOTAL** ({nb_rem}×{nb_mvt})", fmt(tot_r_nwm))

    st.plotly_chart(bar2("", tot_r_tm, tot_r_nwm, "Remorquage"), use_container_width=True)

    with st.expander("📋 Barème complet"):
        all_gts = sorted(set([lo for lo,_,_ in REMORQUAGE_TM] + [lo for lo,_,_ in REMORQUAGE_NWM]))
        rows = []
        for lo, hi, t in REMORQUAGE_TM:
            n = calc_remorquage((lo+hi)//2, REMORQUAGE_NWM, REMORQUAGE_NWM_SUP)
            rows.append({"GT": f"{lo:,}–{hi:,}", "TM (€)": f"{t:,.1f}", "NWM (€)": f"{n:,.1f}", "Δ": pct(t, n)})
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    with st.expander("📜 Services spéciaux remorquage"):
        st.markdown(f"""
        **Mise à disposition remorqueur (TM):** 1-2h: 553,60€/h · 3-12h: 532,80€/h · 13h+: 512,00€/h
        **Veille sécurité pétrolier:** TM: 339,90€/h/rem. · NWM: 330,00€/h/rem.
        **Attente/annulation TM:** 20% du tarif
        """)

# ═════════════════════════════════════════════════════════════════════════════
# TAB 3 — LAMANAGE
# ═════════════════════════════════════════════════════════════════════════════
with tabs[3]:
    st.header("🪢 Lamanage")
    st.info(f"LOA = {loa}m | GT = {gt:,}")

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("🔵 Tanger Med — Base LOA (mètres)")
        cat_l = st.selectbox("Catégorie", list(LAMANAGE_TM.keys()), key="lam_tm")
        duree_l = st.number_input("Durée lamanage (h)", 0.5, 12.0, 1.0, 0.5, key="dur_l")
        l = LAMANAGE_TM[cat_l]
        base_l = max(loa * l["tarif_ml"], l["min"])
        h_sup = max(0, duree_l - l["duree_max_h"])
        suppl = base_l * 0.30 * math.ceil(h_sup) if h_sup > 0 else 0
        tot_l_tm = base_l + suppl
        st.metric("Base", fmt(base_l), f"{l['tarif_ml']} €/ml × {loa}m (min {l['min']}€)")
        if suppl > 0: st.metric("Supplément durée (+30%/h)", fmt(suppl))
        st.metric("**TOTAL TM**", fmt(tot_l_tm))

    with c2:
        st.subheader("🔴 NWM — Formule GTs")
        tot_l_nwm = calc_lamanage_nwm(gt)
        st.caption(f"0.0108104 × {gt:,} + 6.68 = **{tot_l_nwm:,.2f} €**")
        st.metric("**TOTAL NWM**", fmt(tot_l_nwm))

    st.plotly_chart(bar2("", tot_l_tm, tot_l_nwm, "Lamanage"), use_container_width=True)

# ═════════════════════════════════════════════════════════════════════════════
# TAB 4 — CONTENEURS
# ═════════════════════════════════════════════════════════════════════════════
with tabs[4]:
    st.header("📦 Droits de Port sur Conteneurs")
    c1, c2 = st.columns(2)
    with c1:
        op_ctn = st.selectbox("Type opération", list(CONTENEURS_TM.keys()), key="op_ctn")
        nb_evp = st.number_input("Nombre d'EVP", 1, 50000, 500, 10, key="nb_evp")
        md = st.checkbox("Marchandises dangereuses (+50%)", key="md_ctn")
    with c2:
        st.markdown("### Tarifs unitaires (€/EVP)")
        st.markdown(f"**TM:** {CONTENEURS_TM[op_ctn]} | **NWM:** {CONTENEURS_NWM[op_ctn]}")

    mul = 1.5 if md else 1.0
    tot_c_tm = CONTENEURS_TM[op_ctn] * nb_evp * mul
    tot_c_nwm = CONTENEURS_NWM[op_ctn] * nb_evp * mul

    c1, c2 = st.columns(2)
    with c1:
        st.metric("🔵 Tanger Med", fmt(tot_c_tm))
    with c2:
        st.metric("🔴 NWM", fmt(tot_c_nwm))

    eco = tot_c_tm - tot_c_nwm
    if eco > 0:
        st.success(f"**Économie NWM : {fmt(eco)}** ({pct(tot_c_tm, tot_c_nwm)})")
    st.plotly_chart(bar2("", tot_c_tm, tot_c_nwm, f"Conteneurs {op_ctn}"), use_container_width=True)

    with st.expander("📋 Manutention Conteneurs TM (tarifs max publics)"):
        rows = []
        for tc, v in MANUTENTION_CTN_TM.items():
            rows.append({"Terminal": tc, "20' Bord-Quai": f"{v['20_bord_quai']}€", "40' Bord-Quai": f"{v['40_bord_quai']}€",
                         "20' Terre": f"{v['20_terre']}€", "Pesage": f"{v['pesage']}€"})
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        st.warning("⚠️ NWM ne publie pas de tarifs de manutention conteneurs")

# ═════════════════════════════════════════════════════════════════════════════
# TAB 5 — MARCHANDISES DIVERSES
# ═════════════════════════════════════════════════════════════════════════════
with tabs[5]:
    st.header("🚛 Marchandises Diverses")
    tonnage = st.number_input("Tonnage (tonnes)", 1, 500000, 5000, 100, key="ton_md")
    all_md = sorted(set(list(MARCHANDISES_DIV_TM.keys()) + list(MARCHANDISES_DIV_NWM.keys())))
    rows = []
    for t in all_md:
        a = MARCHANDISES_DIV_TM.get(t)
        b = MARCHANDISES_DIV_NWM.get(t)
        rows.append({"Marchandise": t,
            "TM (€/T)": f"{a:.3f}" if a else "N/A",
            "NWM (€/T)": f"{b:.3f}" if b else "N/A",
            f"TM ({tonnage:,}T)": fmt(a * tonnage) if a else "N/A",
            f"NWM ({tonnage:,}T)": fmt(b * tonnage) if b else "N/A",
            "Écart": pct(a, b) if (a and b) else "—"})
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    common = [t for t in all_md if t in MARCHANDISES_DIV_TM and t in MARCHANDISES_DIV_NWM]
    fig = go.Figure()
    fig.add_trace(go.Bar(name="TM", x=common, y=[MARCHANDISES_DIV_TM[t] for t in common], marker_color=TM_C))
    fig.add_trace(go.Bar(name="NWM", x=common, y=[MARCHANDISES_DIV_NWM[t] for t in common], marker_color=NWM_C))
    fig.update_layout(barmode="group", height=400, yaxis_title="€/T", margin=dict(t=30,b=80))
    st.plotly_chart(fig, use_container_width=True)

# ═════════════════════════════════════════════════════════════════════════════
# TAB 6 — HYDROCARBURES
# ═════════════════════════════════════════════════════════════════════════════
with tabs[6]:
    st.header("🛢️ Hydrocarbures (NWM détaillé)")
    ton_h = st.number_input("Tonnage hydrocarbures", 100, 500000, 10000, 100, key="ton_h")
    prod = st.selectbox("Produit", list(HYDROCARBURES_NWM.keys()), key="h_prod")
    op_h = st.selectbox("Opération", list(HYDROCARBURES_NWM[prod].keys()), key="h_op")
    t_h = HYDROCARBURES_NWM[prod][op_h]
    st.metric(f"🔴 NWM: {t_h} €/T × {ton_h:,}T", fmt(t_h * ton_h))
    st.info("Tanger Med ne publie pas de détail comparable pour les hydrocarbures")

    rows = []
    for p, ops in HYDROCARBURES_NWM.items():
        for o, t in ops.items():
            rows.append({"Produit": p, "Opération": o, "€/T": t, f"Total {ton_h:,}T": fmt(t * ton_h)})
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

# ═════════════════════════════════════════════════════════════════════════════
# TAB 7 — ROULIER
# ═════════════════════════════════════════════════════════════════════════════
with tabs[7]:
    st.header("🚗 Terminal Roulier")

    st.subheader("Droits port sur navires rouliers")
    dur_ro = st.number_input("Durée escale (h)", 1.0, 48.0, 6.0, 0.5, key="dur_ro")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("#### 🔵 Tanger Med")
        cat_ro = st.selectbox("Catégorie", list(ROULIERS_TM.keys()), key="cat_ro")
        r = ROULIERS_TM[cat_ro]
        if dur_ro <= r["duree_h"]:
            esc_tm = r["forfait"]
        else:
            sup30 = math.ceil((dur_ro - r["duree_h"]) * 2)
            esc_tm = r["forfait"] + sup30 * r["suppl_30min"]
        naut_ro_tm = vg * ROULIERS_TM_NAUTIQUE
        st.metric("Forfait escale", fmt(esc_tm))
        st.metric("Droit nautique", fmt(naut_ro_tm))
        st.metric("**TOTAL navire TM**", fmt(esc_tm + naut_ro_tm))
    with c2:
        st.markdown("#### 🔴 NWM")
        rn = ROULIERS_NWM["Forfait unique (≤8h)"]
        if dur_ro <= rn["duree_h"]:
            esc_nwm = rn["forfait"]
        else:
            sup30 = math.ceil((dur_ro - rn["duree_h"]) * 2)
            esc_nwm = rn["forfait"] + sup30 * rn["suppl_30min"]
        naut_ro_nwm = vg * ROULIERS_NWM_NAUTIQUE
        st.metric("Forfait escale", fmt(esc_nwm))
        st.metric("Droit nautique", fmt(naut_ro_nwm))
        st.metric("**TOTAL navire NWM**", fmt(esc_nwm + naut_ro_nwm))

    st.divider()
    st.subheader("Droits port sur marchandises roulier")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("#### 🔵 TM (€)")
        rows = [{"Type": k, "Import": v["Import"], "Export": v["Export"]} for k, v in MARCHANDISES_ROULIER_TM.items()]
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    with c2:
        st.markdown(f"#### 🔴 NWM (DH → € @ {taux_dh:.2f})")
        rows = [{"Type": k, "DH": f"{v:,.2f}", "€": fmt(v / taux_dh)} for k, v in MARCHANDISES_ROULIER_NWM_DH.items()]
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        st.warning("⚠️ NWM facture en DH — risque de change")

    st.divider()
    st.subheader("Simulation fret")
    c1, c2, c3 = st.columns(3)
    with c1: nb_rp = st.number_input("Remorques pleines (import)", 0, 500, 50, key="rp")
    with c2: nb_rv = st.number_input("Remorques vides", 0, 500, 20, key="rv")
    with c3: nb_cam = st.number_input("Camions ≤12m pleins (import)", 0, 200, 10, key="cam")

    fret_tm = nb_rp * 195 + nb_rv * 62 + nb_cam * 104
    fret_nwm = (nb_rp * 1500.564 + nb_rv * 289.056 + nb_cam * 807.662) / taux_dh
    st.plotly_chart(bar2("", fret_tm, fret_nwm, "Fret roulier"), use_container_width=True)
    st.markdown(f"**TM: {fmt(fret_tm)}** | **NWM: {fmt(fret_nwm)}** | Δ: {pct(fret_tm, fret_nwm)}")

    with st.expander("📋 Passagers & Véhicules légers (TM)"):
        st.markdown("**Passagers:**")
        st.dataframe(pd.DataFrame([{"Cat": k, "€/pax": v} for k, v in PASSAGERS_TM.items()]), use_container_width=True, hide_index=True)
        st.markdown("**Véhicules légers:**")
        st.dataframe(pd.DataFrame([{"Type": k, "€": v} for k, v in VEHICULES_PASSAGERS_TM.items()]), use_container_width=True, hide_index=True)

# ═════════════════════════════════════════════════════════════════════════════
# TAB 8 — STOCKAGE
# ═════════════════════════════════════════════════════════════════════════════
with tabs[8]:
    st.header("📊 Stockage")

    st.subheader("Stockage Conteneurs (Tanger Med)")
    c1, c2 = st.columns([1, 2])
    with c1:
        tc_s = st.selectbox("Terminal", list(STOCKAGE_CTN_TM.keys()), key="tc_s")
        type_s = st.selectbox("Type conteneur", list(STOCKAGE_CTN_TM[tc_s].keys()), key="type_s")
        nb_j = st.slider("Durée (jours)", 1, 30, 7, key="nb_j")
        nb_c = st.number_input("Nombre conteneurs", 1, 5000, 100, key="nb_c")

    tarifs = STOCKAGE_CTN_TM[tc_s][type_s]
    cout = 0
    det = []
    for j in range(1, nb_j + 1):
        if j <= tarifs["franchise"]: t = 0; p = "Franchise"
        elif j <= 7: t = tarifs["j3_7"]; p = "J3-7"
        else: t = tarifs["j8+"]; p = "J8+"
        cout += t
        det.append({"Jour": j, "Période": p, "€/j": f"{t:.2f}", "Cumul": f"{cout:.2f}"})
    with c2:
        st.metric(f"Coût/conteneur ({nb_j}j)", fmt(cout))
        st.metric(f"**TOTAL ({nb_c} × {nb_j}j)**", fmt(cout * nb_c))
        with st.expander("Détail jour par jour"):
            st.dataframe(pd.DataFrame(det), use_container_width=True, hide_index=True)

    st.warning("⚠️ **NWM ne publie aucun tarif de stockage conteneurs** — lacune majeure")

    st.divider()
    st.subheader("Stockage Vrac TM (€/T/jour)")
    rows = []
    for lieu, t in STOCKAGE_VRAC_TM.items():
        for per, val in t.items():
            rows.append({"Lieu": lieu, "Période": per, "€/T/j": val})
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("Parking TIR (Tanger Med)")
    rows = [{"Catégorie": k, **{kk: vv for kk, vv in v.items()}} for k, v in PARKING_TIR_TM.items()]
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

# ═════════════════════════════════════════════════════════════════════════════
# TAB 9 — SERVICES DIVERS
# ═════════════════════════════════════════════════════════════════════════════
with tabs[9]:
    st.header("🔧 Services & Divers")
    st.info("Services exclusifs Tanger Med — NWM ne les mentionne pas dans son cahier tarifaire 2025")

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("🚜 Traction Portuaire")
        st.dataframe(pd.DataFrame([{"Opération": k, "€": v} for k, v in TRACTION_PORTUAIRE_TM.items()]), use_container_width=True, hide_index=True)

    with c2:
        st.subheader("💧 Fournitures (TM = NWM)")
        st.dataframe(pd.DataFrame([{"Service": k, "Unité": v["unite"], "Tarif": v["tarif"]} for k, v in FOURNITURES.items()]), use_container_width=True, hide_index=True)

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("🚤 Taxi Rade TM")
        st.dataframe(pd.DataFrame([{"": k, "Tarif": v} for k, v in TAXI_RADE_TM.items()]), use_container_width=True, hide_index=True)

        st.subheader("🛡️ Sécurité TM")
        st.dataframe(pd.DataFrame([{"Service": k, "€": v} for k, v in SECURITE_TM.items()]), use_container_width=True, hide_index=True)

    with c2:
        st.subheader("🔍 ZVCI TM")
        st.dataframe(pd.DataFrame([{"Service": k, "€": v} for k, v in ZVCI_TM.items()]), use_container_width=True, hide_index=True)

        st.subheader("🚗 TVCU Manutention TM")
        st.dataframe(pd.DataFrame([{"Service": k, "€": v} for k, v in TVCU_MANUTENTION_TM.items()]), use_container_width=True, hide_index=True)

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("📄 MRN TM")
        st.dataframe(pd.DataFrame([{"Tranche": k, "€/MRN": v} for k, v in MRN_TM.items()]), use_container_width=True, hide_index=True)
    with c2:
        st.subheader("🏥 Divers TM")
        st.metric("Consultation médicale", f"{CONSULTATION_MEDICALE_TM} €")
        st.dataframe(pd.DataFrame([{"": k, "Tarif": f"{v} €"} for k, v in DIVERS_TM.items()]), use_container_width=True, hide_index=True)

# ═════════════════════════════════════════════════════════════════════════════
# TAB 10 — COÛT TOTAL ESCALE
# ═════════════════════════════════════════════════════════════════════════════
with tabs[10]:
    st.header("💰 Simulation Coût Total d'Escale")
    st.info(f"**Navire:** LOA={loa}m · Beam={beam}m · Te={draft}m · GT={gt:,} · VG={vg:,.0f}m³ | Séjour={sejour_h}h | {nb_rem} remorqueurs · {nb_mvt} mouvements")

    c1, c2, c3 = st.columns(3)
    with c1:
        tt_tm = st.selectbox("Terminal TM", list(DROITS_PORT_NAVIRES_TM.keys()), key="tot_tm")
        tt_nwm = st.selectbox("Terminal NWM", list(DROITS_PORT_NAVIRES_NWM.keys()), key="tot_nwm")
    with c2:
        evp_t = st.number_input("EVP", 0, 20000, 500, 50, key="evp_t")
        op_t = st.selectbox("Op. conteneurs", list(CONTENEURS_TM.keys()), key="op_t")
    with c3:
        cat_lam_t = st.selectbox("Cat. lamanage TM", list(LAMANAGE_TM.keys()), key="lt")

    # === CALCULS TM ===
    r_tm = DROITS_PORT_NAVIRES_TM[tt_tm]
    v_naut_tm = vg * r_tm["nautique"]
    v_port_tm = vg * r_tm["port"]
    v_stat_tm = calc_stationnement(vg, r_tm["stationnement"], sejour_h)
    v_pil_tm = calc_pilotage_tm(vg, "Entrée") + calc_pilotage_tm(vg, "Sortie")
    v_rem_tm = calc_remorquage(gt, REMORQUAGE_TM, REMORQUAGE_TM_SUP) * nb_rem * nb_mvt
    ll = LAMANAGE_TM[cat_lam_t]
    v_lam_tm = max(loa * ll["tarif_ml"], ll["min"])
    v_ctn_tm = CONTENEURS_TM[op_t] * evp_t

    # === CALCULS NWM ===
    r_nwm = DROITS_PORT_NAVIRES_NWM[tt_nwm]
    v_naut_nwm = vg * r_nwm["nautique"]
    v_port_nwm = vg * r_nwm["port"]
    v_stat_nwm = calc_stationnement(vg, r_nwm["stationnement"], sejour_h)
    v_pil_nwm = calc_pilotage_nwm_entree_sortie(gt) * 2
    v_rem_nwm = calc_remorquage(gt, REMORQUAGE_NWM, REMORQUAGE_NWM_SUP) * nb_rem * nb_mvt
    v_lam_nwm = calc_lamanage_nwm(gt)
    v_ctn_nwm = CONTENEURS_NWM[op_t] * evp_t

    labels = ["Droit Nautique","Droit de Port","Stationnement","Pilotage","Remorquage","Lamanage","Marchandises CTN"]
    vtm = [v_naut_tm, v_port_tm, v_stat_tm, v_pil_tm, v_rem_tm, v_lam_tm, v_ctn_tm]
    vnwm = [v_naut_nwm, v_port_nwm, v_stat_nwm, v_pil_nwm, v_rem_nwm, v_lam_nwm, v_ctn_nwm]
    total_tm = sum(vtm)
    total_nwm = sum(vnwm)

    c1, c2 = st.columns(2)
    with c1:
        st.subheader(f"🔵 Tanger Med — {fmt(total_tm)}")
        for l, v in zip(labels, vtm):
            st.metric(l, fmt(v))
    with c2:
        st.subheader(f"🔴 NWM — {fmt(total_nwm)}")
        for l, v in zip(labels, vnwm):
            st.metric(l, fmt(v))

    eco = total_tm - total_nwm
    port_best = "NWM" if eco > 0 else "Tanger Med"
    st.success(f"### 💡 Économie **{port_best}** : {fmt(abs(eco))} ({pct(total_tm, total_nwm)})")

    st.plotly_chart(stacked_bar(labels, vtm, vnwm), use_container_width=True)

    # Tableau récap
    recap = []
    for l, a, b in zip(labels, vtm, vnwm):
        recap.append({"Poste": l, "Tanger Med": fmt(a), "NWM": fmt(b), "Écart": pct(a, b)})
    recap.append({"Poste": "🔴 TOTAL", "Tanger Med": fmt(total_tm), "NWM": fmt(total_nwm), "Écart": pct(total_tm, total_nwm)})
    st.dataframe(pd.DataFrame(recap), use_container_width=True, hide_index=True)

    # Sensibilité EVP
    with st.expander("📈 Sensibilité par volume EVP"):
        evps = [100, 500, 1000, 2000, 5000, 10000]
        s_tm, s_nwm = [], []
        base_tm = v_naut_tm + v_port_tm + v_stat_tm + v_pil_tm + v_rem_tm + v_lam_tm
        base_nwm = v_naut_nwm + v_port_nwm + v_stat_nwm + v_pil_nwm + v_rem_nwm + v_lam_nwm
        for e in evps:
            s_tm.append(base_tm + CONTENEURS_TM[op_t] * e)
            s_nwm.append(base_nwm + CONTENEURS_NWM[op_t] * e)
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=evps, y=s_tm, name="Tanger Med", line=dict(color=TM_C, width=3)))
        fig.add_trace(go.Scatter(x=evps, y=s_nwm, name="NWM", line=dict(color=NWM_C, width=3)))
        fig.update_layout(xaxis_title="EVP", yaxis_title="Coût total escale (€)", height=400)
        st.plotly_chart(fig, use_container_width=True)

# ─── FOOTER ──────────────────────────────────────────────────────────────────
st.divider()
st.caption("📌 Simulateur basé sur les cahiers tarifaires 2025 — TMPA & NWM | Données extraites fév. 2026 | Tous tarifs HT")
