"""
Уведомление о найденном сетапе: сообщение в Telegram (без кнопок) и немедленное
исполнение по параметрам профиля.

Раньше здесь было подтверждение кнопками с таймаутом 5 минут -- убрано 20.09.2026
по решению владельца: профиль полностью настроен, а за 5 минут манипуляция успевает
развиться.

НЕ импортирует live_trading.py -- функция исполнения передаётся параметром
(execute_fn), чтобы исключить циклический импорт между этим модулем и live_trading.py.
"""

import logging

from notifier import send_text

logger = logging.getLogger(__name__)


def _format_signal_text(
    symbol: str, exchange: str, direction: str, classification: str,
    current_price: float, magnet_levels: list[float],
) -> str:
    direction_word = "рост" if direction == "up" else "падение"
    classification_word = "разворот (фейд манипуляции)" if classification == "reversal" else "продолжение (по тренду)"
    levels_text = ", ".join(f"{lvl:.6g}" for lvl in magnet_levels) if magnet_levels else "—"
    if classification == "reversal":
        header = f"⚡ *Сетап найден, жду отката: {symbol}* [{exchange}]"
        footer = "Вход НЕ выполнен: бот ждёт отката цены от экстремума и войдёт автоматически по параметрам профиля."
    else:
        header = f"⚡ *Сетап найден, вход по тренду: {symbol}* [{exchange}]"
        footer = "Вход выполнен сразу по параметрам профиля (стратегия по тренду)."
    return (
        f"{header}\n\n"
        f"Импульс: {direction_word}\n"
        f"Классификация: {classification_word}\n"
        f"Текущая цена: `{current_price:.6g}`\n"
        f"Магнит-уровни: {levels_text}\n\n"
        f"{footer}"
    )


async def announce_and_execute(
    session, chat_id: int, symbol: str, exchange: str, direction: str, classification: str,
    current_price: float, window_start_price: float, profile: dict, analysis: dict,
    signal_id: int, magnet_levels: list[float], execute_fn,
) -> None:
    """
    execute_fn -- async-функция с сигнатурой execute_fn(session, chat_id, symbol,
    exchange, direction, classification, current_price, window_start_price,
    profile, analysis, signal_id). Сначала исполняем (время критично), потом уведомляем.

    Прод-инцидент 14.09.2026: необработанное исключение в execute_fn оставляло
    сетап без единого сообщения ни в лог, ни админу -- поэтому ошибка логируется
    и уходит админу в Telegram, а не теряется.
    """
    try:
        await execute_fn(
            session, chat_id, symbol, exchange, direction, classification,
            current_price, window_start_price, profile, analysis, signal_id,
        )
    except Exception as e:
        logger.error(f"Ошибка исполнения сетапа {symbol}: {e}", exc_info=True)
        await send_text(session, chat_id, f"⚠️ Не удалось исполнить сделку {symbol}: {e}")
        return

    await send_text(
        session, chat_id,
        _format_signal_text(symbol, exchange, direction, classification, current_price, magnet_levels),
    )
