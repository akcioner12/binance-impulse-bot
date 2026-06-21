"""
Binance Futures — мониторинг импульса цены по скользящему окну.

Архитектура:
1. fetcher.py     — раз в час обновляет список торгуемых пар (весь рынок, фильтр по объёму)
2. collector.py   — WebSocket-стримы kline_1m, пуш при закрытии каждой минутной свечи
3. analyzer.py    — скользящее окно 30 мин, детект импульса 30% -> +10% -> +10% ...
4. notifier.py    — отправка/редактирование сообщений в Telegram (схлопывание по монете)
5. commands.py    — обработка /start /stop /status (long polling, параллельно)
6. storage.py     — SQLite: подписчики + состояние алертов (персистентность)
"""

import asyncio
import logging
import time

import aiohttp

from config import SYMBOLS_REFRESH_SEC
from fetcher import get_tradable_symbols
from analyzer import PriceWindowTracker
from collector import stream_all_symbols
from notifier import broadcast_signal
from commands import run_command_listener
from storage import init_db, get_all_subscribers, upsert_alert_state, clear_alert_state, get_alert_state, get_all_active_symbols

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("main")

tracker = PriceWindowTracker()
_active_symbols: set[str] = set()


async def on_kline_close(symbol: str, price: float, ts: int):
    """Вызывается коллектором при закрытии каждой минутной свечи."""
    signal = tracker.update(symbol, price, ts)

    if signal is None:
        # Проверяем, не затух ли активный импульс (это обрабатывается внутри tracker,
        # но состояние в БД нужно почистить отдельно)
        if not tracker.is_active(symbol) and get_alert_state(symbol):
            clear_alert_state(symbol)
        return

    # Сохраняем состояние в БД (персистентность)
    upsert_alert_state(
        symbol=signal.symbol,
        direction=signal.direction,
        level=signal.level,
        started_at=ts,
        updated_at=ts,
    )

    subscribers = get_all_subscribers()
    if not subscribers:
        logger.info(f"Сигнал {signal.symbol} {signal.direction} {signal.level}% — нет подписчиков")
        return

    async with aiohttp.ClientSession() as session:
        await broadcast_signal(session, subscribers, signal)

    logger.info(
        f"Сигнал отправлен: {signal.symbol} {signal.direction.upper()} "
        f"{signal.change_pct:+.1f}% (уровень {signal.level:.0f}%) -> {len(subscribers)} подписчикам"
    )


async def symbols_refresher():
    """Периодически обновляет список торгуемых пар и перезапускает WS-соединения при изменениях."""
    global _active_symbols
    while True:
        try:
            async with aiohttp.ClientSession() as session:
                symbols = await get_tradable_symbols(session)
            new_set = set(symbols)
            if new_set != _active_symbols:
                logger.info(
                    f"Список пар изменился: было {len(_active_symbols)}, стало {len(new_set)}. "
                    f"Изменения вступят в силу при следующем перезапуске WS."
                )
                _active_symbols = new_set
        except Exception as e:
            logger.exception(f"Ошибка обновления списка пар: {e}")
        await asyncio.sleep(SYMBOLS_REFRESH_SEC)


async def main():
    init_db()

    logger.info("Загружаю начальный список торгуемых пар...")
    async with aiohttp.ClientSession() as session:
        symbols = await get_tradable_symbols(session)
    global _active_symbols
    _active_symbols = set(symbols)

    # Восстанавливаем активные импульсы из БД (переживаем перезапуск без потери состояния)
    restored = 0
    for symbol in get_all_active_symbols():
        state = get_alert_state(symbol)
        if state:
            tracker.restore_state(symbol, state["direction"], state["last_level"])
            restored += 1
    if restored:
        logger.info(f"Восстановлено {restored} активных импульсов из БД")

    logger.info(f"Мониторинг запущен: {len(symbols)} пар")

    async with aiohttp.ClientSession() as cmd_session:
        await asyncio.gather(
            stream_all_symbols(symbols, on_kline_close),
            run_command_listener(cmd_session),
            symbols_refresher(),
        )


if __name__ == "__main__":
    asyncio.run(main())
