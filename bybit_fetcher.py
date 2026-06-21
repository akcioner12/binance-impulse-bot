"""
Получение списка фьючерсных пар USDT на Bybit с фильтром по минимальному объёму.
"""

import logging
import aiohttp
from config import BYBIT_FUTURES_REST, MIN_DAILY_VOLUME_USDT

logger = logging.getLogger(__name__)


async def get_bybit_tradable_symbols(session: aiohttp.ClientSession) -> list[str]:
    """
    Возвращает все линейные (USDT Perpetual) пары Bybit с дневным объёмом
    выше MIN_DAILY_VOLUME_USDT.
    """
    url = f"{BYBIT_FUTURES_REST}/v5/market/tickers"
    params = {"category": "linear"}

    async with session.get(url, params=params) as resp:
        resp.raise_for_status()
        data = await resp.json()

    if data.get("retCode") != 0:
        logger.error(f"Bybit API ошибка: {data.get('retMsg')}")
        return []

    tickers = data["result"]["list"]
    symbols = [
        t["symbol"] for t in tickers
        if t["symbol"].endswith("USDT")
        and float(t.get("turnover24h", 0)) >= MIN_DAILY_VOLUME_USDT
    ]

    logger.info(
        f"Bybit: найдено {len(symbols)} пар USDT с объёмом >= ${MIN_DAILY_VOLUME_USDT:,.0f}"
    )
    return symbols
