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


def _format_alert_text(sig: ImpulseSignal) -> str:
    arrow = "🚀" if sig.direction == "up" else "🔻"
    word = "РОСТ" if sig.direction == "up" else "ПАДЕНИЕ"
    fire = "🔥" * min(int(sig.level // 30), 3)
    link = build_exchange_link(sig.exchange, sig.symbol)

    return (
        f"{fire} {arrow} *{sig.symbol}* — {word}\n"
        f"Биржа: *{sig.exchange}*\n"
        f"\n"
        f"Импульс: *{sig.change_pct:+.1f}%* за последние {_WINDOW_HOURS:.0f}ч\n"
        f"Уровень: *{sig.level:.0f}%*\n"
        f"Цена: `{sig.window_start_price:,.6f}` → `{sig.current_price:,.6f}`\n"
        f"\n"
        f"[Открыть на {sig.exchange}]({link})\n"
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


async def send_or_edit_alert(session: aiohttp.ClientSession, chat_id: int, sig: ImpulseSignal):
    """
    Отправляет новое сообщение при первом сигнале по монете,
    либо редактирует существующее при повторном (следующий уровень).
    """
    text = _format_alert_text(sig)
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


async def broadcast_signal(session: aiohttp.ClientSession, chat_ids: list[int], sig: ImpulseSignal):
    """Рассылает сигнал всем подписчикам с защитой от rate limit."""
    for chat_id in chat_ids:
        await send_or_edit_alert(session, chat_id, sig)
        await asyncio.sleep(_MIN_DELAY_BETWEEN_SENDS)


async def send_text(session: aiohttp.ClientSession, chat_id: int, text: str):
    await _api_call(session, "sendMessage", {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
    })
