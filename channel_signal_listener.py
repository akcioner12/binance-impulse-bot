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
    """
    Подключается к Telegram под пользовательской сессией и слушает
    CHANNEL_SIGNAL_SOURCE_ID. Клиент создаётся заново на каждой итерации цикла
    (перечитывает файл сессии с диска) -- если сессия ещё не авторизована
    (auth_channel_session.py не запускали или сессия протухла), НЕ вызываем
    интерактивный запуск клиента: на Railway без stdin это либо падает с
    EOFError, либо (если stdin почему-то открыт) блокирует весь event loop на
    input() за номером телефона. Вместо этого connect() + is_user_authorized()
    и ожидание следующей проверки -- после ручного запуска auth-скрипта
    следующая итерация подхватит валидную сессию сама, без рестарта сервиса.
    """
    while True:
        client = None
        try:
            if not TG_API_ID or not TG_API_HASH:
                logger.warning(
                    "channel_signal_listener: TG_API_ID/TG_API_HASH не заданы, повторная проверка через 5 минут"
                )
                await asyncio.sleep(300)
                continue

            client = TelegramClient(TG_CHANNEL_SESSION_PATH, TG_API_ID, TG_API_HASH)
            await client.connect()
            if not await client.is_user_authorized():
                logger.warning(
                    "channel_signal_listener: сессия не авторизована -- запусти "
                    "auth_channel_session.py (railway ssh), повторная проверка через 5 минут"
                )
                await asyncio.sleep(300)
                continue

            @client.on(events.NewMessage(chats=CHANNEL_SIGNAL_SOURCE_ID))
            async def _handler(event):
                async with aiohttp.ClientSession() as session:
                    try:
                        await on_channel_message(session, event.message.raw_text)
                    except Exception as e:
                        logger.exception(f"channel_signal: ошибка обработки сообщения: {e}")

            logger.info("channel_signal_listener: подключен, слушаю канал")
            await client.run_until_disconnected()
        except Exception as e:
            logger.exception(f"channel_signal_listener: соединение оборвалось: {e}")
        finally:
            if client is not None:
                await client.disconnect()
        await asyncio.sleep(30)
