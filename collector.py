"""
WebSocket-коллектор данных Binance Futures.

Подключается к стримам kline_1m для всех отслеживаемых пар.
Binance ограничивает ~200 потоков на одно соединение — при большом количестве
пар (весь рынок, ~300-400 контрактов) открываем несколько соединений параллельно.

callback вызывается при закрытии каждой минутной свечи с (symbol, close_price, timestamp).
"""

import asyncio
import json
import logging
import websockets

from config import BINANCE_FUTURES_WS, SYMBOLS_PER_WS_CONNECTION

logger = logging.getLogger(__name__)


def _chunk(lst: list, size: int) -> list[list]:
    return [lst[i:i + size] for i in range(0, len(lst), size)]


async def _run_connection(symbols: list[str], callback, conn_id: int):
    """Поддерживает одно WS-соединение с автоматическим переподключением."""
    streams = "/".join(f"{s.lower()}@kline_1m" for s in symbols)
    url = f"{BINANCE_FUTURES_WS}/stream?streams={streams}"

    while True:
        try:
            async with websockets.connect(url, ping_interval=180, ping_timeout=600) as ws:
                logger.info(f"[ws-{conn_id}] Подключено, {len(symbols)} пар")
                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                        k = msg["data"]["k"]
                        if k["x"]:  # свеча закрыта
                            symbol = k["s"]
                            close_price = float(k["c"])
                            ts = k["T"] // 1000  # ms -> sec
                            await callback(symbol, close_price, ts)
                    except (KeyError, ValueError, json.JSONDecodeError) as e:
                        logger.warning(f"[ws-{conn_id}] Ошибка парсинга сообщения: {e}")

        except (websockets.exceptions.ConnectionClosed, OSError) as e:
            logger.warning(f"[ws-{conn_id}] Соединение разорвано: {e}. Переподключение через 5с.")
            await asyncio.sleep(5)
        except Exception as e:
            logger.exception(f"[ws-{conn_id}] Неожиданная ошибка: {e}. Переподключение через 10с.")
            await asyncio.sleep(10)


async def stream_all_symbols(symbols: list[str], callback):
    """
    Запускает столько WS-соединений, сколько нужно, чтобы покрыть все символы
    (Binance лимитирует число потоков на соединение).
    """
    chunks = _chunk(symbols, SYMBOLS_PER_WS_CONNECTION)
    logger.info(f"Открываю {len(chunks)} WS-соединений для {len(symbols)} пар")

    tasks = [
        _run_connection(chunk, callback, i)
        for i, chunk in enumerate(chunks)
    ]
    await asyncio.gather(*tasks)
