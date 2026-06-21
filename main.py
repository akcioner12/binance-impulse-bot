"""
Binance + Bybit Futures — мониторинг импульса цены по скользящему окну.

Архитектура:
1. fetcher.py / bybit_fetcher.py   — список торгуемых пар на каждой бирже (весь рынок, фильтр по объёму)
2. collector.py / bybit_collector.py — WebSocket-стримы, пуш при закрытии каждой минутной свечи
3. analyzer.py    — скользящее окно 30 мин, детект импульса 30% -> +10% -> +10% ...
4. notifier.py    — отправка/редактирование сообщений в Telegram (схлопывание по монете, ссылка на нужную биржу)
5. commands.py    — обработка /start /stop /status (long polling, параллельно)
6. storage.py     — SQLite: подписчики + состояние алертов (персистентность)

Правило дублей (см. договорённости): если токен есть на Binance — мониторим
только через Binance. Bybit подключается только для токенов, которых на
Binance нет вообще. Так каждый тикер обрабатывается ровно одной биржей.
"""

import asyncio
import logging
import time

import aiohttp

from config import SYMBOLS_REFRESH_SEC
from fetcher import get_tradable_symbols
from bybit_fetcher import get_bybit_tradable_symbols
from analyzer import PriceWindowTracker
from collector import stream_all_symbols
from bybit_collector import stream_bybit_symbols
from notifier import broadcast_signal
from commands import run_command_listener
from daily_report import daily_report_loop
from storage import init_db, get_all_subscribers, upsert_alert_state, clear_alert_state, get_alert_state, get_all_active_symbols

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("main")

tracker = PriceWindowTracker()
_active_symbols: set[str] = set()       # все символы Binance, для symbols_refresher
_bybit_only_symbols: list[str] = []     # уникальные символы Bybit, для дневного отчёта
_symbol_exchange_map: dict[str, str] = {}  # symbol -> 'Binance' | 'Bybit', для восстановления состояния


async def on_kline_close(symbol: str, exchange: str, price: float, ts: int):
    """Вызывается коллектором (любой биржи) при закрытии каждой минутной свечи."""
    signal = tracker.update(symbol, exchange, price, ts)

    if signal is None:
        if not tracker.is_active(symbol) and get_alert_state(symbol):
            clear_alert_state(symbol)
        return

    upsert_alert_state(
        symbol=signal.symbol,
        direction=signal.direction,
        level=signal.level,
        started_at=ts,
        updated_at=ts,
    )

    subscribers = get_all_subscribers()
    if not subscribers:
        logger.info(f"Сигнал {signal.symbol} ({signal.exchange}) {signal.direction} {signal.level}% — нет подписчиков")
        return

    async with aiohttp.ClientSession() as session:
        await broadcast_signal(session, subscribers, signal)

    logger.info(
        f"Сигнал отправлен: {signal.symbol} [{signal.exchange}] {signal.direction.upper()} "
        f"{signal.change_pct:+.1f}% (уровень {signal.level:.0f}%) -> {len(subscribers)} подписчикам"
    )


async def symbols_refresher():
    """Периодически обновляет список торгуемых пар (Binance + Bybit) и пересчитывает дубли."""
    global _active_symbols, _bybit_only_symbols
    while True:
        try:
            async with aiohttp.ClientSession() as session:
                binance_symbols = await get_tradable_symbols(session)
                bybit_symbols = await get_bybit_tradable_symbols(session)
            new_binance_set = set(binance_symbols)
            new_bybit_only = sorted(set(bybit_symbols) - new_binance_set)
            if new_binance_set != _active_symbols or new_bybit_only != _bybit_only_symbols:
                logger.info(
                    f"Список пар изменился: Binance было {len(_active_symbols)} -> {len(new_binance_set)}, "
                    f"Bybit-уникальных было {len(_bybit_only_symbols)} -> {len(new_bybit_only)}. "
                    f"Изменения в WS вступят в силу при следующем перезапуске."
                )
                _active_symbols = new_binance_set
                _bybit_only_symbols = new_bybit_only
        except Exception as e:
            logger.exception(f"Ошибка обновления списка пар: {e}")
        await asyncio.sleep(SYMBOLS_REFRESH_SEC)


async def main():
    init_db()

    logger.info("Загружаю списки торгуемых пар с Binance и Bybit...")
    async with aiohttp.ClientSession() as session:
        binance_symbols = await get_tradable_symbols(session)
        bybit_symbols = await get_bybit_tradable_symbols(session)

    binance_set = set(binance_symbols)
    bybit_set = set(bybit_symbols)

    # Правило дублей: Bybit мониторим только для символов, которых нет на Binance
    bybit_only = sorted(bybit_set - binance_set)
    overlap_count = len(bybit_set & binance_set)

    global _active_symbols, _bybit_only_symbols, _symbol_exchange_map
    _active_symbols = binance_set
    _bybit_only_symbols = bybit_only
    _symbol_exchange_map = {s: "Binance" for s in binance_symbols}
    _symbol_exchange_map.update({s: "Bybit" for s in bybit_only})

    logger.info(
        f"Binance: {len(binance_symbols)} пар. Bybit: {len(bybit_symbols)} пар, "
        f"из них {overlap_count} пересекаются с Binance (пропускаются), "
        f"{len(bybit_only)} уникальны для Bybit (мониторятся)."
    )

    # Восстанавливаем активные импульсы из БД (переживаем перезапуск без потери состояния)
    restored = 0
    for symbol in get_all_active_symbols():
        state = get_alert_state(symbol)
        if state:
            tracker.restore_state(symbol, state["direction"], state["last_level"])
            restored += 1
    if restored:
        logger.info(f"Восстановлено {restored} активных импульсов из БД")

    async def on_binance_kline(symbol: str, price: float, ts: int):
        await on_kline_close(symbol, "Binance", price, ts)

    async def on_bybit_kline(symbol: str, price: float, ts: int):
        await on_kline_close(symbol, "Bybit", price, ts)

    def get_symbols_for_report():
        return list(_active_symbols), list(_bybit_only_symbols)

    logger.info(f"Мониторинг запущен: {len(binance_symbols)} пар Binance + {len(bybit_only)} уникальных пар Bybit")

    async with aiohttp.ClientSession() as cmd_session:
        await asyncio.gather(
            stream_all_symbols(binance_symbols, on_binance_kline),
            stream_bybit_symbols(bybit_only, on_bybit_kline),
            run_command_listener(cmd_session),
            symbols_refresher(),
            daily_report_loop(get_symbols_for_report, get_all_subscribers),
        )


if __name__ == "__main__":
    asyncio.run(main())
