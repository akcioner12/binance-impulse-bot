"""
Ежедневный отчёт топ-10 импульсов вверх/вниз за день (от 00:00 UTC до момента отчёта).

Важно: используем дневную свечу (klines interval=1d), а НЕ priceChangePercent из
ticker/24hr — то поле считается за скользящие 24 часа, а нам нужно изменение именно
от начала календарного дня UTC, как договаривались.
"""

import asyncio
import logging
import time
from datetime import datetime, timezone

import aiohttp

from config import (
    BINANCE_FUTURES_REST, BYBIT_FUTURES_REST,
    DAILY_REPORT_HOUR_UTC, DAILY_REPORT_MINUTE_UTC, DAILY_REPORT_TOP_N,
)
from analyzer import build_exchange_link
from notifier import send_text

logger = logging.getLogger(__name__)


async def _get_binance_daily_changes(session: aiohttp.ClientSession, symbols: list[str]) -> dict[str, float]:
    """
    Возвращает {symbol: change_pct} для списка символов Binance, используя
    дневную свечу (open сегодняшнего дня UTC -> текущая цена).
    """
    changes = {}
    sem = asyncio.Semaphore(10)  # не долбим API слишком параллельно

    async def fetch_one(symbol: str):
        async with sem:
            url = f"{BINANCE_FUTURES_REST}/fapi/v1/klines"
            params = {"symbol": symbol, "interval": "1d", "limit": 1}
            try:
                async with session.get(url, params=params) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
                    if data:
                        open_price = float(data[0][1])
                        close_price = float(data[0][4])  # последняя известная цена в свече
                        if open_price > 0:
                            changes[symbol] = (close_price - open_price) / open_price * 100
            except Exception as e:
                logger.warning(f"Binance daily kline error {symbol}: {e}")

    await asyncio.gather(*(fetch_one(s) for s in symbols))
    return changes


async def _get_bybit_daily_changes(session: aiohttp.ClientSession, symbols: list[str]) -> dict[str, float]:
    """То же самое для уникальных пар Bybit."""
    changes = {}
    sem = asyncio.Semaphore(10)

    async def fetch_one(symbol: str):
        async with sem:
            url = f"{BYBIT_FUTURES_REST}/v5/market/kline"
            params = {"category": "linear", "symbol": symbol, "interval": "D", "limit": 1}
            try:
                async with session.get(url, params=params) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
                    rows = data.get("result", {}).get("list", [])
                    if rows:
                        # Bybit kline формат: [start, open, high, low, close, volume, turnover]
                        open_price = float(rows[0][1])
                        close_price = float(rows[0][4])
                        if open_price > 0:
                            changes[symbol] = (close_price - open_price) / open_price * 100
            except Exception as e:
                logger.warning(f"Bybit daily kline error {symbol}: {e}")

    await asyncio.gather(*(fetch_one(s) for s in symbols))
    return changes


def _format_report(gainers: list[tuple], losers: list[tuple]) -> str:
    lines = ["📊 *Итоги дня — топ импульсов*\n"]

    lines.append(f"🚀 *Топ-{len(gainers)} рост:*")
    for i, (symbol, exchange, pct) in enumerate(gainers, 1):
        link = build_exchange_link(exchange, symbol)
        lines.append(f"{i}. [{symbol}]({link}) — *+{pct:.1f}%* ({exchange})")

    lines.append("\n🔻 *Топ-{} падение:*".format(len(losers)))
    for i, (symbol, exchange, pct) in enumerate(losers, 1):
        link = build_exchange_link(exchange, symbol)
        lines.append(f"{i}. [{symbol}]({link}) — *{pct:.1f}%* ({exchange})")

    lines.append(f"\n_Отчёт за {datetime.now(timezone.utc).strftime('%Y-%m-%d')} (UTC)_")
    return "\n".join(lines)


async def build_and_send_daily_report(
    binance_symbols: list[str],
    bybit_only_symbols: list[str],
    subscribers: list[int],
):
    """Собирает дневные изменения по всем парам и рассылает топ-10/топ-10 подписчикам."""
    if not subscribers:
        logger.info("Дневной отчёт: нет подписчиков, отчёт не формируется")
        return

    logger.info(f"Формирую дневной отчёт по {len(binance_symbols)} парам Binance + {len(bybit_only_symbols)} Bybit...")

    async with aiohttp.ClientSession() as session:
        binance_changes, bybit_changes = await asyncio.gather(
            _get_binance_daily_changes(session, binance_symbols),
            _get_bybit_daily_changes(session, bybit_only_symbols),
        )

    all_changes = [
        (symbol, "Binance", pct) for symbol, pct in binance_changes.items()
    ] + [
        (symbol, "Bybit", pct) for symbol, pct in bybit_changes.items()
    ]

    if not all_changes:
        logger.warning("Дневной отчёт: не удалось получить данные ни по одной паре")
        return

    sorted_changes = sorted(all_changes, key=lambda x: x[2], reverse=True)
    gainers = sorted_changes[:DAILY_REPORT_TOP_N]
    losers = sorted(all_changes, key=lambda x: x[2])[:DAILY_REPORT_TOP_N]

    report_text = _format_report(gainers, losers)

    async with aiohttp.ClientSession() as session:
        for chat_id in subscribers:
            await send_text(session, chat_id, report_text)
            await asyncio.sleep(0.05)

    logger.info(f"Дневной отчёт отправлен {len(subscribers)} подписчикам")


def seconds_until_next_report() -> float:
    """Считает, сколько секунд осталось до следующего времени отправки отчёта (UTC)."""
    now = datetime.now(timezone.utc)
    target = now.replace(hour=DAILY_REPORT_HOUR_UTC, minute=DAILY_REPORT_MINUTE_UTC, second=0, microsecond=0)
    if target <= now:
        from datetime import timedelta
        target += timedelta(days=1)
    return (target - now).total_seconds()


async def daily_report_loop(get_symbols_fn, get_subscribers_fn):
    """
    Бесконечный цикл: ждёт до времени отчёта (по умолчанию 17:00 UTC = 20:00 Киев/Москва),
    формирует и рассылает отчёт, затем ждёт следующего дня.

    get_symbols_fn() -> (binance_symbols, bybit_only_symbols)
    get_subscribers_fn() -> list[int]
    """
    while True:
        wait_sec = seconds_until_next_report()
        logger.info(f"Следующий дневной отчёт через {wait_sec / 3600:.1f}ч")
        await asyncio.sleep(wait_sec)

        try:
            binance_symbols, bybit_only_symbols = get_symbols_fn()
            subscribers = get_subscribers_fn()
            await build_and_send_daily_report(binance_symbols, bybit_only_symbols, subscribers)
        except Exception as e:
            logger.exception(f"Ошибка формирования дневного отчёта: {e}")

        # небольшая пауза, чтобы не сработать дважды при дрожании таймера
        await asyncio.sleep(60)
