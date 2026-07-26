"""
storage.py — Persistance des données via SQLite

Stocke l'état de l'application (navires, catalogue tarifaire, escales, factures,
paramètres de l'émetteur, compteur de factures) dans une base SQLite locale, afin
que les données survivent aux rafraîchissements de page et aux redémarrages.

Modèle : une simple table clé/valeur (`app_state`) où chaque valeur est un blob JSON.
C'est amplement suffisant pour le volume de données concerné et évite un schéma rigide
qui casserait à chaque évolution du modèle.

⚠️ Sur Streamlit Community Cloud, le disque est éphémère : la base est conservée tant que
le conteneur vit (rafraîchissements, navigation), mais peut être réinitialisée lors d'un
redéploiement ou d'une mise en veille prolongée. Pour une durabilité totale, brancher une
base externe (Postgres, Supabase…) — l'interface de ce module resterait identique.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading

# Emplacement de la base : surchargé par la variable d'environnement NWM_DB_PATH.
DB_PATH = os.environ.get("NWM_DB_PATH", os.path.join(os.path.dirname(__file__), "nwm_data.db"))

# Clés persistées (état applicatif complet).
KEYS = ["vessels", "catalog", "calls", "invoices", "company", "inv_seq"]

_lock = threading.Lock()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def init_db() -> None:
    """Crée la table de stockage si nécessaire."""
    with _lock, _connect() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS app_state ("
            "  key   TEXT PRIMARY KEY,"
            "  value TEXT NOT NULL"
            ")"
        )
        conn.commit()


def load_state() -> dict:
    """Charge tout l'état persisté. Renvoie un dict {clé: objet} (clés absentes ignorées)."""
    init_db()
    out: dict = {}
    with _lock, _connect() as conn:
        cur = conn.execute("SELECT key, value FROM app_state")
        for key, value in cur.fetchall():
            try:
                out[key] = json.loads(value)
            except (json.JSONDecodeError, TypeError):
                continue
    return out


def save_key(key: str, obj) -> None:
    """Persiste une seule clé."""
    init_db()
    with _lock, _connect() as conn:
        conn.execute(
            "INSERT INTO app_state(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(obj, ensure_ascii=False, default=str)),
        )
        conn.commit()


def save_state(state: dict) -> None:
    """Persiste toutes les clés connues présentes dans `state`."""
    init_db()
    with _lock, _connect() as conn:
        for key in KEYS:
            if key in state:
                conn.execute(
                    "INSERT INTO app_state(key, value) VALUES(?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (key, json.dumps(state[key], ensure_ascii=False, default=str)),
                )
        conn.commit()


def clear_state() -> None:
    """Efface toutes les données persistées."""
    init_db()
    with _lock, _connect() as conn:
        conn.execute("DELETE FROM app_state")
        conn.commit()


def db_info() -> dict:
    """Renvoie quelques informations sur la base (pour l'UI)."""
    exists = os.path.exists(DB_PATH)
    size = os.path.getsize(DB_PATH) if exists else 0
    return {"path": DB_PATH, "exists": exists, "size_kb": round(size / 1024, 1)}
