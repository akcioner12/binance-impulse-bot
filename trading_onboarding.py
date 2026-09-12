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
    if callback_data.startswith("sl_method:"):
        return await _handle_sl_method_callback(session, chat_id, callback_data.split(":", 1)[1])
    if callback_data.startswith("tp_split:"):
        return await _handle_tp_split_preset_callback(session, chat_id, callback_data.split(":", 1)[1])
    if callback_data.startswith("risk_warn:"):
        return await _handle_risk_warning_callback(session, chat_id, callback_data.split(":", 1)[1])
    if callback_data.startswith("add_bybit:"):
        return await _handle_add_bybit_callback(session, chat_id, callback_data.split(":", 1)[1])
    return False


async def _handle_sl_method_callback(session, chat_id: int, method: str) -> bool:
    state = _onboarding.get(chat_id)
    if state is None or state["step"] != "sl_method":
        return False
    if method == "atr":
        state["data"]["sl_method"] = "atr"
        state["data"]["sl_fixed_percent"] = None
        state["step"] = "breakeven_after_tp"
        await _ask_breakeven_step(session, chat_id)
    elif method == "fixed":
        state["data"]["sl_method"] = "fixed_percent"
        state["step"] = "sl_fixed_percent"
        await send_text(session, chat_id, "Какой фиксированный % стоп-лосса от средней цены входа?\n\nНапиши цифру:")
    else:
        return False
    return True


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


async def _handle_sl_fixed_percent(session, chat_id: int, state: dict, text: str) -> bool:
    value = _parse_positive_float(text)
    if value is None:
        await send_text(session, chat_id, "Не похоже на число. Напиши цифру, например: 4")
        return True
    state["data"]["sl_fixed_percent"] = value
    state["step"] = "breakeven_after_tp"
    await _ask_breakeven_step(session, chat_id)
    return True


async def _ask_breakeven_step(session, chat_id: int):
    await send_text(
        session, chat_id,
        "5️⃣ После какого тейк-профита переносить стоп в безубыток+ "
        "(покрытие комиссий, не просто ноль)?\n\n"
        "Рекомендуем: после TP2. Напиши номер тейка (целое число):",
    )


async def _handle_breakeven_after_tp(session, chat_id: int, state: dict, text: str) -> bool:
    value = _parse_positive_float(text)
    if value is None or value != int(value):
        await send_text(session, chat_id, "Нужно целое число тейка, например: 2")
        return True
    state["data"]["breakeven_after_tp"] = int(value)
    state["step"] = "tp_split_preset"
    await send_text_with_keyboard(
        session, chat_id,
        "6️⃣ Как делить позицию между TP1-3? (TP4 — трейлинг, остаток позиции)",
        [
            [{"text": "⚖️ Поровну  25/25/25", "callback_data": "tp_split:equal"}],
            [{"text": "🛡 Консервативно  40/30/20", "callback_data": "tp_split:conservative"}],
            [{"text": "🚀 Агрессивно  15/20/25", "callback_data": "tp_split:aggressive"}],
        ],
    )
    return True


def _find_risk_warnings(data: dict) -> dict:
    """Возвращает {поле: (значение, порог)} для полей, превышающих консервативные границы."""
    warnings = {}
    for field, threshold in RISK_WARNING_THRESHOLDS.items():
        value = data.get(field)
        if value is not None and value > threshold:
            warnings[field] = (value, threshold)
    return warnings


_FIELD_LABELS = {
    "risk_percent": "риск на сделку",
    "leverage": "плечо",
    "daily_loss_limit_percent": "дневной лимит убытка",
}


async def _save_profile_from_data(chat_id: int, data: dict):
    trading_storage.save_profile(
        chat_id=chat_id,
        risk_percent=data["risk_percent"],
        daily_loss_limit_percent=data["daily_loss_limit_percent"],
        leverage=data["leverage"],
        sl_method=data["sl_method"],
        sl_fixed_percent=data.get("sl_fixed_percent"),
        breakeven_after_tp=data["breakeven_after_tp"],
        tp_split_preset=data["tp_split_preset"],
        max_concurrent_trades=DEFAULT_PROFILE["max_concurrent_trades"],
    )


async def _ask_first_api_key_step(session, chat_id: int, state: dict):
    state["step"] = "api_binance_key"
    await send_text(
        session, chat_id,
        "🔑 Теперь укажи API-ключ Binance Futures (без прав вывода средств, "
        "только торговля). Пришли ключ отдельным сообщением:",
    )


async def _handle_tp_split_preset_callback(session, chat_id: int, preset: str) -> bool:
    state = _onboarding.get(chat_id)
    if state is None or state["step"] != "tp_split_preset":
        return False
    state["data"]["tp_split_preset"] = preset
    warnings = _find_risk_warnings(state["data"])
    if warnings:
        state["step"] = "risk_warning_confirm"
        lines = [
            f"⚠️ {_FIELD_LABELS[field]}: {value:g} (рекомендуем не выше {threshold:g})"
            for field, (value, threshold) in warnings.items()
        ]
        await send_text_with_keyboard(
            session, chat_id,
            "⚠️ *Обнаружен повышенный риск в твоих настройках:*\n\n" + "\n".join(lines) +
            "\n\nПонизить до рекомендуемых значений, или оставить как есть?",
            [
                [{"text": "✅ Применить рекомендации", "callback_data": "risk_warn:apply_recommended"}],
                [{"text": "➡️ Оставить как есть", "callback_data": "risk_warn:keep_mine"}],
            ],
        )
        return True
    await _save_profile_from_data(chat_id, state["data"])
    await _ask_first_api_key_step(session, chat_id, state)
    return True


async def _handle_risk_warning_callback(session, chat_id: int, choice: str) -> bool:
    state = _onboarding.get(chat_id)
    if state is None or state["step"] != "risk_warning_confirm":
        return False
    if choice == "apply_recommended":
        for field, threshold in RISK_WARNING_THRESHOLDS.items():
            if state["data"].get(field, 0) > threshold:
                state["data"][field] = threshold
    await _save_profile_from_data(chat_id, state["data"])
    await _ask_first_api_key_step(session, chat_id, state)
    return True


async def _handle_api_binance_key(session, chat_id: int, state: dict, text: str) -> bool:
    state["data"]["binance_api_key"] = text.strip()
    state["step"] = "api_binance_secret"
    await send_text(session, chat_id, "Теперь API-секрет Binance:")
    return True


async def _handle_api_binance_secret(session, chat_id: int, state: dict, text: str) -> bool:
    trading_storage.save_api_credentials(
        chat_id, "binance", state["data"]["binance_api_key"], text.strip()
    )
    state["step"] = "add_bybit_choice"
    await send_text_with_keyboard(
        session, chat_id,
        "Ключ Binance сохранён ✅\n\nДобавить также API-ключ Bybit Futures?",
        [
            [{"text": "➕ Добавить Bybit", "callback_data": "add_bybit:yes"}],
            [{"text": "➡️ Пропустить", "callback_data": "add_bybit:no"}],
        ],
    )
    return True


async def _handle_api_bybit_key(session, chat_id: int, state: dict, text: str) -> bool:
    state["data"]["bybit_api_key"] = text.strip()
    state["step"] = "api_bybit_secret"
    await send_text(session, chat_id, "Теперь API-секрет Bybit:")
    return True


async def _handle_api_bybit_secret(session, chat_id: int, state: dict, text: str) -> bool:
    trading_storage.save_api_credentials(
        chat_id, "bybit", state["data"]["bybit_api_key"], text.strip()
    )
    del _onboarding[chat_id]
    await send_text(session, chat_id, "Ключ Bybit сохранён ✅\n\n🎉 Автотрейдинг готов к работе.")
    return True


async def _handle_add_bybit_callback(session, chat_id: int, choice: str) -> bool:
    state = _onboarding.get(chat_id)
    if state is None or state["step"] != "add_bybit_choice":
        return False
    if choice == "yes":
        state["step"] = "api_bybit_key"
        await send_text(session, chat_id, "🔑 Укажи API-ключ Bybit Futures:")
        return True
    if choice == "no":
        del _onboarding[chat_id]
        await send_text(session, chat_id, "🎉 Автотрейдинг готов к работе.")
        return True
    return False


_TEXT_STEP_HANDLERS = {
    "risk_percent": _handle_risk_percent,
    "daily_loss_limit_percent": _handle_daily_loss_limit,
    "leverage": _handle_leverage,
    "sl_fixed_percent": _handle_sl_fixed_percent,
    "breakeven_after_tp": _handle_breakeven_after_tp,
    "api_binance_key": _handle_api_binance_key,
    "api_binance_secret": _handle_api_binance_secret,
    "api_bybit_key": _handle_api_bybit_key,
    "api_bybit_secret": _handle_api_bybit_secret,
}


async def handle_text(session, chat_id: int, text: str) -> bool:
    state = _onboarding.get(chat_id)
    if state is None:
        return False
    handler = _TEXT_STEP_HANDLERS.get(state["step"])
    if handler is None:
        return False
    return await handler(session, chat_id, state, text)
