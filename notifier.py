"""
Отправка и редактирование алертов в Telegram.

Логика схлопывания (п.5 договорённостей):
- Первый сигнал по монете -> отправляем новое сообщение, сохраняем message_id.
- Повторный сигнал (следующий уровень) -> редактируем то же сообщение (editMessageText).
- Если редактирование не удалось (сообщение удалено пользователем, прошло >48ч и т.п.)
  -> отправляем новое и обновляем message_id.
"""

import asyncio
import logging
import time
import aiohttp

from config import TELEGRAM_TOKEN, WINDOW_MINUTES
from storage import get_message_id, set_message_id, clear_alert_state
from analyzer import ImpulseSignal, build_exchange_link

logger = logging.getLogger(__name__)

TG_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# Очередь отправки — защита от Telegram rate limit (см. п.5)
_send_queue: asyncio.Queue = asyncio.Queue()
_MIN_DELAY_BETWEEN_SENDS = 0.05  # ~20 сообщений/сек, с запасом от лимита Telegram (30/сек)

_WINDOW_HOURS = WINDOW_MINUTES / 60


def _format_indicator_lines(indicators: dict | None) -> str:
    if not indicators:
        return ""

    lines = []
    if indicators.get("rsi") is not None:
        lines.append(f"📊 RSI(15м): {indicators['rsi']:.1f}")

    volume_change_pct = indicators.get("volume_change_pct")
    volume_vs_avg_ratio = indicators.get("volume_vs_avg_ratio")
    if volume_change_pct is not None or volume_vs_avg_ratio is not None:
        parts = []
        if volume_change_pct is not None:
            parts.append(f"{volume_change_pct:+.1f}% к пред. свече")
        if volume_vs_avg_ratio is not None:
            parts.append(f"×{volume_vs_avg_ratio:.1f} к среднему")
        lines.append(f"📊 Объём (15м): {', '.join(parts)}")

    if indicators.get("funding_rate") is not None:
        lines.append(f"📊 Funding: {indicators['funding_rate'] * 100:+.3f}%")

    if indicators.get("oi_change_pct") is not None:
        lines.append(f"📊 OI: {indicators['oi_change_pct']:+.1f}%")

    if not lines:
        return ""
    return "\n".join(lines) + "\n\n"


def _format_links_line(sig: ImpulseSignal, also_on_bybit: bool) -> str:
    link = build_exchange_link(sig.exchange, sig.symbol)
    line = f"[Открыть на {sig.exchange}]({link})"
    if also_on_bybit and sig.exchange == "Binance":
        bybit_link = build_exchange_link("Bybit", sig.symbol)
        line += f" | [Открыть на Bybit]({bybit_link})"
    return line


def _format_alert_text(sig: ImpulseSignal, indicators: dict | None = None, also_on_bybit: bool = False) -> str:
    arrow = "🚀" if sig.direction == "up" else "🔻"
    word = "РОСТ" if sig.direction == "up" else "ПАДЕНИЕ"
    fire = "🔥" * min(int(sig.level // 30), 3)

    return (
        f"{fire} {arrow} *{sig.symbol}* — {word}\n"
        f"Биржа: *{sig.exchange}*\n"
        f"\n"
        f"Импульс: *{sig.change_pct:+.1f}%* за последние {_WINDOW_HOURS:.0f}ч\n"
        f"Уровень: *{sig.level:.0f}%*\n"
        f"Цена: `{sig.window_start_price:,.6f}` → `{sig.current_price:,.6f}`\n"
        f"\n"
        f"{_format_indicator_lines(indicators)}"
        f"{_format_links_line(sig, also_on_bybit)}\n"
        f"_Обновлено: {time.strftime('%H:%M:%S UTC', time.gmtime())}_"
    )


async def _api_call(session: aiohttp.ClientSession, method: str, payload: dict) -> dict | None:
    """Единая точка вызова Telegram API с обработкой 429 (rate limit)."""
    url = f"{TG_API}/{method}"
    for attempt in range(3):
        try:
            async with session.post(url, json=payload) as resp:
                data = await resp.json()
                if resp.status == 429:
                    retry_after = data.get("parameters", {}).get("retry_after", 5)
                    logger.warning(f"Telegram rate limit, жду {retry_after}с")
                    await asyncio.sleep(retry_after)
                    continue
                if not data.get("ok"):
                    logger.error(f"Telegram API error ({method}): {data}")
                    return None
                return data.get("result")
        except Exception as e:
            logger.error(f"Ошибка вызова Telegram API ({method}): {e}")
            await asyncio.sleep(1)
    return None


async def send_or_edit_alert(
    session: aiohttp.ClientSession, chat_id: int, sig: ImpulseSignal,
    indicators: dict | None = None, also_on_bybit: bool = False,
):
    """
    Отправляет новое сообщение при первом сигнале по монете,
    либо редактирует существующее при повторном (следующий уровень).
    """
    text = _format_alert_text(sig, indicators, also_on_bybit)
    existing_id = get_message_id(sig.symbol, chat_id)

    if existing_id:
        result = await _api_call(session, "editMessageText", {
            "chat_id": chat_id,
            "message_id": existing_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        })
        if result is not None:
            return
        # Редактирование не удалось (сообщение устарело/удалено) — шлём новое
        logger.info(f"Не удалось отредактировать сообщение для {sig.symbol}, отправляю новое")

    result = await _api_call(session, "sendMessage", {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    })
    if result:
        set_message_id(sig.symbol, chat_id, result["message_id"])


async def broadcast_signal(
    session: aiohttp.ClientSession, chat_ids: list[int], sig: ImpulseSignal,
    indicators: dict | None = None, also_on_bybit: bool = False,
):
    """Рассылает сигнал всем подписчикам с защитой от rate limit."""
    for chat_id in chat_ids:
        await send_or_edit_alert(session, chat_id, sig, indicators, also_on_bybit)
        await asyncio.sleep(_MIN_DELAY_BETWEEN_SENDS)


async def send_text(session: aiohttp.ClientSession, chat_id: int, text: str):
    await _api_call(session, "sendMessage", {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
    })


async def send_document(
    session: aiohttp.ClientSession, chat_id: int, filename: str, content: bytes, caption: str | None = None
) -> bool:
    """Отправляет HTML-файл документом (multipart -- _api_call шлёт только JSON)."""
    form = aiohttp.FormData()
    form.add_field("chat_id", str(chat_id))
    if caption:
        form.add_field("caption", caption)
    form.add_field("document", content, filename=filename, content_type="text/html")
    try:
        async with session.post(f"{TG_API}/sendDocument", data=form) as resp:
            data = await resp.json()
    except Exception as e:
        logger.error(f"Ошибка вызова Telegram API (sendDocument): {e}")
        return False
    if not data.get("ok"):
        logger.error(f"Telegram API error (sendDocument): {data}")
        return False
    return True


async def send_text_with_keyboard(
    session: aiohttp.ClientSession, chat_id: int, text: str, keyboard: list[list[dict]]
) -> dict | None:
    """Отправляет сообщение с inline-клавиатурой (для онбординга и аварийных кнопок)."""
    return await _api_call(session, "sendMessage", {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "reply_markup": {"inline_keyboard": keyboard},
    })


_PUBLIC_COMMANDS = [
    {"command": "start", "description": "Подписаться на сигналы"},
    {"command": "stop", "description": "Отписаться от сигналов"},
    {"command": "status", "description": "Текущие настройки и число подписчиков"},
]
_ADMIN_ONLY_COMMANDS = [
    {"command": "trading_setup", "description": "Настроить автотрейдинг"},
    {"command": "emergency", "description": "Аварийные контролы автотрейдинга"},
    {"command": "reset_paper_balance", "description": "Сбросить paper-trading баланс до $10 000"},
    {"command": "subscribers", "description": "Список подписчиков (chat_id + профиль)"},
    {"command": "set_max_trades", "description": "Изменить макс. число одновременных сделок"},
    {"command": "close_position", "description": "Закрыть одну конкретную открытую позицию"},
]


async def set_bot_commands(session: aiohttp.ClientSession, admin_chat_id: int):
    """
    Регистрирует меню команд Telegram ("/" в чате) -- по умолчанию только
    публичные команды, админ видит дополнительно свои (scope на его chat_id).
    Вызывается один раз при старте бота, безопасно вызывать повторно.
    """
    await _api_call(session, "setMyCommands", {"commands": _PUBLIC_COMMANDS})
    await _api_call(session, "setMyCommands", {
        "commands": _PUBLIC_COMMANDS + _ADMIN_ONLY_COMMANDS,
        "scope": {"type": "chat", "chat_id": admin_chat_id},
    })


async def get_chat_info(session: aiohttp.ClientSession, chat_id: int) -> dict | None:
    """Текущий профиль чата (username/first_name/last_name) -- None, если недоступен."""
    return await _api_call(session, "getChat", {"chat_id": chat_id})


async def answer_callback_query(session: aiohttp.ClientSession, callback_query_id: str):
    """Подтверждает получение нажатия inline-кнопки (убирает 'часики' в Telegram)."""
    await _api_call(session, "answerCallbackQuery", {
        "callback_query_id": callback_query_id,
    })
