"""
Обработка команд бота через getUpdates (long polling).
Работает в отдельной asyncio-задаче параллельно с WebSocket-мониторингом.
"""

import asyncio
import logging
import aiohttp

from config import TELEGRAM_TOKEN, IMPULSE_START_THRESHOLD, IMPULSE_STEP, WINDOW_MINUTES, MIN_DAILY_VOLUME_USDT
from storage import add_subscriber, remove_subscriber, is_subscribed, count_subscribers
from notifier import send_text

logger = logging.getLogger(__name__)

TG_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

WELCOME_TEXT = (
    "👋 *Привет\\!*\n\n"
    "Я мониторю фьючерсы Binance и присылаю сигнал, когда любая пара "
    f"даёт импульс от *{IMPULSE_START_THRESHOLD:.0f}%* за {WINDOW_MINUTES} минут "
    f"\\(в любую сторону\\), а затем каждые *{IMPULSE_STEP:.0f}%* дальше\\.\n\n"
    "Команды:\n"
    "/start — подписаться на алерты\n"
    "/stop — отписаться\n"
    "/status — текущие настройки и статус подписки"
)


async def _get_updates(session: aiohttp.ClientSession, offset: int) -> list[dict]:
    url = f"{TG_API}/getUpdates"
    params = {"offset": offset, "timeout": 30}
    try:
        async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=40)) as resp:
            data = await resp.json()
            if data.get("ok"):
                return data["result"]
    except asyncio.TimeoutError:
        pass
    except Exception as e:
        logger.error(f"Ошибка getUpdates: {e}")
    return []


async def _handle_command(session: aiohttp.ClientSession, chat_id: int, text: str):
    text = text.strip().lower()

    if text.startswith("/start"):
        add_subscriber(chat_id)
        await send_text(session, chat_id, WELCOME_TEXT)
        logger.info(f"Новый подписчик: {chat_id} (всего: {count_subscribers()})")

    elif text.startswith("/stop") or text.startswith("/unsubscribe"):
        remove_subscriber(chat_id)
        await send_text(session, chat_id, "❌ Вы отписались от алертов\\. Чтобы вернуться — /start")
        logger.info(f"Отписка: {chat_id} (всего: {count_subscribers()})")

    elif text.startswith("/status"):
        subscribed = is_subscribed(chat_id)
        status_line = "✅ Вы подписаны" if subscribed else "⛔ Вы не подписаны (/start чтобы подписаться)"
        msg = (
            f"{status_line}\n\n"
            f"*Текущие настройки:*\n"
            f"Старт сигнала: {IMPULSE_START_THRESHOLD:.0f}%\n"
            f"Шаг повторных сигналов: {IMPULSE_STEP:.0f}%\n"
            f"Окно расчёта: {WINDOW_MINUTES} мин\n"
            f"Мин\\. дневной объём: ${MIN_DAILY_VOLUME_USDT:,.0f}\n"
            f"Всего подписчиков: {count_subscribers()}"
        )
        await send_text(session, chat_id, msg)


async def run_command_listener(session: aiohttp.ClientSession):
    """Бесконечный цикл long polling для обработки команд пользователей."""
    offset = 0
    logger.info("Слушатель команд запущен")
    while True:
        updates = await _get_updates(session, offset)
        for update in updates:
            offset = update["update_id"] + 1
            message = update.get("message")
            if not message or "text" not in message:
                continue
            chat_id = message["chat"]["id"]
            await _handle_command(session, chat_id, message["text"])
