"""
Telegram-онбординг профиля автотрейдинга.

Флоу: /trading_setup -> [Рекомендуемые параметры] или [Настроить вручную]
Ручной путь: риск% -> дневной лимит убытка% -> плечо -> метод SL ->
             после какого TP безубыток+ -> деление TP1-3 -> (предупреждение
             о риске, если нужно) -> API-ключ(и) биржи -> готово.
Дефолтный путь: сразу сохраняет DEFAULT_PROFILE, дальше только API-ключ(и).

Состояние диалога хранится в памяти (как _onboarding в tg-forex-signal-monitor) —
теряется при рестарте бота, пользователь просто начинает заново командой /trading_setup.
"""

import logging

from notifier import send_text, send_text_with_keyboard
import trading_storage

logger = logging.getLogger(__name__)

_onboarding: dict[int, dict] = {}

DEFAULT_PROFILE = {
    "risk_percent": 1.0,
    "daily_loss_limit_percent": 5.0,
    "leverage": 3.0,
    "sl_method": "atr",
    "sl_fixed_percent": None,
    "breakeven_after_tp": 2,
    "tp_split_preset": "equal",
    "max_concurrent_trades": 3,
}

RISK_WARNING_THRESHOLDS = {
    "risk_percent": 3.0,
    "leverage": 10.0,
    "daily_loss_limit_percent": 10.0,
}

TP_SPLIT_PRESETS = {
    "equal": (25, 25, 25),
    "conservative": (40, 30, 20),
    "aggressive": (15, 20, 25),
}


def _parse_positive_float(text: str) -> float | None:
    try:
        value = float(text.strip().replace(",", "."))
    except ValueError:
        return None
    if value <= 0:
        return None
    return value


async def start_trading_setup(session, chat_id: int):
    await send_text_with_keyboard(
        session, chat_id,
        "⚙️ *Настройка автотрейдинга*\n\n"
        "Можешь использовать рекомендуемые параметры бота (риск 1% на сделку, "
        "плечо 3x, до 3 одновременных сделок, дневной лимит убытка 5%), "
        "или настроить всё вручную.",
        [
            [{"text": "✅ Рекомендуемые параметры бота", "callback_data": "trading_setup:defaults"}],
            [{"text": "🛠 Настроить вручную", "callback_data": "trading_setup:manual"}],
        ],
    )


async def _apply_defaults_and_ask_api_key(session, chat_id: int):
    trading_storage.save_profile(
        chat_id=chat_id,
        risk_percent=DEFAULT_PROFILE["risk_percent"],
        daily_loss_limit_percent=DEFAULT_PROFILE["daily_loss_limit_percent"],
        leverage=DEFAULT_PROFILE["leverage"],
        sl_method=DEFAULT_PROFILE["sl_method"],
        sl_fixed_percent=DEFAULT_PROFILE["sl_fixed_percent"],
        breakeven_after_tp=DEFAULT_PROFILE["breakeven_after_tp"],
        tp_split_preset=DEFAULT_PROFILE["tp_split_preset"],
        max_concurrent_trades=DEFAULT_PROFILE["max_concurrent_trades"],
    )
    _onboarding[chat_id] = {"step": "api_binance_key", "data": {}}
    await send_text(
        session, chat_id,
        "Параметры сохранены ✅\n\n"
        "🔑 Теперь укажи API-ключ Binance Futures (без прав вывода средств, "
        "только торговля). Пришли ключ отдельным сообщением:",
    )


async def _start_manual_flow(session, chat_id: int):
    _onboarding[chat_id] = {"step": "risk_percent", "data": {}}
    await send_text(
        session, chat_id,
        "1️⃣ Какой % от депозита рисковать на одну сделку?\n\n"
        "Рекомендуем 1%. Напиши цифру (без символа %):",
    )


async def handle_callback(session, chat_id: int, callback_data: str) -> bool:
    if callback_data == "trading_setup:defaults":
        await _apply_defaults_and_ask_api_key(session, chat_id)
        return True
    if callback_data == "trading_setup:manual":
        await _start_manual_flow(session, chat_id)
        return True
    return False


async def _handle_risk_percent(session, chat_id: int, state: dict, text: str) -> bool:
    value = _parse_positive_float(text)
    if value is None:
        await send_text(session, chat_id, "Не похоже на число. Напиши цифру, например: 1")
        return True
    state["data"]["risk_percent"] = value
    state["step"] = "daily_loss_limit_percent"
    await send_text(
        session, chat_id,
        "2️⃣ Дневной лимит убытка (% от депозита), после которого торговля "
        "останавливается на день.\n\nРекомендуем 5%. Напиши цифру:",
    )
    return True


async def _handle_daily_loss_limit(session, chat_id: int, state: dict, text: str) -> bool:
    value = _parse_positive_float(text)
    if value is None:
        await send_text(session, chat_id, "Не похоже на число. Напиши цифру, например: 5")
        return True
    state["data"]["daily_loss_limit_percent"] = value
    state["step"] = "leverage"
    await send_text(
        session, chat_id,
        "3️⃣ Какое плечо использовать по умолчанию на фьючерсных позициях?\n\n"
        "Рекомендуем 3x (высокое плечо на развороте манипуляции рискованно). "
        "Напиши цифру:",
    )
    return True


async def _handle_leverage(session, chat_id: int, state: dict, text: str) -> bool:
    value = _parse_positive_float(text)
    if value is None:
        await send_text(session, chat_id, "Не похоже на число. Напиши цифру, например: 3")
        return True
    state["data"]["leverage"] = value
    state["step"] = "sl_method"
    await send_text_with_keyboard(
        session, chat_id,
        "4️⃣ Какой метод стоп-лосса использовать?",
        [
            [{"text": "📈 ATR-адаптивный (рекомендуем)", "callback_data": "sl_method:atr"}],
            [{"text": "🔢 Фиксированный %", "callback_data": "sl_method:fixed"}],
        ],
    )
    return True


_TEXT_STEP_HANDLERS = {
    "risk_percent": _handle_risk_percent,
    "daily_loss_limit_percent": _handle_daily_loss_limit,
    "leverage": _handle_leverage,
}


async def handle_text(session, chat_id: int, text: str) -> bool:
    state = _onboarding.get(chat_id)
    if state is None:
        return False
    handler = _TEXT_STEP_HANDLERS.get(state["step"])
    if handler is None:
        return False
    return await handler(session, chat_id, state, text)
