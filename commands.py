"""
Обработка команд бота через getUpdates (long polling).
Работает в отдельной asyncio-задаче параллельно с WebSocket-мониторингом.
"""

import asyncio
import logging
import aiohttp

from config import TELEGRAM_TOKEN, IMPULSE_START_THRESHOLD, IMPULSE_STEP, WINDOW_MINUTES, MIN_DAILY_VOLUME_USDT, ADMIN_CHAT_ID
from storage import add_subscriber, remove_subscriber, is_subscribed, count_subscribers
from notifier import send_text, answer_callback_query
from trading_onboarding import (
    start_trading_setup,
    handle_callback as onboarding_handle_callback,
    handle_text as onboarding_handle_text,
)

logger = logging.getLogger(__name__)

TG_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

WELCOME_TEXT = (
    "👋 *Привет!*\n\n"
    "Я мониторю фьючерсы Binance и Bybit и присылаю сигнал, как только цена "
    f"любой пары изменится от *{IMPULSE_START_THRESHOLD:.0f}%* (в любую сторону) — "
    f"а дальше присылаю новый сигнал на каждые *+{IMPULSE_STEP:.0f}%* движения.\n\n"
    "Команды:\n"
    "/start — подписаться на алерты\n"
    "/stop — отписаться\n"
    "/status — текущие настройки и статус подписки\n"
    "/trading_setup — настроить автотрейдинг"
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
    handled_by_onboarding = await onboarding_handle_text(session, chat_id, text)
    if handled_by_onboarding:
        return

    stripped = text.strip().lower()

    if stripped.startswith("/start"):
        add_subscriber(chat_id)
        await send_text(session, chat_id, WELCOME_TEXT)
        logger.info(f"Новый подписчик: {chat_id} (всего: {count_subscribers()})")

    elif stripped.startswith("/stop") or stripped.startswith("/unsubscribe"):
        remove_subscriber(chat_id)
        await send_text(session, chat_id, "❌ Вы отписались от алертов. Чтобы вернуться — /start")
        logger.info(f"Отписка: {chat_id} (всего: {count_subscribers()})")

    elif stripped.startswith("/status"):
        subscribed = is_subscribed(chat_id)
        status_line = "✅ Вы подписаны" if subscribed else "⛔ Вы не подписаны (/start чтобы подписаться)"
        window_hours = WINDOW_MINUTES / 60
        msg = (
            f"{status_line}\n\n"
            f"*Текущие настройки:*\n"
            f"Старт сигнала: {IMPULSE_START_THRESHOLD:.0f}%\n"
            f"Шаг повторных сигналов: {IMPULSE_STEP:.0f}%\n"
            f"Скользящее окно: {window_hours:.0f}ч (движение может накопиться за любое время внутри этого окна)\n"
            f"Мин. дневной объём: ${MIN_DAILY_VOLUME_USDT:,.0f}\n"
            f"Всего подписчиков: {count_subscribers()}"
        )
        await send_text(session, chat_id, msg)

    elif stripped.startswith("/trading_setup"):
        if chat_id != ADMIN_CHAT_ID:
            await send_text(session, chat_id, "⛔ Эта функция пока недоступна.")
            return
        await start_trading_setup(session, chat_id)


async def _handle_callback_query(session: aiohttp.ClientSession, callback_query: dict):
    callback_id = callback_query["id"]
    data = callback_query.get("data", "")
    chat_id = callback_query["message"]["chat"]["id"]

    await onboarding_handle_callback(session, chat_id, data)
    await answer_callback_query(session, callback_id)


async def _process_updates_once(session: aiohttp.ClientSession, offset: int) -> int:
    """Забирает и обрабатывает одну пачку апдейтов. Возвращает новый offset."""
    updates = await _get_updates(session, offset)
    for update in updates:
        offset = update["update_id"] + 1

        callback_query = update.get("callback_query")
        if callback_query:
            await _handle_callback_query(session, callback_query)
            continue

        message = update.get("message")
        if not message or "text" not in message:
            continue
        chat_id = message["chat"]["id"]
        await _handle_command(session, chat_id, message["text"])
    return offset


async def run_command_listener(session: aiohttp.ClientSession):
    """Бесконечный цикл long polling для обработки команд пользователей."""
    offset = 0
    logger.info("Слушатель команд запущен")
    while True:
        offset = await _process_updates_once(session, offset)
