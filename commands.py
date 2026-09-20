"""
Обработка команд бота через getUpdates (long polling).
Работает в отдельной asyncio-задаче параллельно с WebSocket-мониторингом.
"""

import asyncio
import logging
import aiohttp

from config import TELEGRAM_TOKEN, IMPULSE_START_THRESHOLD, IMPULSE_STEP, WINDOW_MINUTES, MIN_DAILY_VOLUME_USDT, ADMIN_CHAT_ID
from storage import add_subscriber, remove_subscriber, is_subscribed, count_subscribers, get_all_subscribers
from notifier import send_text, send_text_with_keyboard, answer_callback_query, get_chat_info
from trading_onboarding import (
    start_trading_setup,
    handle_callback as onboarding_handle_callback,
    handle_text as onboarding_handle_text,
)
import trading_storage
import emergency_controls
import live_trading

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

    elif stripped.startswith("/emergency"):
        if chat_id != ADMIN_CHAT_ID:
            return
        await _handle_emergency_command(session, chat_id)

    elif stripped.startswith("/reset_paper_balance"):
        if chat_id != ADMIN_CHAT_ID:
            return
        await send_text_with_keyboard(
            session, chat_id,
            "⚠️ Это сотрёт весь paper-trading (баланс, позиции, историю сигналов) и начнёт заново с $10 000. Подтвердить?",
            [[{"text": "✅ Подтвердить сброс", "callback_data": "reset_balance:confirm"}]],
        )

    elif stripped.startswith("/subscribers"):
        if chat_id != ADMIN_CHAT_ID:
            return
        await _handle_subscribers_command(session, chat_id)

    elif stripped.startswith("/set_max_trades"):
        if chat_id != ADMIN_CHAT_ID:
            return
        await _handle_set_max_trades_command(session, chat_id, stripped)

    elif stripped.startswith("/close_position"):
        if chat_id != ADMIN_CHAT_ID:
            return
        await _handle_close_position_command(session, chat_id, stripped)


async def _handle_emergency_command(session: aiohttp.ClientSession, chat_id: int):
    profile = trading_storage.get_profile(chat_id)
    is_active = profile["is_active"] if profile else 1
    if is_active:
        toggle_button = {"text": "⏸ Остановить торговлю", "callback_data": "emergency:stop"}
    else:
        toggle_button = {"text": "▶️ Возобновить торговлю", "callback_data": "emergency:start"}

    await send_text_with_keyboard(
        session, chat_id,
        "🚨 *Аварийные контролы автотрейдинга*",
        [
            [toggle_button],
            [{"text": "🔴 Закрыть все позиции сейчас", "callback_data": "emergency:close_all"}],
            [{"text": "🛡 Перенести все в безубыток+", "callback_data": "emergency:breakeven_all"}],
        ],
    )


async def _handle_emergency_callback(session: aiohttp.ClientSession, chat_id: int, action: str):
    if action == "stop":
        emergency_controls.stop_trading(chat_id)
        await send_text(session, chat_id, "⏸ Торговля остановлена. Открытые позиции продолжают управляться штатно.")
    elif action == "start":
        emergency_controls.start_trading(chat_id)
        await send_text(session, chat_id, "▶️ Торговля возобновлена.")
    elif action == "close_all":
        symbols = emergency_controls.close_all_positions_now(chat_id)
        if symbols:
            await send_text(session, chat_id, f"🔴 Закрытие запущено: {', '.join(symbols)} (сработает на ближайшем тике).")
        else:
            await send_text(session, chat_id, "Открытых позиций нет.")
    elif action == "breakeven_all":
        symbols = emergency_controls.move_all_to_breakeven_plus_now(chat_id)
        if symbols:
            await send_text(session, chat_id, f"🛡 Перенесено в безубыток+: {', '.join(symbols)}.")
        else:
            await send_text(session, chat_id, "Нет позиций для переноса (открытых нет или уже на трейлинге).")


def _escape_markdown(text: str) -> str:
    """
    Экранирует спецсимволы legacy Telegram Markdown (_ * ` [) -- прод-баг
    14.09.2026: юзернейм/имя с "_" ломал парсинг ("can't parse entities"),
    и вся команда /subscribers молча падала на отправке.
    """
    for ch in ("_", "*", "`", "["):
        text = text.replace(ch, f"\\{ch}")
    return text


def _format_subscriber_line(chat_id: int, info: dict | None) -> str:
    if info is None:
        return f"`{chat_id}` — (не удалось получить профиль)"
    username = info.get("username")
    if username:
        username = _escape_markdown(username)
    name = " ".join(part for part in [info.get("first_name"), info.get("last_name")] if part)
    if name:
        name = _escape_markdown(name)
    if username and name:
        return f"`{chat_id}` — @{username} ({name})"
    if username:
        return f"`{chat_id}` — @{username}"
    if name:
        return f"`{chat_id}` — {name}"
    return f"`{chat_id}` — (нет данных профиля)"


async def _handle_subscribers_command(session: aiohttp.ClientSession, chat_id: int):
    subscriber_ids = get_all_subscribers()
    if not subscriber_ids:
        await send_text(session, chat_id, "Подписчиков нет.")
        return

    lines = []
    for sub_id in subscriber_ids:
        info = await get_chat_info(session, sub_id)
        lines.append(_format_subscriber_line(sub_id, info))

    text = f"*Подписчики ({len(subscriber_ids)}):*\n\n" + "\n".join(lines)
    await send_text(session, chat_id, text)


async def _handle_set_max_trades_command(session: aiohttp.ClientSession, chat_id: int, stripped: str):
    parts = stripped.split()
    if len(parts) != 2:
        await send_text(session, chat_id, "Использование: `/set_max_trades N` (например, `/set_max_trades 10`)")
        return
    try:
        value = int(parts[1])
    except ValueError:
        await send_text(session, chat_id, "Нужно целое число, например `/set_max_trades 10`.")
        return
    if value <= 0:
        await send_text(session, chat_id, "Число должно быть больше нуля.")
        return

    trading_storage.update_max_concurrent_trades(chat_id, value)
    await send_text(session, chat_id, f"✅ Максимум одновременных сделок: {value}.")


async def _handle_close_position_command(session: aiohttp.ClientSession, chat_id: int, stripped: str):
    parts = stripped.split()
    if len(parts) != 2:
        await send_text(session, chat_id, "Использование: `/close_position SYMBOL` (например, `/close_position KOMAUSDT`)")
        return

    symbol = parts[1].upper()
    closed = emergency_controls.close_position_now(chat_id, symbol)
    if closed:
        await send_text(session, chat_id, f"🔴 Закрытие {symbol} запущено (сработает на ближайшем тике).")
    else:
        await send_text(session, chat_id, f"Открытой позиции по {symbol} нет.")


async def _handle_callback_query(session: aiohttp.ClientSession, callback_query: dict):
    callback_id = callback_query["id"]
    data = callback_query.get("data", "")
    chat_id = callback_query["message"]["chat"]["id"]

    if data.startswith("emergency:"):
        action = data.split(":", 1)[1]
        await _handle_emergency_callback(session, chat_id, action)
    elif data == "reset_balance:confirm":
        live_trading.reset_all_state(chat_id, starting_balance=10000.0)
        await send_text(session, chat_id, "✅ Paper-trading сброшен. Баланс: $10 000.00.")
    else:
        await onboarding_handle_callback(session, chat_id, data)

    await answer_callback_query(session, callback_id)


async def _process_updates_once(session: aiohttp.ClientSession, offset: int) -> int:
    """
    Забирает и обрабатывает одну пачку апдейтов. Возвращает новый offset.
    Необработанное исключение при обработке ОДНОГО апдейта не должно рушить
    весь цикл long polling (прод-инцидент 14.09.2026: без этого один сбойный
    колбэк мог молча "убить" обработку всех последующих команд/кнопок).
    """
    updates = await _get_updates(session, offset)
    for update in updates:
        offset = update["update_id"] + 1

        try:
            callback_query = update.get("callback_query")
            if callback_query:
                await _handle_callback_query(session, callback_query)
                continue

            message = update.get("message")
            if not message or "text" not in message:
                continue
            chat_id = message["chat"]["id"]
            await _handle_command(session, chat_id, message["text"])
        except Exception as e:
            logger.error(f"Ошибка обработки апдейта {update.get('update_id')}: {e}", exc_info=True)
    return offset


async def run_command_listener(session: aiohttp.ClientSession):
    """Бесконечный цикл long polling для обработки команд пользователей."""
    offset = 0
    logger.info("Слушатель команд запущен")
    while True:
        offset = await _process_updates_once(session, offset)
