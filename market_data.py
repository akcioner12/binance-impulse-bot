"""
Получение исторических свечей (klines) с Binance и Bybit Futures.

Единый формат свечи независимо от биржи:
{"open_time": int, "open": float, "high": float, "low": float, "close": float, "volume": float}
Список всегда отсортирован по возрастанию времени (от старых к новым).
"""

import logging
import aiohttp

from config import BINANCE_FUTURES_REST, BYBIT_FUTURES_REST

logger = logging.getLogger(__name__)

_BYBIT_INTERVAL_MAP = {"15m": "15", "1h": "60", "4h": "240"}


async def _fetch_binance_klines(session: aiohttp.ClientSession, symbol: str, interval: str, limit: int) -> list[dict]:
    url = f"{BINANCE_FUTURES_REST}/fapi/v1/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    async with session.get(url, params=params) as resp:
        resp.raise_for_status()
        data = await resp.json()

    return [
        {
            "open_time": row[0],
            "open": float(row[1]),
            "high": float(row[2]),
            "low": float(row[3]),
            "close": float(row[4]),
            "volume": float(row[5]),
        }
        for row in data
    ]


async def _fetch_bybit_klines(session: aiohttp.ClientSession, symbol: str, interval: str, limit: int) -> list[dict]:
    url = f"{BYBIT_FUTURES_REST}/v5/market/kline"
    params = {"category": "linear", "symbol": symbol, "interval": interval, "limit": limit}
    async with session.get(url, params=params) as resp:
        resp.raise_for_status()
        data = await resp.json()

    if data.get("retCode") != 0:
        logger.error(f"Bybit klines ошибка ({symbol}): {data.get('retMsg')}")
        return []

    candles = [
        {
            "open_time": int(row[0]),
            "open": float(row[1]),
            "high": float(row[2]),
            "low": float(row[3]),
            "close": float(row[4]),
            "volume": float(row[5]),
        }
        for row in data["result"]["list"]
    ]
    candles.sort(key=lambda c: c["open_time"])  # Bybit отдаёт новые свечи первыми
    return candles


async def fetch_klines(
    session: aiohttp.ClientSession, exchange: str, symbol: str, interval: str, limit: int = 100
) -> list[dict]:
    """
    interval — в формате Binance: '15m', '1h', '4h' (для Bybit конвертируется автоматически).
    """
    if exchange == "Binance":
        return await _fetch_binance_klines(session, symbol, interval, limit)
    if exchange == "Bybit":
        bybit_interval = _BYBIT_INTERVAL_MAP[interval]
        return await _fetch_bybit_klines(session, symbol, bybit_interval, limit)
    raise ValueError(f"Неизвестная биржа: {exchange}")


async def _fetch_binance_funding_rate(session: aiohttp.ClientSession, symbol: str) -> float:
    url = f"{BINANCE_FUTURES_REST}/fapi/v1/premiumIndex"
    params = {"symbol": symbol}
    async with session.get(url, params=params) as resp:
        resp.raise_for_status()
        data = await resp.json()
    return float(data["lastFundingRate"])


async def _fetch_bybit_funding_rate(session: aiohttp.ClientSession, symbol: str) -> float:
    url = f"{BYBIT_FUTURES_REST}/v5/market/tickers"
    params = {"category": "linear", "symbol": symbol}
    async with session.get(url, params=params) as resp:
        resp.raise_for_status()
        data = await resp.json()

    if data.get("retCode") != 0:
        logger.error(f"Bybit funding rate ошибка ({symbol}): {data.get('retMsg')}")
        return 0.0

    tickers = data["result"]["list"]
    if not tickers:
        return 0.0
    return float(tickers[0]["fundingRate"])


async def fetch_funding_rate(session: aiohttp.ClientSession, exchange: str, symbol: str) -> float:
    """Текущий funding rate в долях (0.0001 = 0.01%)."""
    if exchange == "Binance":
        return await _fetch_binance_funding_rate(session, symbol)
    if exchange == "Bybit":
        return await _fetch_bybit_funding_rate(session, symbol)
    raise ValueError(f"Неизвестная биржа: {exchange}")
