"""
Telethon-листенер стороннего Telegram-канала с сигналами (см. спеку
docs/superpowers/specs/2026-10-04-channel-signal-autotrading-design.md).

on_channel_message() -- тестируемое ядро без сетевой Telethon-обвязки.
run_channel_signal_listener() -- бесконечная задача для asyncio.gather в main.py,
с собственным retry-циклом: обрыв сессии/сети не должен ронять остальные задачи бота.
"""
import asyncio
import logging

import aiohttp
from telethon import TelegramClient, events

import live_trading
from channel_signal_parser import parse_channel_signal
from config import ADMIN_CHAT_ID, CHANNEL_SIGNAL_SOURCE_ID, TG_API_ID, TG_API_HASH, TG_CHANNEL_SESSION_PATH

logger = logging.getLogger(__name__)


async def on_channel_message(session, text: str | None) -> dict | None:
    """Распознаёт сигнал и передаёт в handle_channel_signal. Возвращает None, если
    текст не распознан как сигнал типа A/B (включая тип C и постороннюю переписку)."""
    parsed = parse_channel_signal(text)
    if parsed is None:
        if text:
            logger.info(f"channel_signal: не распознано: {text[:200]!r}")
        return None
    return await live_trading.handle_channel_signal(session, ADMIN_CHAT_ID, parsed.ticker, parsed.direction)


async def run_channel_signal_listener():
    """Подключается к Telegram под пользовательской сессией и слушает
    CHANNEL_SIGNAL_SOURCE_ID. Обрыв соединения -- переподключение через 30с,
    не роняя остальные задачи asyncio.gather в main.py."""
    client = TelegramClient(TG_CHANNEL_SESSION_PATH, TG_API_ID, TG_API_HASH)

    @client.on(events.NewMessage(chats=CHANNEL_SIGNAL_SOURCE_ID))
    async def _handler(event):
        async with aiohttp.ClientSession() as session:
            try:
                await on_channel_message(session, event.message.text)
            except Exception as e:
                logger.error(f"channel_signal: ошибка обработки сообщения: {e}")

    while True:
        try:
            await client.start()
            logger.info("channel_signal_listener: подключен, слушаю канал")
            await client.run_until_disconnected()
        except Exception as e:
            logger.error(f"channel_signal_listener: соединение оборвалось, переподключение через 30с: {e}")
            await asyncio.sleep(30)
