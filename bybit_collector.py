"""
WebSocket-коллектор Bybit Futures (linear/USDT perpetual).

Протокол Bybit отличается от Binance: вместо комбинированных стримов в URL
нужно подключиться к одному endpoint и отправить JSON-сообщение subscribe
с списком топиков (kline.1.{symbol}). Bybit ограничивает число args в одном
сообщении подписки — поэтому подписываемся пакетами.

callback вызывается при закрытии каждой минутной свечи с (symbol, close_price, timestamp).
"""

import asyncio
import json
import logging
import websockets

from config import BYBIT_FUTURES_WS, BYBIT_SYMBOLS_PER_SUBSCRIBE_BATCH

logger = logging.getLogger(__name__)


def _chunk(lst: list, size: int) -> list[list]:
    return [lst[i:i + size] for i in range(0, len(lst), size)]


async def _subscribe_all(ws, symbols: list[str]):
    for batch in _chunk(symbols, BYBIT_SYMBOLS_PER_SUBSCRIBE_BATCH):
        topics = [f"kline.1.{s}" for s in batch]
        await ws.send(json.dumps({"op": "subscribe", "args": topics}))
        await asyncio.sleep(0.1)  # не флудим подписками подряд


async def stream_bybit_symbols(symbols: list[str], callback):
    """
    Поддерживает одно WS-соединение Bybit для всех переданных символов,
    с автоматическим переподключением при разрыве.
    """
    if not symbols:
        logger.info("Bybit: нет уникальных символов для мониторинга, соединение не открывается")
        return

    while True:
        try:
            async with websockets.connect(
                BYBIT_FUTURES_WS, ping_interval=20, ping_timeout=10
            ) as ws:
                logger.info(f"[bybit-ws] Подключено, подписка на {len(symbols)} пар")
                await _subscribe_all(ws, symbols)

                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                        topic = msg.get("topic", "")
                        if not topic.startswith("kline."):
                            continue  # служебные сообщения (pong, подтверждение подписки)

                        for item in msg.get("data", []):
                            if item.get("confirm"):  # свеча закрыта
                                symbol = topic.split(".")[-1]
                                close_price = float(item["close"])
                                ts = item["timestamp"] // 1000  # ms -> sec
                                await callback(symbol, close_price, ts)

                    except (KeyError, ValueError, json.JSONDecodeError) as e:
                        logger.warning(f"[bybit-ws] Ошибка парсинга сообщения: {e}")

        except (websockets.exceptions.ConnectionClosed, OSError) as e:
            logger.warning(f"[bybit-ws] Соединение разорвано: {e}. Переподключение через 5с.")
            await asyncio.sleep(5)
        except Exception as e:
            logger.exception(f"[bybit-ws] Неожиданная ошибка: {e}. Переподключение через 10с.")
            await asyncio.sleep(10)
