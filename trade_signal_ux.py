"""
UX подтверждения сигнала перед исполнением сделки: сообщение в Telegram
с двумя кнопками и таймаутом, после которого сделка исполняется по
дефолтным параметрам профиля автоматически (чтобы не терять быстро
развивающиеся сетапы).

Кнопка "Ручные настройки" в этой версии ведёт себя так же, как "По умолчанию" --
полноценный быстрый прогон параметров именно для этой сделки отложен на потом
(профиль и так можно поменять в любой момент через /trading_setup).

НЕ импортирует live_trading.py -- функция исполнения передаётся параметром
(execute_fn) при вызове request_confirmation(), чтобы исключить циклический
импорт между этим модулем и live_trading.py.
"""

import asyncio
import logging

import aiohttp
from notifier import send_text_with_keyboard, send_text

logger = logging.getLogger(__name__)

CONFIRMATION_TIMEOUT_SECONDS = 300  # 5 минут

_awaiting_confirmation: dict[str, dict] = {}


def is_awaiting_confirmation(symbol: str) -> bool:
    return symbol in _awaiting_confirmation


def _format_signal_text(
    symbol: str, exchange: str, direction: str, classification: str,
    current_price: float, magnet_levels: list[float],
) -> str:
    direction_word = "рост" if direction == "up" else "падение"
    classification_word = "разворот (фейд манипуляции)" if classification == "reversal" else "продолжение (по тренду)"
    levels_text = ", ".join(f"{lvl:.6g}" for lvl in magnet_levels) if magnet_levels else "—"
    return (
        f"⚡ *Найден сетап: {symbol}* [{exchange}]\n\n"
        f"Импульс: {direction_word}\n"
        f"Классификация: {classification_word}\n"
        f"Текущая цена: `{current_price:.6g}`\n"
        f"Магнит-уровни: {levels_text}\n\n"
        f"Исполнить сделку по параметрам профиля?"
    )


async def request_confirmation(
    session, chat_id: int, symbol: str, exchange: str, direction: str, classification: str,
    current_price: float, window_start_price: float, profile: dict, analysis: dict,
    signal_id: int, magnet_levels: list[float], execute_fn,
) -> None:
    """
    execute_fn -- async-функция с сигнатурой execute_fn(session, chat_id, symbol,
    exchange, direction, classification, current_price, window_start_price,
    profile, analysis, signal_id), вызывается по кнопке или по таймауту.
    """
    _awaiting_confirmation[symbol] = {
        "chat_id": chat_id, "exchange": exchange, "direction": direction,
        "classification": classification, "current_price": current_price,
        "window_start_price": window_start_price, "profile": profile, "analysis": analysis,
        "signal_id": signal_id, "execute_fn": execute_fn, "resolved": False,
    }

    text = _format_signal_text(symbol, exchange, direction, classification, current_price, magnet_levels)
    await send_text_with_keyboard(
        session, chat_id, text,
        [
            [{"text": "✅ Войти по умолчанию", "callback_data": f"trade_confirm:defaults:{symbol}"}],
            [{"text": "🛠 Ручные настройки", "callback_data": f"trade_confirm:manual:{symbol}"}],
        ],
    )

    asyncio.create_task(_auto_confirm_after_timeout(symbol))


async def _auto_confirm_after_timeout(symbol: str) -> None:
    await asyncio.sleep(CONFIRMATION_TIMEOUT_SECONDS)
    await _resolve(symbol)


async def handle_confirmation_callback(symbol: str, choice: str) -> bool:
    """choice -- 'defaults' или 'manual' (в этой версии оба ведут к одному исходу)."""
    if symbol not in _awaiting_confirmation:
        return False
    await _resolve(symbol)
    return True


async def _resolve(symbol: str) -> None:
    """
    Прод-инцидент 14.09.2026: необработанное исключение внутри execute_fn
    (вызывается из голой asyncio.create_task() без try/except выше по цепочке
    -- ни кнопка, ни таймаут) оставляло сетап "подвешенным" навсегда без
    единого сообщения ни в лог, ни админу. execute_fn оборачивается в
    try/except, чтобы сбой был виден и не блокировал остальные сетапы.
    """
    state = _awaiting_confirmation.get(symbol)
    if state is None or state["resolved"]:
        return
    state["resolved"] = True
    del _awaiting_confirmation[symbol]

    try:
        async with aiohttp.ClientSession() as session:
            await state["execute_fn"](
                session, state["chat_id"], symbol, state["exchange"], state["direction"],
                state["classification"], state["current_price"], state["window_start_price"],
                state["profile"], state["analysis"], state["signal_id"],
            )
    except Exception as e:
        logger.error(f"Ошибка исполнения сетапа {symbol}: {e}", exc_info=True)
        async with aiohttp.ClientSession() as session:
            await send_text(session, state["chat_id"], f"⚠️ Не удалось исполнить сделку {symbol}: {e}")
