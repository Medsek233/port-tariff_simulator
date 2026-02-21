# 🚢 Simulateur de Tarifs Portuaires — TM vs NWM 2025

Simulateur interactif comparant les tarifs de **Tanger Med** et **Nador West Med** basé sur les cahiers tarifaires 2025.

## 📊 Éléments de facturation couverts (~250+ paramètres)

### Droits de Port sur Navires
- Droit Nautique, Droit de Port, Droit de Stationnement
- 5 terminaux TM (TC, Vrac/MD, Véhicules, Hydrocarbures, GPL)
- 4 terminaux NWM (TC, MD, Hydrocarbures, GAZ)
- Forfaits navires rouliers (3 catégories TM vs forfait unique NWM)
- Règles de modulation (franchise 24h, 1/3, rade)

### Pilotage
- TM: barème complet par tranche VG (8 tranches + 2ème tranche >180k m³), 4 types de mouvement
- NWM: formule linéaire GTs (entrée/sortie + changement quai)
- Majorations: PEC, retard, désemparé, dépassement durée

### Remorquage
- TM: 16 tranches GT + supplément >50k GT
- NWM: 11 tranches GT + supplément >50k GT
- Majorations: sans propulsion, déhalage
- Services spéciaux: mise à disposition, veille sécurité

### Lamanage
- TM: base LOA (2 catégories), min 80€, supplément durée +30%
- NWM: formule linéaire GTs

### Conteneurs
- Droits port sur marchandise (transbordement, import/export, cabotage)
- Manutention TC1-TC4 (bord-quai, terre, pesage)
- Stockage par terminal et type conteneur

### Marchandises Diverses
- 11+ catégories comparées (colis lourds, bobines, big bags, céréales, etc.)

### Hydrocarbures (NWM détaillé)
- Produits blancs et noirs, 3 opérations

### Roulier
- Marchandises fret (7 catégories TM en €, 8 catégories NWM en DH)
- Passagers et véhicules légers
- Simulation fret avec conversion DH/EUR

### Stockage
- Conteneurs: 4 terminaux × 4 types × 3 périodes (TM)
- Vrac: hangar et terre-plein (TM)
- Parking TIR: import, export, MD (TM)

### Services Divers (TM exclusivement)
- Traction portuaire (14 opérations)
- Taxi rade, sécurité, ZVCI, TVCU
- MRN (déclaration européenne)
- Fournitures eau/électricité

### Coût Total Escale
- Synthèse comparative avec graphique empilé
- Analyse de sensibilité par volume EVP

## 🚀 Lancement

```bash
# Installer les dépendances
pip install -r requirements.txt

# Lancer l'application
streamlit run app.py
```

L'application sera accessible sur `http://localhost:8501`

## 📁 Structure

```
simulateur_tarif/
├── app.py              # Application Streamlit principale
├── tarifs_data.py      # Données tarifaires (~250+ paramètres)
├── requirements.txt    # Dépendances Python
└── README.md           # Ce fichier
```

## 📌 Sources

- Cahier Tarifaire Tanger Med 2025 (51 pages)
- Cahier Tarifaire Nador West Med 2025 (~10 pages)
- Paramètres Facturables TM2025 Complet (Excel)

---
*Données extraites en février 2026 — Tous tarifs HT*
