"""
Хранилище состояния бота в SQLite.

Таблицы:
- subscribers: подписчики бота (chat_id)
- alert_state: для каждой пары — последний достигнутый уровень и id сообщения для редактирования
"""

import sqlite3
import logging
from contextlib import contextmanager
from config import DB_PATH

logger = logging.getLogger(__name__)


def init_db():
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS subscribers (
                chat_id INTEGER PRIMARY KEY,
                subscribed_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS alert_state (
                symbol TEXT PRIMARY KEY,
                direction TEXT NOT NULL,        -- 'up' или 'down'
                last_level REAL NOT NULL,        -- последний достигнутый уровень, напр. 30, 40, 50
                started_at INTEGER NOT NULL,     -- unix timestamp начала импульса
                updated_at INTEGER NOT NULL      -- unix timestamp последнего обновления
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS alert_messages (
                symbol TEXT NOT NULL,
                chat_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                PRIMARY KEY (symbol, chat_id)
            )
        """)
        conn.commit()
    logger.info("База данных инициализирована")


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


# --- Подписчики ---

def add_subscriber(chat_id: int):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO subscribers (chat_id) VALUES (?)", (chat_id,)
        )
        conn.commit()


def remove_subscriber(chat_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM subscribers WHERE chat_id = ?", (chat_id,))
        conn.commit()


def is_subscribed(chat_id: int) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM subscribers WHERE chat_id = ?", (chat_id,)
        ).fetchone()
        return row is not None


def get_all_subscribers() -> list[int]:
    with get_conn() as conn:
        rows = conn.execute("SELECT chat_id FROM subscribers").fetchall()
        return [r["chat_id"] for r in rows]


def count_subscribers() -> int:
    with get_conn() as conn:
        row = conn.execute("SELECT COUNT(*) as c FROM subscribers").fetchone()
        return row["c"]


# --- Состояние алертов по парам ---

def get_alert_state(symbol: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM alert_state WHERE symbol = ?", (symbol,)
        ).fetchone()
        return dict(row) if row else None


def upsert_alert_state(symbol: str, direction: str, level: float, started_at: int, updated_at: int):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO alert_state (symbol, direction, last_level, started_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(symbol) DO UPDATE SET
                direction = excluded.direction,
                last_level = excluded.last_level,
                started_at = excluded.started_at,
                updated_at = excluded.updated_at
        """, (symbol, direction, level, started_at, updated_at))
        conn.commit()


def clear_alert_state(symbol: str):
    """Импульс затух (вернулись ниже порога старта) — сбрасываем состояние и историю сообщений."""
    with get_conn() as conn:
        conn.execute("DELETE FROM alert_state WHERE symbol = ?", (symbol,))
        conn.execute("DELETE FROM alert_messages WHERE symbol = ?", (symbol,))
        conn.commit()


def get_all_active_symbols() -> list[str]:
    with get_conn() as conn:
        rows = conn.execute("SELECT symbol FROM alert_state").fetchall()
        return [r["symbol"] for r in rows]


# --- message_id для редактирования сообщений (схлопывание алертов) ---

def get_message_id(symbol: str, chat_id: int) -> int | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT message_id FROM alert_messages WHERE symbol = ? AND chat_id = ?",
            (symbol, chat_id)
        ).fetchone()
        return row["message_id"] if row else None


def set_message_id(symbol: str, chat_id: int, message_id: int):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO alert_messages (symbol, chat_id, message_id)
            VALUES (?, ?, ?)
            ON CONFLICT(symbol, chat_id) DO UPDATE SET message_id = excluded.message_id
        """, (symbol, chat_id, message_id))
        conn.commit()
