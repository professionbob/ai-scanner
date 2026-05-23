import sqlite3
from datetime import datetime

DB_NAME = "alpha_signals.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS signals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT,
        ticker TEXT,
        themes TEXT,
        score INTEGER,
        price REAL,
        level TEXT
    )
    """)

    conn.commit()
    conn.close()

def save_signal(ticker, themes, score, price, level):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()

    cur.execute("""
    INSERT INTO signals (
        created_at, ticker, themes, score, price, level
    )
    VALUES (?, ?, ?, ?, ?, ?)
    """, (
        datetime.now().isoformat(),
        ticker,
        ",".join(themes),
        score,
        price,
        level
    ))

    conn.commit()
    conn.close()