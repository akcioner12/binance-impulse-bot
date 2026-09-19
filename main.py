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

from config import SYMBOLS_REFRESH_SEC, ADMIN_CHAT_ID, IMPULSE_START_THRESHOLD
from fetcher import get_tradable_symbols
from bybit_fetcher import get_bybit_tradable_symbols
from analyzer import PriceWindowTracker, DailyHighTracker
from collector import stream_all_symbols
from bybit_collector import stream_bybit_symbols
from notifier import broadcast_signal, send_text, set_bot_commands
from commands import run_command_listener
from daily_report import daily_report_loop
from trading_journal_report import trading_journal_report_loop, load_seed_events
from storage import init_db, get_all_subscribers, upsert_alert_state, clear_alert_state, get_alert_state, get_all_active_symbols
from trading_storage import init_trading_db, init_paper_trading_db, expire_all_pending_signals, seed_trade_events_if_empty
import live_trading
import impulse_analysis
import market_data

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("main")

# Включаем DEBUG только для наших модулей (не для websockets/aiohttp — иначе зальём логи шумом).
# Это даёт доступ к диагностике уровня логов analyzer.py (приближение к порогу) и main.py (полный
# список пар) без раздувания общего объёма логов от сторонних библиотек.
for _mod in ("main", "analyzer", "fetcher", "bybit_fetcher", "collector", "bybit_collector"):
    logging.getLogger(_mod).setLevel(logging.DEBUG)

tracker = PriceWindowTracker()
dump_tracker = DailyHighTracker()
_active_symbols: set[str] = set()       # все символы Binance, для symbols_refresher и отчёта
_bybit_only_symbols: list[str] = []     # уникальные символы Bybit, для symbols_refresher и отчёта
_overlap_symbols: set[str] = set()      # символы, торгуемые на ОБЕИХ биржах -- для второй ссылки в алерте
_tick_count = 0                          # диагностика: общее число обработанных тиков с момента старта
_last_tick_log_time = 0.0
_seen_symbols: set[str] = set()         # диагностика: подтверждение первого тика по каждому символу


async def on_kline_close(symbol: str, exchange: str, price: float, ts: int):
    """Вызывается коллектором (любой биржи) при закрытии каждой минутной свечи."""
    global _tick_count, _last_tick_log_time
    _tick_count += 1

    if symbol not in _seen_symbols:
        _seen_symbols.add(symbol)
        logger.debug(f"Первый тик получен: {symbol} [{exchange}] price={price}")

    # Раз в час логируем суммарное число обработанных тиков — если коллектор молча
    # перестанет получать данные (например, из-за тихого разрыва соединения без
    # исключения), это будет видно по тому, что счётчик перестал расти.
    now = time.time()
    if now - _last_tick_log_time >= 3600:
        logger.info(f"Диагностика: обработано тиков с момента старта = {_tick_count}, уникальных символов = {len(_seen_symbols)}")
        _last_tick_log_time = now

    signal = tracker.update(symbol, exchange, price, ts)

    try:
        tick_events = live_trading.handle_price_tick(symbol, price)
        if tick_events:
            logger.info(f"Автотрейдинг [{symbol}]: {tick_events}")
            if "part1_filled" in tick_events or "part2_filled" in tick_events:
                asyncio.create_task(_notify_entry_for_admin(symbol, exchange))
            if "atr_refresh_needed" in tick_events:
                asyncio.create_task(_refresh_pending_setup_atr_for_admin(symbol))
        for note in live_trading.pop_notifications():
            asyncio.create_task(_send_notification(note["chat_id"], note["text"]))
    except Exception as e:
        logger.error(f"Автотрейдинг: ошибка обработки тика {symbol}: {e}")

    dump_signal = dump_tracker.update(symbol, exchange, price, ts)
    if dump_signal is not None and dump_signal.level == IMPULSE_START_THRESHOLD:
        asyncio.create_task(_run_autotrading_for_admin(
            dump_signal.symbol, dump_signal.exchange, dump_signal.direction,
            dump_signal.current_price, dump_signal.window_start_price,
        ))

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

    if signal.level == IMPULSE_START_THRESHOLD and signal.direction == "up":
        asyncio.create_task(_run_autotrading_for_admin(
            signal.symbol, signal.exchange, signal.direction,
            signal.current_price, signal.window_start_price,
        ))

    subscribers = get_all_subscribers()
    if not subscribers:
        logger.info(f"Сигнал {signal.symbol} ({signal.exchange}) {signal.direction} {signal.level}% — нет подписчиков")
        return

    also_on_bybit = signal.exchange == "Binance" and is_also_on_bybit(signal.symbol)

    async with aiohttp.ClientSession() as session:
        indicators_data = await _build_alert_indicators_safe(session, signal.exchange, signal.symbol)
        await broadcast_signal(session, subscribers, signal, indicators_data, also_on_bybit)

    logger.info(
        f"Сигнал отправлен: {signal.symbol} [{signal.exchange}] {signal.direction.upper()} "
        f"{signal.change_pct:+.1f}% (уровень {signal.level:.0f}%) -> {len(subscribers)} подписчикам"
    )


async def _build_alert_indicators_safe(session: aiohttp.ClientSession, exchange: str, symbol: str) -> dict | None:
    """Доп. показатели (RSI/объём/funding/OI) для текстового алерта -- best-effort, не блокирует рассылку при сбое."""
    try:
        return await impulse_analysis.build_alert_indicators(session, exchange, symbol)
    except Exception as e:
        logger.error(f"Алерт: ошибка получения показателей для {symbol}: {e}")
        return None


async def on_binance_kline(symbol: str, price: float, ts: int):
    await on_kline_close(symbol, "Binance", price, ts)


async def on_bybit_kline(symbol: str, price: float, ts: int):
    await on_kline_close(symbol, "Bybit", price, ts)


async def _run_autotrading_for_admin(
    symbol: str, exchange: str, direction: str, current_price: float, window_start_price: float
):
    """
    Запускается фоновой задачей (asyncio.create_task) -- НЕ блокирует обработку
    тиков других символов. Любая ошибка здесь логируется и не должна влиять
    на рассылку текстовых алертов подписчикам -- автотрейдинг полностью
    изолирован от основного пути обработки тиков.
    """
    try:
        async with aiohttp.ClientSession() as session:
            result = await live_trading.handle_new_impulse(
                session, ADMIN_CHAT_ID, symbol, exchange, direction, current_price, window_start_price
            )
        if result is not None:
            logger.info(f"Автотрейдинг [{symbol}]: сетап найден, классификация={result['classification']}, signal_id={result['signal_id']}")
    except Exception as e:
        logger.error(f"Автотрейдинг: ошибка обработки импульса {symbol} [{exchange}]: {e}")


async def _refresh_pending_setup_atr_for_admin(symbol: str):
    """
    Пересчитывает ATR для ожидающего сетапа, когда цена ушла далеко без отката
    (событие "atr_refresh_needed"). Фоновая задача, не блокирует обработку
    тиков других символов.
    """
    try:
        async with aiohttp.ClientSession() as session:
            await live_trading.refresh_pending_setup_atr(session, symbol)
    except Exception as e:
        logger.error(f"Автотрейдинг: ошибка обновления ATR для {symbol}: {e}")


async def _notify_entry_for_admin(symbol: str, exchange: str):
    """
    Отчёт о факте входа в сделку (срабатывание трейлинг-триггера части 1/2) --
    отдельно от исходного запроса подтверждения, который уходит ДО входа.
    Фоновая задача, не блокирует обработку тиков других символов.
    """
    try:
        snapshot = live_trading.get_position_snapshot(symbol)
        if snapshot is None:
            return
        also_on_bybit = exchange == "Binance" and is_also_on_bybit(symbol)
        report = live_trading.format_entry_report(symbol, exchange, snapshot, also_on_bybit)
        async with aiohttp.ClientSession() as session:
            await send_text(session, snapshot["chat_id"], report)
    except Exception as e:
        logger.error(f"Автотрейдинг: ошибка отправки отчёта о входе {symbol}: {e}")


async def _send_notification(chat_id: int, text: str):
    """Отправляет одно уведомление о действии бота по открытой позиции (TP, безубыток+, трейлинг, закрытие)."""
    try:
        async with aiohttp.ClientSession() as session:
            await send_text(session, chat_id, text)
    except Exception as e:
        logger.error(f"Автотрейдинг: ошибка отправки уведомления: {e}")


async def fetch_current_symbol_lists() -> tuple[list[str], list[str], set[str]]:
    """Запрашивает свежие списки пар с обеих бирж и применяет правило дублей."""
    async with aiohttp.ClientSession() as session:
        binance_symbols = await get_tradable_symbols(session)
        bybit_symbols = await get_bybit_tradable_symbols(session)

    binance_set = set(binance_symbols)
    overlap = set(bybit_symbols) & binance_set
    bybit_only = sorted(set(bybit_symbols) - binance_set)

    logger.info(
        f"Binance: {len(binance_symbols)} пар. Bybit: {len(bybit_symbols)} пар, "
        f"из них {len(overlap)} пересекаются с Binance (пропускаются), "
        f"{len(bybit_only)} уникальны для Bybit (мониторятся)."
    )
    # Полный список пар на DEBUG-уровне — чтобы при расследовании пропущенного сигнала
    # можно было найти конкретный тикер в логах и подтвердить/исключить его отсутствие в подписке.
    logger.debug(f"Полный список Binance: {','.join(sorted(binance_symbols))}")
    logger.debug(f"Полный список Bybit-only: {','.join(bybit_only)}")
    return sorted(binance_symbols), bybit_only, overlap


def is_also_on_bybit(symbol: str) -> bool:
    """True, если символ (источник -- Binance) также торгуется на Bybit -- вторая ссылка в алерте."""
    return symbol in _overlap_symbols


async def _seed_price_history(session: aiohttp.ClientSession, binance_symbols: list[str], bybit_only: list[str]):
    """
    Подтягивает часовые свечи за 24ч по каждому символу и сидирует буфер
    tracker (PriceWindowTracker.seed_history()) -- без этого скользящее 24ч
    окно живёт только в памяти процесса и обнуляется при КАЖДОМ рестарте бота
    (редеплой), из-за чего детекция импульсов эффективно "теряет память" на
    время, пока новые тики не накопят собственные 24ч заново (прод-инцидент
    14.09.2026: 6 редеплоев за 1.5ч -> ни одного сигнала за это время).
    Ограниченная параллельность (semaphore), чтобы не упереться в rate limit биржи;
    сбой по одному символу не должен останавливать сидирование остальных.
    """
    semaphore = asyncio.Semaphore(10)

    async def seed_one(exchange: str, symbol: str):
        async with semaphore:
            try:
                candles = await market_data.fetch_klines(session, exchange, symbol, "1h", limit=24)
            except Exception as e:
                logger.debug(f"Не удалось подтянуть историю для {symbol} [{exchange}]: {e}")
                return
            points = [(c["open_time"] // 1000, c["close"]) for c in candles]
            tracker.seed_history(symbol, points)

    tasks = [seed_one("Binance", s) for s in binance_symbols] + [seed_one("Bybit", s) for s in bybit_only]
    if tasks:
        await asyncio.gather(*tasks)
    logger.info(f"Сидирование истории цен завершено: {len(tasks)} символов")


async def _seed_dump_history(session: aiohttp.ClientSession, binance_symbols: list[str], bybit_only: list[str]):
    """
    Подтягивает 10 дневных свечей по каждому символу и сидирует dump_tracker
    (DailyHighTracker.seed_history()) -- без этого 10-дневное окно детекции
    дампов для автотрейдинга после каждого рестарта Railway "теряет память"
    так же, как раньше терял её 24ч-буфер PriceWindowTracker (см.
    _seed_price_history выше). Последняя из 10 свечей -- текущие (ещё не
    завершённые) сутки, остальные до 9 -- завершённые дни.
    """
    semaphore = asyncio.Semaphore(10)

    async def seed_one(exchange: str, symbol: str):
        async with semaphore:
            try:
                candles = await market_data.fetch_klines(session, exchange, symbol, "1d", limit=10)
            except Exception as e:
                logger.debug(f"Не удалось подтянуть дневную историю для {symbol} [{exchange}]: {e}")
                return
            if not candles:
                return
            *completed, today = candles
            daily_highs = [c["high"] for c in completed]
            dump_tracker.seed_history(symbol, daily_highs, today["high"], today["open_time"] // 1000)

    tasks = [seed_one("Binance", s) for s in binance_symbols] + [seed_one("Bybit", s) for s in bybit_only]
    if tasks:
        await asyncio.gather(*tasks)
    logger.info(f"Сидирование дневной истории дампов завершено: {len(tasks)} символов")


async def collectors_supervisor():
    """
    Раз в SYMBOLS_REFRESH_SEC секунд (по умолчанию 24ч) пересчитывает список торгуемых
    пар на обеих биржах и ПЕРЕЗАПУСКАЕТ WebSocket-подписки с этим обновлённым списком —
    новые/выросшие по объёму пары начинают мониториться, исчезнувшие/упавшие — отключаются.
    """
    global _active_symbols, _bybit_only_symbols, _overlap_symbols

    is_first_run = True
    while True:
        binance_symbols, bybit_only, overlap = await fetch_current_symbol_lists()
        _active_symbols = set(binance_symbols)
        _overlap_symbols = overlap
        _bybit_only_symbols = bybit_only

        if is_first_run:
            # Только на старте процесса -- на плановых 24ч-обновлениях у уже
            # отслеживаемых символов буфер и так накоплен реальными тиками.
            async with aiohttp.ClientSession() as seed_session:
                await _seed_price_history(seed_session, binance_symbols, bybit_only)
                await _seed_dump_history(seed_session, binance_symbols, bybit_only)
            is_first_run = False

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
    init_trading_db()
    init_paper_trading_db()
    seeded = seed_trade_events_if_empty(ADMIN_CHAT_ID, load_seed_events())
    if seeded:
        logger.info(f"Загружена история событий автотрейдинга в trade_events: {seeded} строк")

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

    # Восстанавливаем открытые позиции автотрейдинга (SL/TP/Chandelier) -- иначе
    # редеплой во время открытой сделки "осиротит" её без какого-либо мониторинга.
    # Ожидающие (ещё не исполненные) сетапы восстановить нельзя -- их триггеры
    # живут только в памяти, поэтому такие сигналы просто помечаются истёкшими.
    restored_positions = live_trading.restore_open_positions()
    if restored_positions:
        logger.info(f"Восстановлено {restored_positions} открытых позиций автотрейдинга из БД")
    expire_all_pending_signals()

    async with aiohttp.ClientSession() as cmd_session:
        await set_bot_commands(cmd_session, ADMIN_CHAT_ID)
        await asyncio.gather(
            collectors_supervisor(),
            run_command_listener(cmd_session),
            daily_report_loop(get_symbols_for_report, get_all_subscribers),
            trading_journal_report_loop(ADMIN_CHAT_ID),
        )


if __name__ == "__main__":
    asyncio.run(main())
