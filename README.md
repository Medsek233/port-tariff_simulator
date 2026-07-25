# ⚓ Simulateur d'Escales & Facturation Portuaire — Nador West Med

Application **Streamlit** de simulation des **tarifs d'escale** et de **génération de
factures dynamiques** pour le port de **Nador West Med (NWM)**, basée sur le
*Cahier Tarifaire NWM — Avril 2025*.

> Deux applications sont fournies dans ce dépôt :
> | Fichier | Rôle |
> |---|---|
> | **`app.py`** | 🧾 **Simulateur d'escales & facturation** (application principale) |
> | `comparateur_tm_nwm.py` | 📊 Comparateur de tarifs Tanger Med vs NWM vs Algeciras |

---

## ✨ Fonctionnalités

- **🚢 Référentiel navires** — flotte multi-navires (nom, IMO, pavillon, GT, LOA, largeur,
  tirant d'eau). Le **Volume Géométrique (VG)** est calculé automatiquement
  (`VG = L × B × T`, avec tirant minimum réglementaire `0,14·√(L·B)`).
- **📖 Catalogue tarifaire éditable** — ~44 articles pré-chargés depuis le Cahier
  Tarifaire NWM. **Ajout / modification / suppression** de n'importe quel article, avec
  une *base de calcul* configurable (forfait, ×GT, ×VG, ×jours, formule pilotage, barème
  remorquage, mètre linéaire lamanage…).
- **🛳️ Escales complexes multi-mouvements / multi-terminaux** — chaque escale est un
  **itinéraire chronologique** de mouvements (mouillage → accostage → shifting → mouillage
  → départ…) avec **sélecteur date & heure** par mouvement. Chaque tronçon peut se trouver
  sur un **terminal différent** (TCE, TCO, TRV, PP1-PP3, TGL, TMD, TVS ou rade), avec ses
  **propres services** (pilotage, remorqueurs, lamanage cochés par mouvement).
- **🅿️ Droit de stationnement par itinéraire** — calculé tronçon par tronçon au **taux de
  chaque terminal**, avec franchise de 24 h et **réduction rade de 50 %** au-delà de 4 jours
  de mouillage ; un détail par tronçon est affiché.
- **⚙️ Chiffrage automatique** — génération des prestations (droits de port, pilotage,
  remorquage, lamanage, droits marchandise) à partir des caractéristiques du navire et de
  l'escale, puis **édition libre des lignes** (ajout / modification / suppression).
- **⚠️ Majorations & suppléments de durée** — dépassement de durée pilotage (+50 %/h > 2 h),
  lamanage (+30 %/h > 2 h), retard confirmé (+50 %), retard > 20 min (+100 %), navire
  désemparé (+100 %), remorquage sans propulsion (+25 %) et déhalage (25 % du tarif).
- **🧾 Factures dynamiques** — numérotation automatique, dates & échéance, TVA par ligne,
  totaux HT / TVA / TTC, contre-valeur en MAD. **Aperçu intégré** + export
  **HTML imprimable (→ PDF)** et **CSV**.
- **📈 Tableau de bord** — CA prévisionnel, répartition par catégorie de prestation,
  historique des escales et factures.
- **💾 Persistance SQLite** — navires, catalogue, escales, factures et paramètres sont
  automatiquement enregistrés dans une base SQLite (`nwm_data.db`) : les données
  **survivent aux rafraîchissements de page** et aux redémarrages du serveur.
- **🚫 Zone Franche** — montants **exonérés de TVA** (aucune TVA appliquée sur les factures).

## 📐 Tarifs NWM (Avril 2025) intégrés

- **Droits de port navire** par terminal (nautique / port / stationnement, €/m³ VG) —
  incl. catégorie *Car Carrier*.
- **Pilotage** : formule par **Volume Géométrique** à 2 tranches (entrée-sortie &
  changement de quai), minimum 261,1 €.
- **Remorquage** : barème par tranche de GT + supplément 150 €/5000 GT au-delà de 50 000.
- **Lamanage** : 1,1596 €/mètre linéaire (LOA), minimum 80 €, supplément durée +30 %/h.
- **Droits marchandise** : conteneurs (transbordement / import-export / cabotage),
  marchandises diverses, hydrocarbures (blancs/noirs), rouliers.
- **Fournitures & services** : eau, électricité, veille sécurité, déchets…

---

## 🚀 Lancement en local

```bash
pip install -r requirements.txt
streamlit run app.py
```

L'application est accessible sur `http://localhost:8501`.

Pour le comparateur de tarifs :

```bash
streamlit run comparateur_tm_nwm.py
```

---

## ☁️ Déploiement sur Streamlit Community Cloud (gratuit)

### 1 · Envoyer le code sur GitHub

```bash
git add .
git commit -m "Simulateur d'escales & facturation NWM"
git push -u origin claude/port-tariffs-invoices-streamlit-e8m0p6
```

(ou fusionnez la branche dans `main` puis poussez.)

### 2 · Déployer

1. Aller sur **https://share.streamlit.io** et se connecter avec GitHub.
2. Cliquer **« Create app »** → **« Deploy a public app from GitHub »**.
3. Renseigner :
   - **Repository** : `medsek233/port-tariff_simulator`
   - **Branch** : `main` (ou votre branche)
   - **Main file path** : `app.py`
4. Cliquer **« Deploy »**. Streamlit installe `requirements.txt` et publie l'app à une
   URL du type `https://<votre-app>.streamlit.app`.

> 💡 Le fichier `.streamlit/config.toml` applique automatiquement le thème NWM.
> Aucune variable secrète n'est nécessaire.

> 💾 **Persistance :** la base `nwm_data.db` (SQLite) est créée automatiquement au premier
> lancement. Sur Streamlit Community Cloud le disque est *éphémère* — les données sont
> conservées tant que le conteneur reste actif, mais peuvent être réinitialisées lors d'un
> redéploiement ou d'une longue mise en veille. Pour une durabilité permanente, définir la
> variable d'environnement `NWM_DB_PATH` vers un volume persistant, ou brancher une base
> externe (l'interface de `storage.py` reste identique).

---

## 📁 Structure

```
port-tariff_simulator/
├── app.py                  # 🧾 Application principale — escales & facturation
├── billing.py              # Moteur de tarification & génération de factures
├── storage.py              # Persistance des données (SQLite)
├── tarifs_data.py          # Données tarifaires (NWM Avril 2025, TM, Algeciras)
├── comparateur_tm_nwm.py   # 📊 Comparateur de tarifs (application secondaire)
├── requirements.txt        # Dépendances Python
├── .streamlit/config.toml  # Thème & configuration Streamlit
└── README.md
```

## 🧾 Générer un PDF de facture

Depuis l'onglet **Factures**, télécharger la facture au format **HTML**, l'ouvrir dans un
navigateur puis **Ctrl / Cmd + P → Enregistrer au format PDF**. La mise en page est
optimisée pour l'impression.

---

*Tarifs HT en EUR — Source : Cahier Tarifaire NWM, Avril 2025. Outil de simulation ;
les montants réels facturés font foi selon les conditions contractuelles en vigueur.*
