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
st.set_page_config(page_title="Simulateur Tarifs TM vs NWM vs Algeciras", page_icon="🚢", layout="wide")
TM_C, NWM_C, ALG_C = "#1B4F72", "#C0392B", "#2E7D32"
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

def bar3(label, vtm, vnwm, valg, title=""):
    fig = go.Figure()
    fig.add_trace(go.Bar(name="Tanger Med", x=[title or ""], y=[vtm], marker_color=TM_C, text=[fmt(vtm)], textposition="outside"))
    fig.add_trace(go.Bar(name="NWM", x=[title or ""], y=[vnwm], marker_color=NWM_C, text=[fmt(vnwm)], textposition="outside"))
    fig.add_trace(go.Bar(name="Algeciras", x=[title or ""], y=[valg], marker_color=ALG_C, text=[fmt(valg)], textposition="outside"))
    fig.update_layout(barmode="group", height=350, margin=dict(t=30, b=20, l=40, r=20), legend=dict(orientation="h", y=1.15), yaxis_title="€")
    return fig

def stacked_bar3(labels, vtm, vnwm, valg):
    colors = ["#2980B9","#27AE60","#F39C12","#8E44AD","#E74C3C","#1ABC9C","#D35400","#2C3E50"]
    fig = go.Figure()
    for i, l in enumerate(labels):
        fig.add_trace(go.Bar(name=l, x=["Tanger Med","NWM","Algeciras"], y=[vtm[i], vnwm[i], valg[i]], marker_color=colors[i % len(colors)]))
    fig.update_layout(barmode="stack", height=500, margin=dict(t=30,b=20), yaxis_title="€", legend=dict(orientation="h", y=1.12))
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
    st.divider()
    st.subheader("🇪🇸 Algeciras")
    alg_freq = st.selectbox("Fréquence escales/an", list(ALG_T1_REDUCTION_FREQUENCE.keys()), index=3,
                            help="Réduction progressive par nombre d'escales annuelles")
    alg_regulier = st.checkbox("Service régulier (-5%)", value=True)
    alg_concession = st.selectbox("Type poste", ["Quai/Jetée sans concession", "Quai/Jetée concession avec lame d'eau"],
                                  help="Terminal concession = tarifs réduits")

# ─── TITRE ───────────────────────────────────────────────────────────────────
st.title("🚢 Simulateur de Tarifs Portuaires 2025")
st.caption("**Tanger Med** vs **Nador West Med** vs **Algeciras** — Tous les éléments de facturation extraits des cahiers tarifaires")

# ─── TABS ────────────────────────────────────────────────────────────────────
tabs = st.tabs(["🏗️ Droits Port","🧭 Pilotage","⚓ Remorquage","🪢 Lamanage",
                "📦 Conteneurs","🚛 Marchandises Div.","🛢️ Hydrocarbures",
                "🚗 Roulier","📊 Stockage","🔧 Services & Divers",
                "🇪🇸 Algeciras","💰 Coût Total 3 Ports"])

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
        st.caption("""
        **Méthode:** On utilise les proportions du navire saisi (LOA/beam/draft) comme référence,
        puis on fait varier la taille par un facteur d'échelle. Le VG est recalculé à chaque point
        via la formule officielle VG = L × b × Te. Le GT est estimé via le ratio GT/VG du navire de référence.
        """)
        # Ratio réel GT/VG du navire saisi
        ratio_gt_vg = gt / vg if vg > 0 else 0.3
        # Gamme de GT cible de 5k à 150k
        gts_target = list(range(5000, 150001, 2500))
        c_tm, c_nwm = [], []
        for g_t in gts_target:
            # VG dérivé du ratio du navire de référence
            vg_t = g_t / ratio_gt_vg
            c_tm.append(calc_pilotage_tm(vg_t, "Entrée") + calc_pilotage_tm(vg_t, "Sortie"))
            c_nwm.append(calc_pilotage_nwm_entree_sortie(g_t) * 2)
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=gts_target, y=c_tm, name="Tanger Med (barème VG)", line=dict(color=TM_C, width=3)))
        fig.add_trace(go.Scatter(x=gts_target, y=c_nwm, name="NWM (formule GT)", line=dict(color=NWM_C, width=3, dash="dash")))
        # Marqueur pour le navire actuel
        pil_now_tm = calc_pilotage_tm(vg, "Entrée") + calc_pilotage_tm(vg, "Sortie")
        pil_now_nwm = calc_pilotage_nwm_entree_sortie(gt) * 2
        fig.add_trace(go.Scatter(x=[gt, gt], y=[pil_now_tm, pil_now_nwm],
            mode="markers", marker=dict(size=12, symbol="diamond"),
            name=f"Navire actuel (GT={gt:,})", showlegend=True))
        fig.update_layout(xaxis_title="GT (axe de référence)", yaxis_title="Pilotage Entrée+Sortie (€)", height=420,
            annotations=[dict(x=gt, y=max(pil_now_tm, pil_now_nwm)*1.08,
                text=f"Votre navire<br>GT={gt:,} / VG={vg:,.0f}m³", showarrow=False, font=dict(size=11))])
        st.plotly_chart(fig, use_container_width=True)

        # Trouver le point d'inflexion tranche 1 → tranche 2
        vg_seuil = 180000
        gt_seuil = vg_seuil * ratio_gt_vg
        pil_t1 = calc_pilotage_tm(vg_seuil, "Entrée") + calc_pilotage_tm(vg_seuil, "Sortie")
        pil_t2 = calc_pilotage_tm(vg_seuil + 1, "Entrée") + calc_pilotage_tm(vg_seuil + 1, "Sortie")
        if abs(pil_t1 - pil_t2) > 200:
            st.warning(f"""
            ⚠️ **Discontinuité détectée dans le barème TM** à VG ≈ 180 000 m³ (GT ≈ {gt_seuil:,.0f} pour ce type de navire).
            La 2ème tranche du cahier tarifaire TM redémarre à un niveau inférieur:
            - Fin tranche 1 (VG=180k): Entrée+Sortie = **{pil_t1:,.0f}€**
            - Début tranche 2 (VG=180k+1): Entrée+Sortie = **{pil_t2:,.0f}€**
            - Écart: **{pil_t1 - pil_t2:,.0f}€** → Avantage significatif pour les très grands navires à TM
            """)

        st.info(f"**Ratio de référence:** GT/VG = {ratio_gt_vg:.4f} (basé sur votre navire: GT={gt:,} / VG={vg:,.0f}m³). "
                f"TM utilise le VG (m³), NWM utilise les GTs — les deux assiettes sont liées par les proportions de votre navire. "
                f"Ce ratio varie selon le type de navire: un porte-conteneurs aura un ratio différent d'un tanker ou d'un ferry.")

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
# TAB 10 — ALGECIRAS
# ═════════════════════════════════════════════════════════════════════════════
with tabs[10]:
    st.header("🇪🇸 Port d'Algeciras — Baie d'Algésiras")
    st.info("""**Système espagnol:** Taxes publiques (tasas) fixées par le Décret Royal 2/2011.
    Le port authority perçoit les taxes T0-T6. Les services (remorquage, lamanage, manutention) sont des marchés privés avec tarifs négociés — non inclus ici.""")

    alg_tabs = st.tabs(["🚢 T1 Navire","🧭 Pilotage","📦 T3 Marchandise","👤 T2 Passagers","📊 T6 Stockage","⚡ Utilities","🗑️ Déchets"])

    # --- T1 Taxe Navire ---
    with alg_tabs[0]:
        st.subheader("T1 — Taxe du Navire")
        st.caption(f"T1 = GT/100 × Heures × {ALG_T1_BASE_B} × Coef.utilisation × Réduction fréquence × Réduction spéciale × Bonification")

        c1, c2, c3 = st.columns(3)
        with c1:
            alg_reduc_spec = st.selectbox("Réduction spéciale", list(ALG_T1_REDUCTIONS_SPEC.keys()), index=len(ALG_T1_REDUCTIONS_SPEC)-1, key="alg_rs")
        with c2:
            alg_bonif = st.selectbox("Bonification", list(ALG_T1_BONIFICATIONS.keys()), index=len(ALG_T1_BONIFICATIONS)-1, key="alg_bo")
        with c3:
            alg_base_type = st.radio("Montant base", ["B = 1,43 (général)", "S = 1,20 (courte distance)"], key="alg_bt")

        base_sel = ALG_T1_BASE_B if "1,43" in alg_base_type else ALG_T1_BASE_S
        coef_u = ALG_T1_COEF_UTILISATION[alg_concession]
        freq_r = ALG_T1_REDUCTION_FREQUENCE[alg_freq]
        spec_r = ALG_T1_REDUCTIONS_SPEC[alg_reduc_spec]
        bonif_r = ALG_T1_BONIFICATIONS[alg_bonif]

        t1_val = calc_alg_t1(gt, sejour_h, coef_util=coef_u, reduc_freq=freq_r,
                             reduc_spec=spec_r, bonif=bonif_r, base=base_sel, regulier=alg_regulier)

        # Valeur sans réductions pour montrer l'impact
        t1_brut = calc_alg_t1(gt, sejour_h, coef_util=coef_u, base=base_sel)

        c1, c2, c3 = st.columns(3)
        c1.metric("T1 Brut (sans réductions)", fmt(t1_brut))
        c2.metric("T1 Net (avec réductions)", fmt(t1_val), delta=f"{(t1_val/t1_brut-1)*100:.0f}%" if t1_brut > 0 else "")
        freq_eff = freq_r - 0.05 if alg_regulier else freq_r
        c3.metric("Coefficient cumulé", f"{coef_u * freq_eff * spec_r * bonif_r:.4f}")

        # Comparaison avec droits de port TM & NWM
        st.divider()
        st.subheader("Comparaison avec les Droits de Port TM & NWM")
        st.caption("Les droits de port marocains (nautique + port + stationnement) sont l'équivalent le plus proche de la T1 espagnole")

        tt_alg_tm = st.selectbox("Terminal TM", list(DROITS_PORT_NAVIRES_TM.keys()), key="alg_ttm")
        tt_alg_nwm = st.selectbox("Terminal NWM", list(DROITS_PORT_NAVIRES_NWM.keys()), key="alg_tnwm")
        r_tm_a = DROITS_PORT_NAVIRES_TM[tt_alg_tm]
        r_nwm_a = DROITS_PORT_NAVIRES_NWM[tt_alg_nwm]
        dp_tm = vg * r_tm_a["nautique"] + vg * r_tm_a["port"] + calc_stationnement(vg, r_tm_a["stationnement"], sejour_h)
        dp_nwm = vg * r_nwm_a["nautique"] + vg * r_nwm_a["port"] + calc_stationnement(vg, r_nwm_a["stationnement"], sejour_h)

        c1, c2, c3 = st.columns(3)
        c1.metric("🔵 TM Droits Port", fmt(dp_tm))
        c2.metric("🔴 NWM Droits Port", fmt(dp_nwm))
        c3.metric("🟢 Algeciras T1 Net", fmt(t1_val))
        st.plotly_chart(bar3("", dp_tm, dp_nwm, t1_val, "Taxe Navire / Droits de Port"), use_container_width=True)

        # Sensibilité par fréquence
        with st.expander("📈 Impact de la fréquence d'escale sur la T1"):
            freq_labels = list(ALG_T1_REDUCTION_FREQUENCE.keys())
            freq_vals = []
            for f_lab in freq_labels:
                f_coef = ALG_T1_REDUCTION_FREQUENCE[f_lab]
                v = calc_alg_t1(gt, sejour_h, coef_util=coef_u, reduc_freq=f_coef,
                                reduc_spec=spec_r, bonif=bonif_r, base=base_sel, regulier=alg_regulier)
                freq_vals.append(v)
            fig = go.Figure()
            fig.add_trace(go.Bar(x=freq_labels, y=freq_vals, marker_color=ALG_C, text=[fmt(v) for v in freq_vals], textposition="outside"))
            fig.add_hline(y=dp_tm, line_dash="dash", line_color=TM_C, annotation_text=f"TM: {fmt(dp_tm)}")
            fig.add_hline(y=dp_nwm, line_dash="dash", line_color=NWM_C, annotation_text=f"NWM: {fmt(dp_nwm)}")
            fig.update_layout(height=400, yaxis_title="T1 Algeciras (€)", xaxis_title="Fréquence d'escale")
            st.plotly_chart(fig, use_container_width=True)
            st.caption("Les lignes pointillées montrent les droits de port TM et NWM pour comparaison. "
                       "Algeciras offre des réductions massives pour les lignes à haute fréquence (>365 escales → 35% du tarif de base).")

    # --- Pilotage ---
    with alg_tabs[1]:
        st.subheader("Pilotage Algeciras")
        st.caption("Formule linéaire: Partie fixe + Partie variable × GT. Tarif T+2 applicable 2024.")

        c1, c2 = st.columns(2)
        with c1:
            alg_pil_tranche = st.selectbox("Tranche tarifaire", list(ALG_PILOTAGE_TARIFS.keys()), index=0, key="alg_pt")
        with c2:
            alg_pil_maj = st.selectbox("Majoration", list(ALG_PILOTAGE_MAJORATIONS.keys()), index=len(ALG_PILOTAGE_MAJORATIONS)-1, key="alg_pm")

        maj_val = ALG_PILOTAGE_MAJORATIONS[alg_pil_maj]
        if isinstance(maj_val, (int, float)) and alg_pil_maj != ">90 min (€/h suppl.)":
            pil_e_alg = calc_alg_pilotage(gt, "Entrée", alg_pil_tranche, maj_val)
            pil_s_alg = calc_alg_pilotage(gt, "Sortie", alg_pil_tranche, maj_val)
            pil_mi_alg = calc_alg_pilotage(gt, "Mouvement intérieur", alg_pil_tranche, maj_val)
        else:
            pil_e_alg = calc_alg_pilotage(gt, "Entrée", alg_pil_tranche)
            pil_s_alg = calc_alg_pilotage(gt, "Sortie", alg_pil_tranche)
            pil_mi_alg = calc_alg_pilotage(gt, "Mouvement intérieur", alg_pil_tranche)

        pil_es_alg = pil_e_alg + pil_s_alg
        pil_tm = calc_pilotage_tm(vg, "Entrée") + calc_pilotage_tm(vg, "Sortie")
        pil_nwm = calc_pilotage_nwm_entree_sortie(gt) * 2

        c1, c2, c3 = st.columns(3)
        c1.metric("Entrée", fmt(pil_e_alg))
        c2.metric("Sortie", fmt(pil_s_alg))
        c3.metric("Mouv. intérieur", fmt(pil_mi_alg))

        st.divider()
        st.subheader("Comparaison Pilotage E+S (3 ports)")
        c1, c2, c3 = st.columns(3)
        c1.metric("🔵 TM (barème VG)", fmt(pil_tm))
        c2.metric("🔴 NWM (formule GT)", fmt(pil_nwm))
        c3.metric("🟢 Algeciras (fixe+var×GT)", fmt(pil_es_alg))
        st.plotly_chart(bar3("", pil_tm, pil_nwm, pil_es_alg, "Pilotage Entrée + Sortie"), use_container_width=True)

        # Courbe comparative par taille navire
        with st.expander("📈 Courbe pilotage E+S par taille navire (3 ports)"):
            ratio_gt_vg = gt / vg if vg > 0 else 0.3
            gts_pil = list(range(5000, 150001, 2500))
            c_tm_p, c_nwm_p, c_alg_p = [], [], []
            for g_t in gts_pil:
                vg_t = g_t / ratio_gt_vg
                c_tm_p.append(calc_pilotage_tm(vg_t, "Entrée") + calc_pilotage_tm(vg_t, "Sortie"))
                c_nwm_p.append(calc_pilotage_nwm_entree_sortie(g_t) * 2)
                c_alg_p.append(calc_alg_pilotage(g_t, "Entrée", alg_pil_tranche) + calc_alg_pilotage(g_t, "Sortie", alg_pil_tranche))
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=gts_pil, y=c_tm_p, name="Tanger Med (VG)", line=dict(color=TM_C, width=3)))
            fig.add_trace(go.Scatter(x=gts_pil, y=c_nwm_p, name="NWM (GT)", line=dict(color=NWM_C, width=3, dash="dash")))
            fig.add_trace(go.Scatter(x=gts_pil, y=c_alg_p, name="Algeciras (fixe+var×GT)", line=dict(color=ALG_C, width=3, dash="dot")))
            fig.add_trace(go.Scatter(x=[gt]*3, y=[pil_tm, pil_nwm, pil_es_alg],
                mode="markers", marker=dict(size=12, symbol="diamond"), name=f"Navire actuel (GT={gt:,})"))
            fig.update_layout(xaxis_title="GT", yaxis_title="Pilotage E+S (€)", height=450)
            st.plotly_chart(fig, use_container_width=True)

        # Détail barème
        with st.expander("📋 Barème complet Algeciras"):
            rows = []
            for tr, mouvs in ALG_PILOTAGE_TARIFS.items():
                for m, vals in mouvs.items():
                    exemple = vals["fixe"] + vals["variable"] * gt
                    rows.append({"Tranche": tr, "Mouvement": m, "Fixe (€)": vals["fixe"], "Variable (€/GT)": vals["variable"],
                                 f"Exemple GT={gt:,}": f"{exemple:,.2f}€"})
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    # --- T3 Marchandise ---
    with alg_tabs[2]:
        st.subheader("T3 — Taxe de la Marchandise")
        st.caption(f"Régime simplifié: T3 = Unité × Montant base ({ALG_T3_BASE_M}€) × Coef.équipement × Réductions × Bonifications")

        c1, c2 = st.columns(2)
        with c1:
            alg_t3_type = st.selectbox("Type équipement", list(ALG_T3_SIMPLIFIE.keys()), key="alg_t3t")
            nb_equip = st.number_input("Nombre d'unités", 1, 50000, 500, 50, key="alg_t3n")
        with c2:
            alg_t3_reduc = st.selectbox("Réduction", list(ALG_T3_REDUCTIONS.keys()), key="alg_t3r")
            alg_t3_bonif_ctn = st.checkbox("Bonification conteneurs I/E (×0.70)", key="alg_t3b")

        tarif_unit = ALG_T3_SIMPLIFIE[alg_t3_type]["total"]
        reduc_t3 = ALG_T3_REDUCTIONS[alg_t3_reduc]
        bonif_t3 = ALG_T3_BONIF_CTN if alg_t3_bonif_ctn else 1.00
        t3_total = tarif_unit * nb_equip * reduc_t3 * bonif_t3

        c1, c2, c3 = st.columns(3)
        c1.metric("Tarif unitaire brut", fmt(tarif_unit))
        c2.metric(f"Total ({nb_equip} unités)", fmt(t3_total))
        c3.metric("Coef. réduction × bonif", f"{reduc_t3 * bonif_t3:.2f}")

        # Comparaison avec conteneurs TM/NWM
        if "CTN" in alg_t3_type:
            st.divider()
            st.subheader("Comparaison droits sur marchandise CTN")
            # Mapping: CTN ≤20' → TEU, CTN >20' → 2 TEU
            is_20 = "≤20" in alg_t3_type
            evp_eq = nb_equip if is_20 else nb_equip * 2

            if "chargé" in alg_t3_type:
                op_map = st.selectbox("Type opération TM/NWM", list(CONTENEURS_TM.keys()), key="alg_opm")
                tm_ctn = CONTENEURS_TM[op_map] * evp_eq
                nwm_ctn = CONTENEURS_NWM[op_map] * evp_eq
            else:
                tm_ctn = 0
                nwm_ctn = 0
                st.info("Pas de taxe conteneurs vides dans les cahiers marocains (hors manutention)")

            if tm_ctn > 0:
                c1, c2, c3 = st.columns(3)
                c1.metric(f"🔵 TM ({evp_eq} EVP)", fmt(tm_ctn))
                c2.metric(f"🔴 NWM ({evp_eq} EVP)", fmt(nwm_ctn))
                c3.metric(f"🟢 Algeciras ({nb_equip} u.)", fmt(t3_total))
                st.plotly_chart(bar3("", tm_ctn, nwm_ctn, t3_total, "Taxe marchandise / conteneurs"), use_container_width=True)

        # Tableau complet
        with st.expander("📋 Grille complète régime simplifié"):
            rows = []
            for k, v in ALG_T3_SIMPLIFIE.items():
                rows.append({"Équipement": k, "Coefficient": v["coef"], "Tarif (€/u)": f"{v['total']:.2f}"})
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    # --- T2 Passagers ---
    with alg_tabs[3]:
        st.subheader("T2 — Taxe des Passagers")
        st.caption(f"T2 = Unités × Montant base ({ALG_T2_BASE_P}€) × Coef.utilisation × Réductions")

        rows = []
        for k, v in ALG_T2.items():
            rows.append({"Concept": k, "Coefficient": v["coef"], "Tarif (€/u)": f"{v['total']:.2f}"})
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

        # Comparaison passagers
        st.divider()
        st.subheader("Comparaison passagers/véhicules (3 ports)")
        comp_pax = {
            "Passager": {"TM (Cat A)": 3.00, "TM (Cat C)": 3.90, "NWM": 3.00, "Algeciras Schengen": 2.42, "Algeciras Non-Sch.": 3.23},
            "Véhicule 2 roues": {"TM": 3.00, "NWM": 3.00, "Algeciras": 4.20},
            "Automobile": {"TM (Cat A)": 6.00, "TM (Cat C)": 7.90, "NWM": 6.00, "Algeciras ≤5m": 9.37},
            "Bus": {"TM": 35.00, "NWM": 35.00, "Algeciras": 50.39},
        }
        st.dataframe(pd.DataFrame(comp_pax).T, use_container_width=True)

    # --- T6 Stockage ---
    with alg_tabs[4]:
        st.subheader("T6 — Taxe d'Utilisation Zone de Transit")
        st.caption("Stockage temporaire des marchandises. Franchise: 4h (roulant), 48h (autres)")

        c1, c2 = st.columns(2)
        with c1:
            surf_alg = st.number_input("Surface (m²)", 1.0, 10000.0, 33.2, 0.5, key="alg_surf", help="CTN 20'≈14.8m², 40'≈29.7m²")
        with c2:
            jours_alg = st.number_input("Jours de stockage", 1, 365, 10, 1, key="alg_jrs")

        t6_val = calc_alg_t6(surf_alg, jours_alg)
        st.metric(f"T6 — {surf_alg}m² × {jours_alg} jours", fmt(t6_val))

        rows = []
        for k, v in ALG_T6_COEF.items():
            rows.append({"Période": k, "Coefficient": v["coef"], "Tarif (€/m²/j)": f"{v['total']:.3f}"})
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    # --- Utilities ---
    with alg_tabs[5]:
        st.subheader("Approvisionnements & Utilities")

        comp_util = {
            "Eau (€/m³)": {"TM": 1.235, "NWM": 1.235, "Algeciras (local)": 5.00, "Algeciras (autres)": 4.00},
            "Électricité BT (€/kWh)": {"TM": 0.1623, "NWM": 0.1623, "Algeciras": 0.1778},
            "Électricité MT (€/kWh)": {"TM": 0.1373, "NWM": 0.1373, "Algeciras HT": 0.0953},
            "Connexion élec. (€)": {"TM": 10.00, "NWM": 10.00, "Algeciras": 8.45},
        }
        st.dataframe(pd.DataFrame(comp_util).T, use_container_width=True)

        st.warning("⚠️ **Eau 4× plus chère à Algeciras** (5€/m³ vs 1,235€/m³ au Maroc). "
                   "L'électricité est comparable, voire moins chère en haute tension à Algeciras (0,0953€/kWh).")

    # --- Déchets ---
    with alg_tabs[6]:
        st.subheader("Taxe Déchets Navires")
        nb_pax_alg = st.number_input("Nombre passagers (0 = cargo)", 0, 10000, 0, key="alg_pax")
        dech_alg = calc_alg_dechets(gt, nb_pax_alg)
        st.metric(f"Taxe déchets (GT={gt:,})", fmt(dech_alg))
        st.caption("Cette taxe n'existe pas dans les cahiers tarifaires marocains (incluse dans d'autres postes ou gérée différemment).")

# ═════════════════════════════════════════════════════════════════════════════
# TAB 11 — COÛT TOTAL ESCALE (3 PORTS)
# ═════════════════════════════════════════════════════════════════════════════
with tabs[11]:
    st.header("💰 Simulation Coût Total d'Escale — 3 Ports")
    st.info(f"**Navire:** LOA={loa}m · Beam={beam}m · Te={draft}m · GT={gt:,} · VG={vg:,.0f}m³ | Séjour={sejour_h}h | {nb_rem} remorqueurs · {nb_mvt} mouvements")

    c1, c2, c3 = st.columns(3)
    with c1:
        tt_tm = st.selectbox("Terminal TM", list(DROITS_PORT_NAVIRES_TM.keys()), key="tot_tm")
    with c2:
        tt_nwm = st.selectbox("Terminal NWM", list(DROITS_PORT_NAVIRES_NWM.keys()), key="tot_nwm")
    with c3:
        evp_t = st.number_input("EVP", 0, 20000, 500, 50, key="evp_t")
        op_t = st.selectbox("Op. conteneurs", list(CONTENEURS_TM.keys()), key="op_t")

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

    # === CALCULS ALGECIRAS ===
    coef_u_tot = ALG_T1_COEF_UTILISATION[alg_concession]
    freq_r_tot = ALG_T1_REDUCTION_FREQUENCE[alg_freq]
    v_t1_alg = calc_alg_t1(gt, sejour_h, coef_util=coef_u_tot, reduc_freq=freq_r_tot, regulier=alg_regulier)
    v_pil_alg = calc_alg_pilotage(gt, "Entrée") + calc_alg_pilotage(gt, "Sortie")
    v_rem_alg = 0  # Non publié — service privé
    v_lam_alg = 0  # Non publié — service privé
    # T3 marchandise conteneurs
    if "Transshipment" in op_t or "transbordement" in op_t.lower():
        t3_reduc = 0.30  # transbordement accostés
        t3_bonif = 1.00
    else:
        t3_reduc = 1.00
        t3_bonif = ALG_T3_BONIF_CTN  # 0.70 pour CTN I/E
    # 20' = 1 TEU → 1 unité CTN≤20', 40' = 2 TEU → on suppose mix moyen
    alg_tarif_ctn = ALG_T3_SIMPLIFIE["CTN ≤20' chargé"]["total"] if evp_t > 0 else 0
    v_ctn_alg = alg_tarif_ctn * evp_t * t3_reduc * t3_bonif
    v_t0_alg = ALG_T0_TOTAL_GT * gt  # Aides navigation
    v_dech_alg = calc_alg_dechets(gt)

    labels = ["Taxe Navire / Droits Port", "Pilotage", "Remorquage*", "Lamanage*", "Marchandises CTN", "T0 Aides Nav. / Déchets"]
    vtm = [v_naut_tm + v_port_tm + v_stat_tm, v_pil_tm, v_rem_tm, v_lam_tm, v_ctn_tm, 0]
    vnwm = [v_naut_nwm + v_port_nwm + v_stat_nwm, v_pil_nwm, v_rem_nwm, v_lam_nwm, v_ctn_nwm, 0]
    valg = [v_t1_alg, v_pil_alg, v_rem_alg, v_lam_alg, v_ctn_alg, v_t0_alg + v_dech_alg]
    total_tm = sum(vtm)
    total_nwm = sum(vnwm)
    total_alg = sum(valg)

    c1, c2, c3 = st.columns(3)
    with c1:
        st.subheader(f"🔵 Tanger Med")
        st.metric("TOTAL", fmt(total_tm))
        for l, v in zip(labels, vtm):
            if v > 0: st.metric(l, fmt(v))
    with c2:
        st.subheader(f"🔴 NWM")
        st.metric("TOTAL", fmt(total_nwm))
        for l, v in zip(labels, vnwm):
            if v > 0: st.metric(l, fmt(v))
    with c3:
        st.subheader(f"🟢 Algeciras")
        st.metric("TOTAL", fmt(total_alg))
        for l, v in zip(labels, valg):
            if v > 0: st.metric(l, fmt(v))
        st.caption("*Remorquage & lamanage = services privés non publiés à Algeciras")

    mins = {"Tanger Med": total_tm, "NWM": total_nwm, "Algeciras": total_alg}
    best = min(mins, key=mins.get)
    worst = max(mins, key=mins.get)
    eco = mins[worst] - mins[best]
    st.success(f"### 💡 Port le moins cher: **{best}** ({fmt(mins[best])}) — Économie vs {worst}: {fmt(eco)}")
    st.warning("⚠️ **Comparaison partielle pour Algeciras:** les tarifs de remorquage et lamanage (services privés) ne sont pas inclus. "
               "Le coût réel sera plus élevé. Les réductions par fréquence d'escale ont un impact majeur sur le positionnement d'Algeciras.")

    st.plotly_chart(stacked_bar3(labels, vtm, vnwm, valg), use_container_width=True)

    # Tableau récap
    recap = []
    for l, a, b, c in zip(labels, vtm, vnwm, valg):
        recap.append({"Poste": l, "🔵 TM": fmt(a), "🔴 NWM": fmt(b), "🟢 Algeciras": fmt(c),
                       "Δ ALG vs TM": pct(a, c) if a > 0 else "—", "Δ NWM vs TM": pct(a, b) if a > 0 else "—"})
    recap.append({"Poste": "🔴 TOTAL", "🔵 TM": fmt(total_tm), "🔴 NWM": fmt(total_nwm), "🟢 Algeciras": fmt(total_alg),
                   "Δ ALG vs TM": pct(total_tm, total_alg), "Δ NWM vs TM": pct(total_tm, total_nwm)})
    st.dataframe(pd.DataFrame(recap), use_container_width=True, hide_index=True)

    # Sensibilité EVP
    with st.expander("📈 Sensibilité par volume EVP (3 ports)"):
        evps = [100, 500, 1000, 2000, 5000, 10000]
        s_tm, s_nwm, s_alg = [], [], []
        base_tm_t = sum(vtm[:4])  # navire + pilotage + rem + lam
        base_nwm_t = sum(vnwm[:4])
        base_alg_t = valg[0] + valg[1] + valg[5]  # T1 + pilotage + T0/déchets
        for e in evps:
            s_tm.append(base_tm_t + CONTENEURS_TM[op_t] * e)
            s_nwm.append(base_nwm_t + CONTENEURS_NWM[op_t] * e)
            s_alg.append(base_alg_t + alg_tarif_ctn * e * t3_reduc * t3_bonif)
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=evps, y=s_tm, name="Tanger Med", line=dict(color=TM_C, width=3)))
        fig.add_trace(go.Scatter(x=evps, y=s_nwm, name="NWM", line=dict(color=NWM_C, width=3, dash="dash")))
        fig.add_trace(go.Scatter(x=evps, y=s_alg, name="Algeciras", line=dict(color=ALG_C, width=3, dash="dot")))
        fig.update_layout(xaxis_title="EVP", yaxis_title="Coût total escale (€)", height=420)
        st.plotly_chart(fig, use_container_width=True)

# ─── FOOTER ──────────────────────────────────────────────────────────────────
st.divider()
st.caption("📌 Simulateur basé sur les cahiers tarifaires 2025 (TM & NWM) et résolution tarifaire 2024 (Algeciras) | Données extraites fév. 2026 | Tous tarifs HT")
