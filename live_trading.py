"""
Живая оркестрация автотрейдинга: от найденного импульса до открытой/закрытой
paper-позиции. Состояние (ожидающие сетапы, открытые позиции) хранится в
памяти процесса, keyed по символу.

НЕ подключён к живому потоку цен main.py -- см. отдельный план подключения.
"""

import logging

import trading_storage
import impulse_analysis
import magnet_levels as magnet_levels_module
import entry_engine
import position_manager
import order_executor
import market_data

logger = logging.getLogger(__name__)

_pending_setups: dict[str, dict] = {}
_open_positions: dict[str, dict] = {}

DEFAULT_ATR_MULTIPLIER = 1.5


async def handle_new_impulse(
    session, chat_id: int, symbol: str, exchange: str, direction: str,
    current_price: float, window_start_price: float,
) -> dict | None:
    """
    Вызывается один раз на новый импульс (первый уровень ImpulseSignal).
    Возвращает None, если автотрейдинг неприменим для этого символа сейчас.
    """
    profile = trading_storage.get_profile(chat_id)
    if profile is None or not profile["is_active"]:
        return None
    if symbol in _pending_setups or symbol in _open_positions:
        return None
    if len(trading_storage.get_open_positions(chat_id)) >= profile["max_concurrent_trades"]:
        return None

    return None  # ветки classification реализуются в Task 3-4
