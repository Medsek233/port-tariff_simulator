"""
tarifs_data.py — Données tarifaires complètes extraites des cahiers tarifaires 2025
Tanger Med Port Authority (TMPA) et Nador West Med (NWM)

Sources:
  - cahiertarifaire_Tanger_Med.pdf (51 pages)
  - Cahier_Tarifaire_NWM.docx (~10 pages)
  - Parametres_Facturables_TM2025_Complet.xlsx
"""
import math

# ═══════════════════════════════════════════════════════════════════════════════
# 1. DROITS DE PORT SUR NAVIRES (€/m³ de Volume Géométrique)
# ═══════════════════════════════════════════════════════════════════════════════

DROITS_PORT_NAVIRES_TM = {
    "Terminaux à Conteneurs (TC1-TC4)": {"nautique": 0.0054, "port": 0.0261, "stationnement": 0.0551},
    "Terminal Vrac & MD":               {"nautique": 0.0056, "port": 0.0271, "stationnement": 0.0561},
    "Terminal Véhicules (TVCU)":        {"nautique": 0.0056, "port": 0.0271, "stationnement": 0.0561},
    "Terminal Hydrocarbures":           {"nautique": 0.0056, "port": 0.0271, "stationnement": 0.0561},
    "Navires GPL":                      {"nautique": 0.0066, "port": 0.0282, "stationnement": 0.0663},
}

DROITS_PORT_NAVIRES_NWM = {
    "Terminal à Conteneurs":     {"nautique": 0.005,  "port": 0.02405, "stationnement": 0.053},
    "Terminal Marchandises Div": {"nautique": 0.005,  "port": 0.0259,  "stationnement": 0.054},
    "Terminal Hydrocarbures":    {"nautique": 0.006,  "port": 0.026,   "stationnement": 0.052},
    "Terminal GAZ":              {"nautique": 0.007,  "port": 0.027,   "stationnement": 0.062},
}

# Règles stationnement TM: franchise 24h, 1/3 si ≤8h après franchise, plein tarif/24h si >8h
# Rade TM: 50% dès 6ème jour | Rade NWM: 50% dès 5ème jour
# TM: exonération soutage 48h à l'ancre

# ═══════════════════════════════════════════════════════════════════════════════
# 1bis. NAVIRES ROULIERS — forfaits horaires
# ═══════════════════════════════════════════════════════════════════════════════

ROULIERS_TM = {
    "Cat A – Détroit (ferry >1 escale/j, ≤2h30)": {"forfait": 458,  "duree_h": 2.5,  "suppl_30min": 204},
    "Cat B – Pur RoRo (≤6h30)":                   {"forfait": 1289, "duree_h": 6.5,  "suppl_30min": 204},
    "Cat C – Au-delà du détroit (≤8h30)":          {"forfait": 1951, "duree_h": 8.5,  "suppl_30min": 204},
}
ROULIERS_TM_NAUTIQUE = 0.0054  # €/m³

ROULIERS_NWM = {
    "Forfait unique (≤8h)": {"forfait": 1700, "duree_h": 8.0, "suppl_30min": 200},
}
ROULIERS_NWM_NAUTIQUE = 0.005  # €/m³

# ═══════════════════════════════════════════════════════════════════════════════
# 2. PILOTAGE
# ═══════════════════════════════════════════════════════════════════════════════

# --- TM: barème par tranche de Volume Géométrique (m³), 4 types de mouvement ---
PILOTAGE_TM = {
    "Entrée": {
        "tranches": [
            (0, 40000, 317.0), (40001, 50000, 342.4), (50001, 60000, 418.5),
            (60001, 70000, 472.4), (70001, 80000, 516.9), (80001, 90000, 608.8),
            (90001, 100000, 827.1), (100001, 110000, 1125.7),
        ],
        "supplement_10k": 191.4,  # par 10 000 m³ > 110 000
        # 2ème tranche > 180 000 m³
        "tranches2": [
            (180001, 190000, 1444.8), (190001, 200000, 1521.3), (200001, 210000, 1597.8),
            (210001, 220000, 1674.2), (220001, 230000, 1750.7), (230001, 240000, 1827.2),
            (240001, 250000, 1903.7), (250001, 260000, 1980.1),
        ],
        "supplement2_10k": 76.5,
    },
    "Sortie": {
        "tranches": [
            (0, 40000, 215.7), (40001, 50000, 228.3), (50001, 60000, 279.2),
            (60001, 70000, 348.2), (70001, 80000, 379.0), (80001, 90000, 448.0),
            (90001, 100000, 551.4), (100001, 110000, 884.5),
        ],
        "supplement_10k": 90.1,
        "tranches2": [
            (180001, 190000, 1198.3), (190001, 200000, 1266.3), (200001, 210000, 1334.3),
            (210001, 220000, 1402.3), (220001, 230000, 1470.2), (230001, 240000, 1538.2),
            (240001, 250000, 1606.2), (250001, 260000, 1674.2),
        ],
        "supplement2_10k": 68.0,
    },
    "Changement de Quai": {
        "tranches": [
            (0, 40000, 253.6), (40001, 50000, 291.8), (50001, 60000, 329.6),
            (60001, 70000, 372.9), (70001, 80000, 402.0), (80001, 90000, 459.5),
            (90001, 100000, 516.9), (100001, 110000, 574.3),
        ],
        "supplement_10k": 56.3,
        "tranches2": [
            (180001, 190000, 764.9), (190001, 200000, 807.4), (200001, 210000, 849.9),
            (210001, 220000, 892.3), (220001, 230000, 934.8), (230001, 240000, 977.3),
            (240001, 250000, 1019.8), (250001, 260000, 1062.3),
        ],
        "supplement2_10k": 42.5,
    },
    "Changement de Bassin": {
        "tranches": [
            (0, 40000, 532.7), (40001, 50000, 570.5), (50001, 60000, 697.5),
            (60001, 70000, 820.6), (70001, 80000, 896.0), (80001, 90000, 1056.8),
            (90001, 100000, 1378.4), (100001, 110000, 2010.2),
        ],
        "supplement_10k": 191.4,
        "tranches2": [
            (180001, 190000, 2643.1), (190001, 200000, 2787.6), (200001, 210000, 2932.0),
            (210001, 220000, 3076.5), (220001, 230000, 3220.9), (230001, 240000, 3365.4),
            (240001, 250000, 3509.8), (250001, 260000, 3654.3),
        ],
        "supplement2_10k": 144.4,
    },
}

# TM majorations pilotage
# - Durée > 2h: +50% par heure entamée supplémentaire
# - Retard confirmé: +50%
# - Retard >20min après embarquement pilote: +100%
# - Navire désemparé: +100%
# - PEC: exonération totale (sauf RoRo/Night ferry: 50% sortie uniquement)
# - Vedette: 100€/h intérieur, 175€/h rade (min 300€)

def calc_pilotage_tm(volume_m3, mouvement):
    """Calcule le tarif pilotage TM pour un mouvement donné."""
    data = PILOTAGE_TM[mouvement]
    # Tranche 1 (0 à 110 000)
    if volume_m3 <= 110000:
        for lo, hi, tarif in data["tranches"]:
            if lo <= volume_m3 <= hi:
                return tarif
        return data["tranches"][0][2]
    # Entre 110 001 et 180 000
    elif volume_m3 <= 180000:
        base = data["tranches"][-1][2]
        extra = math.ceil((volume_m3 - 110000) / 10000)
        return base + data["supplement_10k"] * extra
    # Tranche 2 (> 180 000)
    else:
        for lo, hi, tarif in data.get("tranches2", []):
            if lo <= volume_m3 <= hi:
                return tarif
        if volume_m3 > 260000:
            base2 = data["tranches2"][-1][2] if data.get("tranches2") else 2000
            extra2 = math.ceil((volume_m3 - 260000) / 10000)
            return base2 + data.get("supplement2_10k", 76.5) * extra2
        return data["tranches2"][-1][2] if data.get("tranches2") else 2000


# --- NWM: formule linéaire basée sur GTs ---
def calc_pilotage_nwm_entree_sortie(gts):
    """Pilotage NWM: 0.022641381 × GTs + 21.26, min 261.1€"""
    return max(0.022641381 * gts + 21.25659786, 261.1)

def calc_pilotage_nwm_chg_quai(gts):
    """Pilotage NWM changement quai: 0.011521001 × GTs + 145.24, min 261.1€"""
    return max(0.011521001 * gts + 145.23524, 261.1)

# NWM majorations: navire désemparé = tarif doublé (×2)
# NWM exonérations: navires de guerre, pêche marocains, remorqueurs marocains,
#   servitude, déhalage <100m sans remorqueur

# ═══════════════════════════════════════════════════════════════════════════════
# 3. REMORQUAGE (€ par remorqueur par mouvement)
# ═══════════════════════════════════════════════════════════════════════════════

REMORQUAGE_TM = [
    (0, 1000, 339.2), (1001, 2000, 410.8), (2001, 3000, 713.4),
    (3001, 5000, 773.7), (5001, 7000, 979.8), (7001, 9000, 1100.1),
    (9001, 12000, 1196.9), (12001, 15000, 1245.6), (15001, 18000, 1498.1),
    (18001, 22000, 1815.4), (22001, 26000, 1860.8), (26001, 30000, 2127.0),
    (30001, 35000, 2247.6), (35001, 40000, 2440.8), (40001, 45000, 2513.7),
    (45001, 50000, 2766.1),
]
REMORQUAGE_TM_SUP = 158.5  # par 5 000 GT > 50 000

# TM majorations: +25% sans propulsion, déhalage 25% du tarif, attente/annul 20%
# Mise dispo remorqueur: 1-2h=553.6, 3-12h=532.8, 13h+=512.0 €/h
# Veille sécurité pétrolier: 339.9 €/h/remorqueur

REMORQUAGE_NWM = [
    (0, 2000, 375.5), (2001, 4000, 720.5), (4001, 7000, 870.0),
    (7001, 10000, 1030.0), (10001, 15000, 1180.0), (15001, 20000, 1490.0),
    (20001, 25000, 1785.0), (25001, 30000, 1925.0), (30001, 35000, 2150.0),
    (35001, 40000, 2350.0), (40001, 50000, 2570.0),
]
REMORQUAGE_NWM_SUP = 150.0  # par 5 000 GT > 50 000

# NWM majorations: +25% sans propulsion, déhalage 25% du tarif
# Veille sécurité pétrolier: 330 €/h/remorqueur

def calc_remorquage(gt, bareme, supplement, seuil=50000):
    """Lookup remorquage par tranche GT."""
    for lo, hi, tarif in bareme:
        if lo <= gt <= hi:
            return tarif
    if gt > seuil:
        base = bareme[-1][2]
        extra = math.ceil((gt - seuil) / 5000)
        return base + supplement * extra
    return bareme[0][2]


# ═══════════════════════════════════════════════════════════════════════════════
# 4. LAMANAGE
# ═══════════════════════════════════════════════════════════════════════════════

# TM: basé sur LOA (mètres), min 80€
LAMANAGE_TM = {
    "Cat A – Ferry >1 escale/jour": {"tarif_ml": 0.5798, "min": 80.0, "duree_max_h": 1},
    "Cat B&C – Autres navires":     {"tarif_ml": 1.1596, "min": 80.0, "duree_max_h": 2},
}
# TM: supplément durée +30% par heure entamée au-delà de la durée max
# TM: lamanage TC1-TC4 NON mentionné dans le cahier (convention séparée)

# NWM: formule linéaire basée sur GTs
def calc_lamanage_nwm(gts):
    """Lamanage NWM: 0.0108104 × GTs + 6.68"""
    return 0.0108104 * gts + 6.68


# ═══════════════════════════════════════════════════════════════════════════════
# 5. DROITS DE PORT SUR MARCHANDISES — CONTENEURS
# ═══════════════════════════════════════════════════════════════════════════════

CONTENEURS_TM = {"Transbordement": 0.583, "Import/Export": 38.63, "Cabotage": 10.92}
CONTENEURS_NWM = {"Transbordement": 0.55, "Import/Export": 38.25, "Cabotage": 10.65}
# +50% marchandises dangereuses pour les deux ports

# ═══════════════════════════════════════════════════════════════════════════════
# 6. MANUTENTION CONTENEURS — TM uniquement (tarifs max publics)
# ═══════════════════════════════════════════════════════════════════════════════

MANUTENTION_CTN_TM = {
    "TC1": {"20_bord_quai": 61.31, "40_bord_quai": 69.63, "20_terre": 17.87, "40_terre": 17.87, "pesage": 19.72},
    "TC2": {"20_bord_quai": 61.92, "40_bord_quai": 70.32, "20_terre": 18.05, "40_terre": 18.05, "pesage": 19.16},
    "TC3": {"20_bord_quai": 75.41, "40_bord_quai": 85.64, "20_terre": 21.98, "40_terre": 21.98, "pesage": 23.28},
    "TC4": {"20_bord_quai": 61.92, "40_bord_quai": 70.32, "20_terre": 18.05, "40_terre": 18.05, "pesage": 19.14},
}

# ═══════════════════════════════════════════════════════════════════════════════
# 7. STOCKAGE CONTENEURS — TM (€/jour)
# ═══════════════════════════════════════════════════════════════════════════════

STOCKAGE_CTN_TM = {
    "TC1": {
        "20' plein sec":  {"franchise": 2, "j3_7": 1.23, "j8+": 3.33},
        "40' plein sec":  {"franchise": 2, "j3_7": 2.46, "j8+": 6.65},
        "Frigo":          {"franchise": 2, "j3_7": 2.46, "j8+": 6.65},
        "Vide":           {"franchise": 2, "j3_7": 0.92, "j8+": 2.46},
    },
    "TC2": {
        "20' plein sec":  {"franchise": 2, "j3_7": 1.24, "j8+": 3.36},
        "40' plein sec":  {"franchise": 2, "j3_7": 2.49, "j8+": 6.72},
        "Frigo":          {"franchise": 2, "j3_7": 2.49, "j8+": 6.72},
        "Vide":           {"franchise": 2, "j3_7": 0.93, "j8+": 2.49},
    },
    "TC3": {
        "20' plein sec":  {"franchise": 2, "j3_7": 1.52, "j8+": 4.09},
        "40' plein sec":  {"franchise": 2, "j3_7": 3.03, "j8+": 8.19},
        "Frigo":          {"franchise": 2, "j3_7": 3.03, "j8+": 8.19},
        "Vide":           {"franchise": 2, "j3_7": 1.14, "j8+": 3.03},
    },
    "TC4": {
        "20' plein sec":  {"franchise": 2, "j3_7": 1.16, "j8+": 3.13},
        "40' plein sec":  {"franchise": 2, "j3_7": 2.32, "j8+": 6.27},
        "Frigo":          {"franchise": 2, "j3_7": 2.32, "j8+": 6.27},
        "Vide":           {"franchise": 2, "j3_7": 0.87, "j8+": 2.32},
    },
}
# NWM: AUCUN tarif de stockage conteneur publié ⚠️

# Terminal Ferroviaire TM: franchise 3j, j4-7: 1€/j, j8+: 3€/j

# ═══════════════════════════════════════════════════════════════════════════════
# 8. MARCHANDISES DIVERSES (€/T sauf exceptions)
# ═══════════════════════════════════════════════════════════════════════════════

MARCHANDISES_DIV_TM = {
    "Colis Lourds":               1.59,
    "Bobines de tôle":            1.59,
    "Marchandises en big bags":   0.86,
    "Palettisées et autres":      0.86,
    "Bois (€/m³)":                0.63,
    "Ferraille":                  1.59,
    "Verre en caisse":            0.86,
    "Céréales":                   1.06,
    "Autres Vracs":               0.73,
    "Conteneur via MD (€/EVP)":   38.64,
}

MARCHANDISES_DIV_NWM = {
    "Colis Lourds":               1.50,
    "Bobines de tôle":            1.50,
    "Marchandises en big bags":   0.82,
    "Palettisées et autres":      0.82,
    "Bois (€/m³)":                0.65,
    "Ferraille":                  1.53,
    "Verre en caisse":            0.84,
    "Céréales":                   0.75,
    "Charbon":                    0.285,
    "Autres Vracs":               1.23,
    "Conteneur via MD (€/EVP)":   38.25,
}

# ═══════════════════════════════════════════════════════════════════════════════
# 9. HYDROCARBURES
# ═══════════════════════════════════════════════════════════════════════════════

HYDROCARBURES_NWM = {
    "Produits blancs (diesel, kérosène, essence, lubrifiants)": {
        "Transbordement": 1.01, "Import/Export": 1.54, "Cabotage": 0.83,
    },
    "Produits noirs (fuel lourd, bitume)": {
        "Transbordement": 0.49, "Import/Export": 0.62, "Cabotage": 0.52,
    },
}
# TM: pas de détail comparable publié

# ═══════════════════════════════════════════════════════════════════════════════
# 10. ROULIER — MARCHANDISES
# ═══════════════════════════════════════════════════════════════════════════════

MARCHANDISES_ROULIER_TM = {
    "1.1 Remorque/ensemble routier plein":       {"Import": 195, "Export": 154},
    "1.2 Camion/fourgon ≤12m plein":             {"Import": 104, "Export": 88},
    "1.3 Véhicule/engin ≥18m (hors gabarit)":    {"Import": 306, "Export": 225},
    "1.4 Engin agricole et BTP":                  {"Import": 195, "Export": 195},
    "1.5 Ensemble routier/remorque vide":         {"Import": 62,  "Export": 62},
    "1.6 Plateau ou tracteur":                    {"Import": 32,  "Export": 32},
    "1.7 Camion/engin ≤12m vide":                 {"Import": 32,  "Export": 32},
}
# TM: Primeurs/produits frais mer/escargots export = 110€ forfait
# TM: MD +50%

MARCHANDISES_ROULIER_NWM_DH = {
    "Remorques pleines":                          1500.564,
    "Remorques vides":                            289.056,
    "Ensembles routiers pleins":                  1513.414,
    "Ensembles routiers vides":                   553.54,
    "Camion/fourgon ≤12m plein":                  807.662,
    "Camion/engin ≤12m vide":                     283.862,
    "Véhicule/engin ≥18m (hors gabarit)":         2212.382,
    "Engin agricole et BTP":                      1625.702,
}
# NWM: MD +50%

# ═══════════════════════════════════════════════════════════════════════════════
# 11. PASSAGERS ET VÉHICULES LÉGERS — TM
# ═══════════════════════════════════════════════════════════════════════════════

PASSAGERS_TM = {"Catégorie A (détroit)": 3.00, "Catégorie C (au-delà)": 3.90}

VEHICULES_PASSAGERS_TM = {
    "2.1 Véhicule 2 Roues":                      3.00,
    "2.2 Voiture tourisme Cat A":                 6.00,
    "2.3 Voiture tourisme Cat C":                 7.90,
    "2.4 Remorque bagage (véhicule)":             2.50,
    "2.5 Remorque bagage (fourgon/autocar)":      35.00,
    "2.6 Caravane/Camping-Car/Fourgon":           35.00,
    "2.7 Autocar/transport collectif":            35.00,
    "2.8 Complément transbordement":              20.00,
}

REMORQUAGE_DEPANNAGE_TM = {
    "PTAC ≤ 3,5T":                                20,
    "PTAC 3,5T – 8T":                             30,
    "PTAC > 8T":                                  40,
    "Déplacement VNA ≤3,5T → zone ctrl import":   20,
    "Déplacement VNA ≤3,5T → TVCU":               20,
    "Déplacement VNA ≤3,5T TVCU → zone ctrl":     20,
}

# ═══════════════════════════════════════════════════════════════════════════════
# 12. MANUTENTION VRAC — TM (€/T)
# ═══════════════════════════════════════════════════════════════════════════════

MANUTENTION_VRAC_TM = {
    "Céréales – Sortie directe":            4.22,
    "Urée – Sortie directe":                5.41,
    "Big Bags – Sortie directe":            11.53,
    "Ferraille – Sortie directe":           9.20,
    "Bobines <10T – Bord-Quai":             5.24,
    "Bobines >10T – Bord-Quai":             9.89,
    "Colis 10-40T – Bord-Quai":             63.07,
    "Colis >40T – Bord-Quai":               74.48,
}
# Pénalité improductivité TM: 1 500€/shift

# Stockage vrac TM:
STOCKAGE_VRAC_TM = {
    "Hangar":      {"j1_5": 0.51, "j6_15": 1.53, "j16_25": 4.08, "j26+": 6.12},
    "Terre-plein": {"j6_15": 0.51, "j16_25": 1.33, "j26+": 2.04},
}

# ═══════════════════════════════════════════════════════════════════════════════
# 13. FOURNITURES (identiques TM et NWM)
# ═══════════════════════════════════════════════════════════════════════════════

FOURNITURES = {
    "Eau potable":        {"unite": "€/m³",  "tarif": 1.235},
    "Électricité BT":     {"unite": "€/kWh", "tarif": 0.1623},
    "Électricité MT":     {"unite": "€/kWh", "tarif": 0.1373},
    "Branchement eau":    {"unite": "€",     "tarif": 10.0},
}

# ═══════════════════════════════════════════════════════════════════════════════
# 14. SERVICES DIVERS — TM exclusivement
# ═══════════════════════════════════════════════════════════════════════════════

TRACTION_PORTUAIRE_TM = {
    "Remorque navire ↔ quai":                            23,
    "Remorque zone ctrl ↔ quai":                         27,
    "Remorque quai → zone ctrl + scanner":               29,
    "Traction même zone ctrl + scanner":                 30,
    "Remorque >40T navire ↔ quai":                       62,
    "Remorque >40T zone ctrl ↔ quai":                    74,
    "Remorque zone ctrl → zone enlèvement":              26,
    "Remorque MEDHUB ↔ quai":                            40,
    "Remorque entre hangars MEDHUB":                     27,
    "CTN 40' MEDHUB ↔ terminal (12h, plateau inclus)":   92,
    "CTN 40' ferroviaire → terminal (plateau, 12h)":     75,
    "Location plateau 8h":                               52,
    "CTN 40' intra TM1 (1h, plateau inclus)":            40,
    "CTN 40' TM1 ↔ TM2 (1h, plateau inclus)":           62,
}

TAXI_RADE_TM = {
    "Tarif horaire": 300, "Minimum": 500,
    "Transport marchandise (€/kg)": 0.3, "Minimum marchandise": 200,
}

SECURITE_TM = {
    "Escorte matière dangereuse":        52,
    "Escorte convoi exceptionnel":       52,
    "Escorte soutage par barge":         250,
    "Mise à disposition équipe (€/h)":   150,
}

ZVCI_TM = {
    "Manutention Reach Stacker (20'-40')": 37,
    "Stockage ≤1j après main levée 20'":   20,
    "Stockage ≤1j après main levée 40'":   32,
    "Stockage >1j après main levée 20'":   40,
    "Stockage >1j après main levée 40'":   50,
    "Manutention intégrale":               100,
    "Manutention spéciale (friperie etc)": 300,
}

DECHETS_TM = {
    "Solides": "Selon convention TMU",
    "Liquides commerce": "1 700 DH/opération (max 12m³) ou 66 €/m³",
    "Liquides passage": "1 700 DH/op ou 10 000 DH forfait mensuel",
}
DECHETS_NWM = {
    "Solides": "Variable (DHS)",
    "Liquides commerce": "1 700 DH/op ou 66 €/m³",
}

MRN_TM = {
    "1-50 MRN":     3.00,
    "51-100 MRN":   2.50,
    "101-300 MRN":  2.20,
    "301-500 MRN":  2.00,
    ">500 MRN":     1.80,
}

CONSULTATION_MEDICALE_TM = 100  # €

REMORQUEUR_DISPO_TM = {"1-2h": 553.6, "3-12h": 532.8, "13h+": 512.0}  # €/h
VEILLE_SECURITE = {"TM": 339.9, "NWM": 330.0}  # €/h/remorqueur

VEDETTE_PILOTAGE_TM = {"Intérieur port (€/h)": 100, "Rade/mouillage (€/h)": 175, "Minimum rade": 300}

PARKING_TIR_TM = {
    "Import – Remorque/ensemble plein": {"franchise_j": 2, "j2_5": 15, "j5_10": 30, "j10+": 40},
    "Import – Remorque/ensemble vide":  {"franchise_j": 1, "j1_3": 15, "j3+": 40},
    "Import – Camion ≤12m":             {"franchise_j": 2, "j2_5": 15, "j5_10": 30, "j10+": 40},
    "Export":                            {"franchise_h": 24, "tarif_h": 1},
    "Fourgons/souffrance":              {"franchise_h": 24, "tarif_24h": 20},
    "Matière Dangereuse":               {"franchise_j": 2, "j2_4": 25, "j4+": 100},
}
# Plafond litiges douane: 1 000€ max

TVCU_MANUTENTION_TM = {
    "Véhicule tourisme neuf Cat A – Import": 16.65,
    "Véhicule tourisme neuf Cat A – Export": 7.28,
    "Véhicule tourisme neuf Cat A – Transbordement": 3.00,
    "Véhicule Cat B (1,5-3T) – Import": 20.81,
    "Véhicule Cat C (3-5T) – Import": 22.89,
    "Engin H&H neuf – Import": 9.74,
    "Engin H&H neuf >10T – Import": 16.23,
    "Engin remorqué ≤50T – Import": 12.98,
    "Engin remorqué >50T – Import": 16.23,
    "Véhicule léger roulant – Import": 3.00,
    "Véhicule léger roulant – Export": 2.60,
    "Véhicule léger roulant – Transbordement": 1.62,
}

DIVERS_TM = {
    "Duplicata de facture": 5,
    "Titre d'accès personne/mois": 10,
    "Macaron véhicule/an": 27,
}

# ═══════════════════════════════════════════════════════════════════════════════
# 15. HELPER: Calcul Volume Géométrique
# ═══════════════════════════════════════════════════════════════════════════════

def calc_vg(loa, beam, draft):
    """Calcule le Volume Géométrique conformément à la formule officielle.
    Te min = 0.14 × √(L × b)"""
    te_min = 0.14 * math.sqrt(loa * beam)
    te = max(draft, te_min)
    return loa * beam * te

def calc_stationnement(vg, taux_base, sejour_h, en_rade=False, jour_rade=0):
    """Calcule le droit de stationnement selon les règles communes."""
    if sejour_h <= 24:
        return 0.0  # franchise 24h
    heures_apres = sejour_h - 24
    if heures_apres <= 8:
        base = vg * taux_base / 3  # 1/3 si ≤8h après franchise
    else:
        jours = math.ceil(heures_apres / 24)
        base = vg * taux_base * jours
    # Réduction rade
    if en_rade and jour_rade >= 1:
        return base * 0.5
    return base
