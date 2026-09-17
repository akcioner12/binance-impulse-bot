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


def update_max_concurrent_trades(chat_id: int, value: int):
    with get_conn() as conn:
        conn.execute(
            "UPDATE user_profiles SET max_concurrent_trades = ?, updated_at = CURRENT_TIMESTAMP WHERE chat_id = ?",
            (value, chat_id),
        )
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


_POSITION_RECOVERY_COLUMNS = {
    "original_stop_loss": "REAL",
    "tp_split_preset": "TEXT",
    "breakeven_after_tp": "INTEGER",
    "atr_1h": "REAL",
    "remaining_quantity": "REAL",
    "tp1_filled": "INTEGER NOT NULL DEFAULT 0",
    "tp2_filled": "INTEGER NOT NULL DEFAULT 0",
    "tp3_filled": "INTEGER NOT NULL DEFAULT 0",
    "chandelier_active": "INTEGER NOT NULL DEFAULT 0",
    "chandelier_extreme_price": "REAL",
    "chandelier_stop_price": "REAL",
    "tp_r_multiples": "TEXT",
}


def _ensure_position_recovery_columns(conn):
    """
    Добавляет колонки, нужные для восстановления открытых позиций при рестарте
    (см. live_trading.restore_open_positions), если их ещё нет -- на уже
    развёрнутой в проде БД, созданной до этой фичи, CREATE TABLE IF NOT EXISTS
    их не добавит сам по себе.
    """
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(positions)")}
    for column, sql_type in _POSITION_RECOVERY_COLUMNS.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE positions ADD COLUMN {column} {sql_type}")


def init_paper_trading_db():
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS paper_balance (
                chat_id INTEGER PRIMARY KEY,
                balance REAL NOT NULL,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                symbol TEXT NOT NULL,
                exchange TEXT NOT NULL,
                direction TEXT NOT NULL,
                mode TEXT NOT NULL,
                avg_entry_price REAL NOT NULL,
                quantity REAL NOT NULL,
                stop_loss REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                realized_pnl REAL NOT NULL DEFAULT 0.0,
                opened_at TEXT DEFAULT CURRENT_TIMESTAMP,
                closed_at TEXT
            )
        """)
        _ensure_position_recovery_columns(conn)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS trade_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                symbol TEXT NOT NULL,
                exchange TEXT NOT NULL,
                impulse_direction TEXT NOT NULL,
                classification TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
    logger.info("Таблицы paper-trading инициализированы")


def init_paper_balance(chat_id: int, starting_balance: float):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO paper_balance (chat_id, balance) VALUES (?, ?)",
            (chat_id, starting_balance),
        )
        conn.commit()


def get_paper_balance(chat_id: int) -> float | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT balance FROM paper_balance WHERE chat_id = ?", (chat_id,)
        ).fetchone()
        return row["balance"] if row else None


def adjust_paper_balance(chat_id: int, delta: float) -> float:
    with get_conn() as conn:
        conn.execute(
            "UPDATE paper_balance SET balance = balance + ?, updated_at = CURRENT_TIMESTAMP WHERE chat_id = ?",
            (delta, chat_id),
        )
        conn.commit()
        row = conn.execute(
            "SELECT balance FROM paper_balance WHERE chat_id = ?", (chat_id,)
        ).fetchone()
        return row["balance"]


def reset_paper_trading(chat_id: int, starting_balance: float = 10000.0):
    """Полный сброс paper-trading для chat_id: обнуляет баланс и стирает позиции/сигналы."""
    with get_conn() as conn:
        conn.execute("DELETE FROM positions WHERE chat_id = ?", (chat_id,))
        conn.execute("DELETE FROM trade_signals WHERE chat_id = ?", (chat_id,))
        conn.execute(
            "INSERT INTO paper_balance (chat_id, balance) VALUES (?, ?) "
            "ON CONFLICT(chat_id) DO UPDATE SET balance = excluded.balance, updated_at = CURRENT_TIMESTAMP",
            (chat_id, starting_balance),
        )
        conn.commit()


def create_position(
    chat_id: int, symbol: str, exchange: str, direction: str, mode: str,
    avg_entry_price: float, quantity: float, stop_loss: float,
    original_stop_loss: float | None = None,
    tp_split_preset: str = "equal",
    breakeven_after_tp: int = 2,
    atr_1h: float | None = None,
    tp_r_multiples: tuple[float, float, float] = (1.0, 2.0, 3.0),
) -> int:
    """
    original_stop_loss/tp_split_preset/breakeven_after_tp/atr_1h/tp_r_multiples --
    снимок параметров, нужный чтобы при рестарте бота восстановить open-позицию
    точно в том же состоянии (см. live_trading.restore_open_positions). Если
    original_stop_loss не передан -- берётся равным stop_loss на входе (совпадает,
    т.к. на момент создания позиции стоп ещё никуда не двигался).
    """
    if original_stop_loss is None:
        original_stop_loss = stop_loss
    tp_r_multiples_str = ",".join(str(r) for r in tp_r_multiples)
    with get_conn() as conn:
        cursor = conn.execute("""
            INSERT INTO positions (
                chat_id, symbol, exchange, direction, mode,
                avg_entry_price, quantity, stop_loss,
                original_stop_loss, tp_split_preset, breakeven_after_tp, atr_1h,
                remaining_quantity, tp_r_multiples
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            chat_id, symbol, exchange, direction, mode, avg_entry_price, quantity, stop_loss,
            original_stop_loss, tp_split_preset, breakeven_after_tp, atr_1h, quantity,
            tp_r_multiples_str,
        ))
        conn.commit()
        return cursor.lastrowid


def get_position(position_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM positions WHERE id = ?", (position_id,)).fetchone()
        return dict(row) if row else None


def get_open_positions(chat_id: int) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM positions WHERE chat_id = ? AND status = 'open'", (chat_id,)
        ).fetchall()
        return [dict(row) for row in rows]


def get_all_open_positions() -> list[dict]:
    """Все открытые позиции по всем chat_id -- для восстановления при старте бота."""
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM positions WHERE status = 'open'").fetchall()
        return [dict(row) for row in rows]


def update_position_progress(
    position_id: int,
    tp1_filled: bool,
    tp2_filled: bool,
    tp3_filled: bool,
    remaining_quantity: float,
    chandelier_active: bool,
    chandelier_extreme_price: float | None,
    chandelier_stop_price: float | None,
):
    """Снимок прогресса открытой позиции -- нужен для восстановления при рестарте."""
    with get_conn() as conn:
        conn.execute("""
            UPDATE positions SET
                tp1_filled = ?, tp2_filled = ?, tp3_filled = ?,
                remaining_quantity = ?,
                chandelier_active = ?, chandelier_extreme_price = ?, chandelier_stop_price = ?
            WHERE id = ?
        """, (
            int(tp1_filled), int(tp2_filled), int(tp3_filled), remaining_quantity,
            int(chandelier_active), chandelier_extreme_price, chandelier_stop_price,
            position_id,
        ))
        conn.commit()


def update_position_stop_loss(position_id: int, new_stop_loss: float):
    with get_conn() as conn:
        conn.execute(
            "UPDATE positions SET stop_loss = ? WHERE id = ?", (new_stop_loss, position_id)
        )
        conn.commit()


def close_position(position_id: int, realized_pnl: float):
    with get_conn() as conn:
        conn.execute(
            "UPDATE positions SET status = 'closed', realized_pnl = ?, closed_at = CURRENT_TIMESTAMP WHERE id = ?",
            (realized_pnl, position_id),
        )
        conn.commit()


def create_trade_signal(
    chat_id: int, symbol: str, exchange: str, impulse_direction: str, classification: str
) -> int:
    with get_conn() as conn:
        cursor = conn.execute("""
            INSERT INTO trade_signals (chat_id, symbol, exchange, impulse_direction, classification)
            VALUES (?, ?, ?, ?, ?)
        """, (chat_id, symbol, exchange, impulse_direction, classification))
        conn.commit()
        return cursor.lastrowid


def get_trade_signal(signal_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM trade_signals WHERE id = ?", (signal_id,)).fetchone()
        return dict(row) if row else None


def update_trade_signal_status(signal_id: int, status: str):
    with get_conn() as conn:
        conn.execute("UPDATE trade_signals SET status = ? WHERE id = ?", (status, signal_id))
        conn.commit()


def count_recent_signals(chat_id: int, symbol: str, since: str) -> int:
    """
    Сколько раз символ уже сигналил (любой статус) с момента `since` -- защита
    от многоволновых манипуляций (см. live_trading._compute_wave_size_multiplier).
    """
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM trade_signals WHERE chat_id = ? AND symbol = ? AND created_at >= ?",
            (chat_id, symbol, since),
        ).fetchone()
        return row["cnt"]


def expire_all_pending_signals():
    """
    При старте бота -- триггеры ожидающих (ещё не исполненных) сетапов живут
    только в памяти процесса и не переживают рестарт, поэтому такие сигналы
    помечаются истёкшими, а не остаются висеть в статусе pending навсегда.
    """
    with get_conn() as conn:
        conn.execute("UPDATE trade_signals SET status = 'expired' WHERE status = 'pending'")
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


def set_trading_active(chat_id: int, is_active: bool):
    with get_conn() as conn:
        conn.execute(
            "UPDATE user_profiles SET is_active = ? WHERE chat_id = ?",
            (1 if is_active else 0, chat_id),
        )
        conn.commit()


def get_positions_closed_since(chat_id: int, since: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM positions WHERE chat_id = ? AND status = 'closed' AND closed_at >= ?",
            (chat_id, since),
        ).fetchall()
        return [dict(row) for row in rows]
