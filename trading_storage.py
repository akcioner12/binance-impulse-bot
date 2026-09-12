"""
Хранилище профиля риск-менеджмента и API-ключей для автотрейдинга.

Таблицы:
- user_profiles: настройки риск-менеджмента одного пользователя (владельца бота,
  в будущем — любого подписчика с подключённым автотрейдингом)
- api_credentials: API-ключи бирж, зашифрованные через crypto_utils (Fernet)
"""

import logging

from storage import get_conn
from crypto_utils import encrypt_secret, decrypt_secret

logger = logging.getLogger(__name__)


def init_trading_db():
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_profiles (
                chat_id INTEGER PRIMARY KEY,
                risk_percent REAL NOT NULL,
                daily_loss_limit_percent REAL NOT NULL,
                leverage REAL NOT NULL,
                sl_method TEXT NOT NULL,
                sl_fixed_percent REAL,
                breakeven_after_tp INTEGER NOT NULL,
                tp_split_preset TEXT NOT NULL,
                max_concurrent_trades INTEGER NOT NULL,
                trading_mode TEXT NOT NULL DEFAULT 'paper',
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS api_credentials (
                chat_id INTEGER NOT NULL,
                exchange TEXT NOT NULL,
                api_key_encrypted TEXT NOT NULL,
                api_secret_encrypted TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (chat_id, exchange)
            )
        """)
        conn.commit()
    logger.info("Таблицы автотрейдинга инициализированы")


def save_profile(
    chat_id: int,
    risk_percent: float,
    daily_loss_limit_percent: float,
    leverage: float,
    sl_method: str,
    sl_fixed_percent: float | None,
    breakeven_after_tp: int,
    tp_split_preset: str,
    max_concurrent_trades: int,
):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO user_profiles (
                chat_id, risk_percent, daily_loss_limit_percent, leverage,
                sl_method, sl_fixed_percent, breakeven_after_tp,
                tp_split_preset, max_concurrent_trades
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                risk_percent = excluded.risk_percent,
                daily_loss_limit_percent = excluded.daily_loss_limit_percent,
                leverage = excluded.leverage,
                sl_method = excluded.sl_method,
                sl_fixed_percent = excluded.sl_fixed_percent,
                breakeven_after_tp = excluded.breakeven_after_tp,
                tp_split_preset = excluded.tp_split_preset,
                max_concurrent_trades = excluded.max_concurrent_trades,
                updated_at = CURRENT_TIMESTAMP
        """, (
            chat_id, risk_percent, daily_loss_limit_percent, leverage,
            sl_method, sl_fixed_percent, breakeven_after_tp,
            tp_split_preset, max_concurrent_trades,
        ))
        conn.commit()


def get_profile(chat_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM user_profiles WHERE chat_id = ?", (chat_id,)
        ).fetchone()
        return dict(row) if row else None


def has_profile(chat_id: int) -> bool:
    return get_profile(chat_id) is not None


def save_api_credentials(chat_id: int, exchange: str, api_key: str, api_secret: str):
    encrypted_key = encrypt_secret(api_key)
    encrypted_secret = encrypt_secret(api_secret)
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO api_credentials (chat_id, exchange, api_key_encrypted, api_secret_encrypted)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(chat_id, exchange) DO UPDATE SET
                api_key_encrypted = excluded.api_key_encrypted,
                api_secret_encrypted = excluded.api_secret_encrypted
        """, (chat_id, exchange, encrypted_key, encrypted_secret))
        conn.commit()


def get_api_credentials(chat_id: int, exchange: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM api_credentials WHERE chat_id = ? AND exchange = ?",
            (chat_id, exchange)
        ).fetchone()
    if not row:
        return None
    return {
        "chat_id": row["chat_id"],
        "exchange": row["exchange"],
        "api_key": decrypt_secret(row["api_key_encrypted"]),
        "api_secret": decrypt_secret(row["api_secret_encrypted"]),
    }
