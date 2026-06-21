"""
Получение списка фьючерсных пар USDT с фильтром по минимальному объёму.
"""

import logging
import aiohttp
from config import BINANCE_FUTURES_REST, MIN_DAILY_VOLUME_USDT

logger = logging.getLogger(__name__)


async def get_tradable_symbols(session: aiohttp.ClientSession) -> list[str]:
    """
    Возвращает ВСЕ фьючерсные пары USDT с дневным объёмом выше MIN_DAILY_VOLUME_USDT.
    Это весь рынок (не топ-N), отфильтрованный только от полностью мёртвых пар.
    """
    # 1. Список активных контрактов (исключаем делистинг/приостановленные)
    info_url = f"{BINANCE_FUTURES_REST}/fapi/v1/exchangeInfo"
    async with session.get(info_url) as resp:
        resp.raise_for_status()
        info = await resp.json()

    active_symbols = {
        s["symbol"] for s in info["symbols"]
        if s["status"] == "TRADING"
        and s["symbol"].endswith("USDT")
        and s["contractType"] == "PERPETUAL"
    }

    # 2. 24h объёмы для фильтрации мёртвых пар
    ticker_url = f"{BINANCE_FUTURES_REST}/fapi/v1/ticker/24hr"
    async with session.get(ticker_url) as resp:
        resp.raise_for_status()
        tickers = await resp.json()

    symbols = [
        t["symbol"] for t in tickers
        if t["symbol"] in active_symbols
        and float(t["quoteVolume"]) >= MIN_DAILY_VOLUME_USDT
    ]

    logger.info(
        f"Найдено {len(symbols)} торгуемых пар USDT с объёмом >= "
        f"${MIN_DAILY_VOLUME_USDT:,.0f} (из {len(active_symbols)} всего активных)"
    )
    return symbols
