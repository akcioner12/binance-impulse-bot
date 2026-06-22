"""
Binance + Bybit Futures — мониторинг импульса цены по скользящему окну.

Архитектура:
1. fetcher.py / bybit_fetcher.py   — список торгуемых пар на каждой бирже (весь рынок, фильтр по объёму)
2. collector.py / bybit_collector.py — WebSocket-стримы, пуш при закрытии каждой минутной свечи
3. analyzer.py    — скользящее окно 24ч, детект импульса 30% -> +10% -> +10% ...
4. notifier.py    — отправка/редактирование сообщений в Telegram (схлопывание по монете, ссылка на нужную биржу)
5. commands.py    — обработка /start /stop /status (long polling, параллельно)
6. storage.py     — SQLite: подписчики + состояние алертов (персистентность)

Правило дублей (см. договорённости): если токен есть на Binance — мониторим
только через Binance. Bybit подключается только для токенов, которых на
Binance нет вообще. Так каждый тикер обрабатывается ровно одной биржей.

Раз в сутки (SYMBOLS_REFRESH_SEC) список пар на обеих биржах пересчитывается
заново (новые/делистнутые пары, изменения объёма) и WebSocket-подписки
перезапускаются с обновлённым списком — а не просто обновляются в памяти.
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
_active_symbols: set[str] = set()       # все символы Binance, для symbols_refresher и отчёта
_bybit_only_symbols: list[str] = []     # уникальные символы Bybit, для symbols_refresher и отчёта


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


async def on_binance_kline(symbol: str, price: float, ts: int):
    await on_kline_close(symbol, "Binance", price, ts)


async def on_bybit_kline(symbol: str, price: float, ts: int):
    await on_kline_close(symbol, "Bybit", price, ts)


async def fetch_current_symbol_lists() -> tuple[list[str], list[str]]:
    """Запрашивает свежие списки пар с обеих бирж и применяет правило дублей."""
    async with aiohttp.ClientSession() as session:
        binance_symbols = await get_tradable_symbols(session)
        bybit_symbols = await get_bybit_tradable_symbols(session)

    binance_set = set(binance_symbols)
    bybit_only = sorted(set(bybit_symbols) - binance_set)
    overlap_count = len(set(bybit_symbols) & binance_set)

    logger.info(
        f"Binance: {len(binance_symbols)} пар. Bybit: {len(bybit_symbols)} пар, "
        f"из них {overlap_count} пересекаются с Binance (пропускаются), "
        f"{len(bybit_only)} уникальны для Bybit (мониторятся)."
    )
    return sorted(binance_symbols), bybit_only


async def collectors_supervisor():
    """
    Раз в SYMBOLS_REFRESH_SEC секунд (по умолчанию 24ч) пересчитывает список торгуемых
    пар на обеих биржах и ПЕРЕЗАПУСКАЕТ WebSocket-подписки с этим обновлённым списком —
    новые/выросшие по объёму пары начинают мониториться, исчезнувшие/упавшие — отключаются.
    """
    global _active_symbols, _bybit_only_symbols

    while True:
        binance_symbols, bybit_only = await fetch_current_symbol_lists()
        _active_symbols = set(binance_symbols)
        _bybit_only_symbols = bybit_only

        logger.info(
            f"Запускаю WS-подписки: {len(binance_symbols)} пар Binance + "
            f"{len(bybit_only)} уникальных пар Bybit"
        )

        binance_task = asyncio.create_task(stream_all_symbols(binance_symbols, on_binance_kline))
        bybit_task = asyncio.create_task(stream_bybit_symbols(bybit_only, on_bybit_kline))

        # Ждём либо истечения интервала обновления, либо неожиданного завершения
        # одной из задач коллектора (это сигнал проблемы, а не штатное событие —
        # коллекторы рассчитаны работать вечно с автопереподключением внутри).
        done, pending = await asyncio.wait(
            [binance_task, bybit_task],
            timeout=SYMBOLS_REFRESH_SEC,
            return_when=asyncio.FIRST_COMPLETED,
        )

        if done:
            for task in done:
                exc = task.exception() if task.done() and not task.cancelled() else None
                if exc:
                    logger.error(f"Коллектор неожиданно завершился с ошибкой: {exc}. Перезапускаю немедленно.")
                else:
                    logger.warning("Коллектор неожиданно завершился без ошибки. Перезапускаю немедленно.")

        logger.info("Останавливаю текущие WS-подписки для пересборки списка пар...")
        for task in (binance_task, bybit_task):
            if not task.done():
                task.cancel()
        await asyncio.gather(binance_task, bybit_task, return_exceptions=True)


def get_symbols_for_report() -> tuple[list[str], list[str]]:
    return list(_active_symbols), list(_bybit_only_symbols)


async def main():
    init_db()

    logger.info("Загружаю начальные списки торгуемых пар с Binance и Bybit...")

    # Восстанавливаем активные импульсы из БД (переживаем перезапуск без потери состояния)
    restored = 0
    for symbol in get_all_active_symbols():
        state = get_alert_state(symbol)
        if state:
            tracker.restore_state(symbol, state["direction"], state["last_level"])
            restored += 1
    if restored:
        logger.info(f"Восстановлено {restored} активных импульсов из БД")

    async with aiohttp.ClientSession() as cmd_session:
        await asyncio.gather(
            collectors_supervisor(),
            run_command_listener(cmd_session),
            daily_report_loop(get_symbols_for_report, get_all_subscribers),
        )


if __name__ == "__main__":
    asyncio.run(main())
