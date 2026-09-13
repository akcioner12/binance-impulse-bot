"""
Telegram-онбординг профиля автотрейдинга.

Флоу: /trading_setup -> [Рекомендуемые параметры] или [Настроить вручную]
Ручной путь: риск% -> дневной лимит убытка% -> плечо -> метод SL ->
             после какого TP безубыток+ -> деление TP1-3 -> (предупреждение
             о риске, если нужно) -> выбор биржи -> ключ+секрет -> (добавить
             вторую биржу? да/нет) -> готово.
Дефолтный путь: сразу сохраняет DEFAULT_PROFILE, дальше только выбор биржи.

Пользователь сам выбирает, с какой биржи начать (Binance или Bybit) -- это
важно, т.к. Binance недоступен в России и часть пользователей пользуется
только Bybit. После ввода ключей первой выбранной биржи бот предлагает
кнопкой добавить и вторую (с возможностью пропустить кнопкой, без ввода
текста).

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

DEFAULT_PAPER_BALANCE = 10000.0

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


_EXCHANGE_LABELS = {"binance": "Binance", "bybit": "Bybit"}


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
    state = {"step": None, "data": {}}
    _onboarding[chat_id] = state
    await _ask_exchange_choice_step(session, chat_id, state, prefix="Параметры сохранены ✅\n\n")


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
    if callback_data.startswith("exchange_choice:"):
        return await _handle_exchange_choice_callback(session, chat_id, callback_data.split(":", 1)[1])
    if callback_data.startswith("add_other_exchange:"):
        return await _handle_add_other_exchange_callback(session, chat_id, callback_data.split(":", 1)[1])
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
        "4️⃣ Стоп-лосс — это уровень цены, на котором сделка автоматически закроется "
        "с небольшим убытком, если цена пойдёт не в нашу сторону. Как его рассчитывать?\n\n"
        "📈 Автоматически (рекомендуем) — бот сам подбирает расстояние до стопа "
        "по волатильности конкретной монеты: для спокойных монет стоп ближе, "
        "для резких — дальше\n"
        "🔢 Фиксированный % — одна и та же дистанция в процентах для всех монет, "
        "которую задаёшь ты сам",
        [
            [{"text": "📈 Автоматически (рекомендуем)", "callback_data": "sl_method:atr"}],
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
        "6️⃣ Тейк-профит — уровень цены, на котором бот частично фиксирует прибыль. "
        "Их четыре: первые три — на заранее заданных уровнях, четвёртый (последняя "
        "четверть позиции) не фиксирован — он едет за ценой и закрывается, когда цена "
        "начинает разворачиваться, чтобы забрать максимум движения.\n\n"
        "Как разделить позицию между первыми тремя тейками?\n\n"
        "⚖️ Поровну (25/25/25) — фиксируем прибыль равномерно\n"
        "🛡 Консервативно (40/30/20) — больше фиксируем сразу на первом тейке, меньше риска отдать прибыль обратно\n"
        "🚀 Агрессивно (15/20/25) — меньше фиксируем сразу, больше оставляем до дальних целей — выше потенциал, но и риск выше",
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


async def _ask_exchange_choice_step(session, chat_id: int, state: dict, prefix: str = ""):
    state["step"] = "exchange_choice"
    await send_text_with_keyboard(
        session, chat_id,
        prefix + "🏦 С какой биржи начать настройку?\n\n"
        "Binance сейчас недоступен в России — если это твой случай, выбирай Bybit.",
        [
            [{"text": "🟡 Binance", "callback_data": "exchange_choice:binance"}],
            [{"text": "⚫ Bybit", "callback_data": "exchange_choice:bybit"}],
        ],
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
    await _ask_exchange_choice_step(session, chat_id, state)
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
    await _ask_exchange_choice_step(session, chat_id, state)
    return True


async def _handle_exchange_choice_callback(session, chat_id: int, exchange: str) -> bool:
    state = _onboarding.get(chat_id)
    if state is None or state["step"] != "exchange_choice":
        return False
    if exchange not in _EXCHANGE_LABELS:
        return False
    state["data"]["current_exchange"] = exchange
    state["data"]["is_second_exchange"] = False
    state["step"] = "api_key"
    await send_text(
        session, chat_id,
        f"🔑 Укажи API-ключ {_EXCHANGE_LABELS[exchange]} Futures (без прав вывода средств, "
        "только торговля). Пришли ключ отдельным сообщением:",
    )
    return True


async def _handle_api_key(session, chat_id: int, state: dict, text: str) -> bool:
    exchange = state["data"]["current_exchange"]
    state["data"]["api_key"] = text.strip()
    state["step"] = "api_secret"
    await send_text(session, chat_id, f"Теперь API-секрет {_EXCHANGE_LABELS[exchange]}:")
    return True


async def _handle_api_secret(session, chat_id: int, state: dict, text: str) -> bool:
    exchange = state["data"]["current_exchange"]
    trading_storage.save_api_credentials(chat_id, exchange, state["data"]["api_key"], text.strip())

    if state["data"]["is_second_exchange"]:
        del _onboarding[chat_id]
        trading_storage.init_paper_balance(chat_id, DEFAULT_PAPER_BALANCE)
        await send_text(
            session, chat_id,
            f"Ключ {_EXCHANGE_LABELS[exchange]} сохранён ✅\n\n🎉 Автотрейдинг готов к работе.",
        )
        return True

    other = "bybit" if exchange == "binance" else "binance"
    state["data"]["other_exchange"] = other
    state["step"] = "add_other_exchange_choice"
    await send_text_with_keyboard(
        session, chat_id,
        f"Ключ {_EXCHANGE_LABELS[exchange]} сохранён ✅\n\nДобавить также API-ключ "
        f"{_EXCHANGE_LABELS[other]} Futures?",
        [
            [{"text": f"➕ Добавить {_EXCHANGE_LABELS[other]}", "callback_data": "add_other_exchange:yes"}],
            [{"text": "➡️ Пропустить", "callback_data": "add_other_exchange:no"}],
        ],
    )
    return True


async def _handle_add_other_exchange_callback(session, chat_id: int, choice: str) -> bool:
    state = _onboarding.get(chat_id)
    if state is None or state["step"] != "add_other_exchange_choice":
        return False
    if choice == "yes":
        other = state["data"]["other_exchange"]
        state["data"]["current_exchange"] = other
        state["data"]["is_second_exchange"] = True
        state["step"] = "api_key"
        await send_text(session, chat_id, f"🔑 Укажи API-ключ {_EXCHANGE_LABELS[other]} Futures:")
        return True
    if choice == "no":
        del _onboarding[chat_id]
        trading_storage.init_paper_balance(chat_id, DEFAULT_PAPER_BALANCE)
        await send_text(session, chat_id, "🎉 Автотрейдинг готов к работе.")
        return True
    return False


_TEXT_STEP_HANDLERS = {
    "risk_percent": _handle_risk_percent,
    "daily_loss_limit_percent": _handle_daily_loss_limit,
    "leverage": _handle_leverage,
    "sl_fixed_percent": _handle_sl_fixed_percent,
    "breakeven_after_tp": _handle_breakeven_after_tp,
    "api_key": _handle_api_key,
    "api_secret": _handle_api_secret,
}


async def handle_text(session, chat_id: int, text: str) -> bool:
    state = _onboarding.get(chat_id)
    if state is None:
        return False
    handler = _TEXT_STEP_HANDLERS.get(state["step"])
    if handler is None:
        return False
    return await handler(session, chat_id, state, text)
