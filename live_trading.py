"""
Живая оркестрация автотрейдинга: от найденного импульса до открытой/закрытой
paper-позиции. Состояние (ожидающие сетапы, открытые позиции) хранится в
памяти процесса, keyed по символу.

НЕ подключён к живому потоку цен main.py -- см. отдельный план подключения.
"""

import logging
from datetime import datetime, timedelta

import trading_storage
import impulse_analysis
import magnet_levels as magnet_levels_module
import entry_engine
import position_manager
import order_executor
import market_data
import indicators
import trade_signal_ux
from notifier import send_text

logger = logging.getLogger(__name__)

_pending_setups: dict[str, dict] = {}
_open_positions: dict[str, dict] = {}

# Шаг, с которым обновляется ATR у долго ждущего сетапа. Триггеры считают
# дистанцию отката от ATR на момент старта мониторинга -- если цена уходит
# далеко без отката, эта величина устаревает относительно текущей волатильности
# (которая обычно растёт вместе с ценой), и триггер рискует сработать на
# обычном шуме нового масштаба вместо настоящего разворота.
ATR_REFRESH_STEP_PCT = 50.0

# Очередь уведомлений о действиях бота по открытым позициям (TP, безубыток+,
# включение трейлинга, закрытие) -- копится синхронно внутри _process_open_
# position_tick (там нет доступа к event loop для отправки в Telegram) и
# вычитывается main.py на каждом тике через pop_notifications().
_notification_queue: list[dict] = []

DEFAULT_ATR_MULTIPLIER = 1.5

# Защита от многоволновых манипуляций (прод-инцидент 12-13.09: LSKUSDT/POWRUSDT/
# ARKUSDT/VTHOUSDT -- все 5 убыточных сделок за ночь оказались РАННИМИ волнами
# продолжающегося пампа, а не его финальным разворотом: первый откат выглядел
# как истощение, бот заходил в шорт на реальном (не рыночном) трейлинг-откате,
# но манипуляция возобновлялась новой волной и выбивала стоп). Чем больше раз
# подряд символ уже сигналил за последние WAVE_LOOKBACK_HOURS часов, тем меньше
# доверия к тому, что именно ЭТА волна -- последняя.
WAVE_LOOKBACK_HOURS = 4
WAVE_SIZE_MULTIPLIERS = {0: 1.0, 1: 0.5}  # wave_count >= 2 -> сетап пропускается

# Ретроспектива 13-14.09.2026 (2833 эпизода за июль-сентябрь): фейд импульса-пампа
# сам по себе даёт эдж около нуля (avgR +0.13 на всех, но климакс/RSI-дивергенция
# из classify_impulse() на пампах скорее ВРЕДЯТ, а не помогают). Единственный
# сигнал, который монотонно и статистически значимо разделяет прибыльные и
# убыточные пампы -- экстремальность funding rate по модулю (топ-20% -> avgR
# +0.46, t=4.94): либо перегретые лонги на плече (long squeeze), либо шорты,
# продолжающие платить несмотря на рост (короткий сквиз без топлива). Дампов
# это не касается -- там эдж сильный и без дополнительных фильтров.
PUMP_FUNDING_EXTREME_THRESHOLD = 0.00012


async def handle_new_impulse(
    session, chat_id: int, symbol: str, exchange: str, direction: str,
    current_price: float, window_start_price: float,
) -> dict | None:
    """
    Вызывается один раз на новый импульс (первый уровень ImpulseSignal).
    Возвращает None, если автотрейдинг неприменим для этого символа сейчас.
    """
    profile = trading_storage.get_profile(chat_id)
    if profile is None or not profile["is_active"]:
        return None
    if symbol in _pending_setups or symbol in _open_positions or trade_signal_ux.is_awaiting_confirmation(symbol):
        return None
    if len(trading_storage.get_open_positions(chat_id)) >= profile["max_concurrent_trades"]:
        return None

    analysis = await impulse_analysis.analyze_impulse(session, symbol, exchange, direction, current_price)
    classification = analysis["classification"]

    if direction == "up" and classification == "reversal":
        if abs(analysis["funding_rate"]) < PUMP_FUNDING_EXTREME_THRESHOLD:
            return None

    signal_id = trading_storage.create_trade_signal(
        chat_id=chat_id, symbol=symbol, exchange=exchange,
        impulse_direction=direction, classification=classification,
    )

    await trade_signal_ux.request_confirmation(
        session, chat_id, symbol, exchange, direction, classification,
        current_price, window_start_price, profile, analysis, signal_id,
        magnet_levels=[], execute_fn=execute_setup,
    )
    return {"classification": classification, "signal_id": signal_id, "awaiting_confirmation": True}


def _compute_wave_size_multiplier(chat_id: int, symbol: str, signal_id: int) -> float | None:
    """
    Считает, сколько раз символ уже сигналил за последние WAVE_LOOKBACK_HOURS
    часов (включая текущий сигнал), и возвращает множитель размера позиции.
    None означает "не входить вообще" -- третья и более поздняя волна подряд.
    """
    signal = trading_storage.get_trade_signal(signal_id)
    signal_time = datetime.strptime(signal["created_at"], "%Y-%m-%d %H:%M:%S")
    since = (signal_time - timedelta(hours=WAVE_LOOKBACK_HOURS)).strftime("%Y-%m-%d %H:%M:%S")
    wave_count = trading_storage.count_recent_signals(chat_id, symbol, since) - 1  # без текущего
    return WAVE_SIZE_MULTIPLIERS.get(wave_count)


async def execute_setup(
    session, chat_id: int, symbol: str, exchange: str, direction: str, classification: str,
    current_price: float, window_start_price: float, profile: dict, analysis: dict, signal_id: int,
) -> dict:
    """
    Реально исполняет сетап -- вызывается из trade_signal_ux после подтверждения
    (кнопкой или по таймауту), НЕ напрямую из handle_new_impulse().
    """
    size_multiplier = _compute_wave_size_multiplier(chat_id, symbol, signal_id)
    if size_multiplier is None:
        trading_storage.update_trade_signal_status(signal_id, "expired")
        logger.info(f"Автотрейдинг [{symbol}]: сетап пропущен -- уже 2+ волны за последние {WAVE_LOOKBACK_HOURS}ч")
        return {"classification": classification, "signal_id": signal_id, "skipped": "multiwave_protection"}

    if classification == "continuation":
        return await _open_continuation_position(
            session, chat_id, symbol, exchange, direction, current_price, profile, analysis, signal_id, size_multiplier,
        )
    return await _create_pending_reversal_setup(
        session, chat_id, symbol, exchange, direction, current_price,
        window_start_price, profile, analysis, signal_id, size_multiplier,
    )


def format_entry_report(symbol: str, exchange: str, snapshot: dict) -> str:
    """Отчёт пользователю о факте входа в сделку -- цена, объём, SL, сетка TP."""
    direction_word = "🟢 LONG" if snapshot["direction"] == "long" else "🔴 SHORT"
    tp_lines = "\n".join(
        f"TP{idx}: `{tp['level']:.6g}` ({tp['size_pct']}%)"
        for idx, tp in enumerate(snapshot["take_profits"], start=1)
    )
    return (
        f"✅ *Вход в сделку: {symbol}* [{exchange}]\n\n"
        f"Направление: {direction_word}\n"
        f"Цена входа: `{snapshot['avg_entry_price']:.6g}`\n"
        f"Объём: `{snapshot['quantity']:.6g}`\n"
        f"SL: `{snapshot['stop_loss']:.6g}`\n"
        f"{tp_lines}\n"
        f"TP4: трейлинг (Chandelier), {snapshot['tp4_size_pct']}% объёма\n\n"
        f"Риск на сделку: `{snapshot['risk_amount']:.2f}`"
    )


async def _open_continuation_position(
    session, chat_id: int, symbol: str, exchange: str, direction: str, current_price: float,
    profile: dict, analysis: dict, signal_id: int, size_multiplier: float = 1.0,
) -> dict:
    trade_direction = position_manager.determine_trade_direction(direction, "continuation")
    stop_loss = position_manager.calculate_stop_loss(
        current_price, trade_direction, profile["sl_method"],
        analysis["atr_1h"], DEFAULT_ATR_MULTIPLIER, profile["sl_fixed_percent"],
    )
    balance = trading_storage.get_paper_balance(chat_id) or 0.0
    size = position_manager.calculate_position_size(
        balance, profile["risk_percent"], current_price, stop_loss
    ) * size_multiplier

    result = order_executor.open_paper_position(
        chat_id=chat_id, symbol=symbol, exchange=exchange, direction=trade_direction,
        fills=[(current_price, size)], sl_method=profile["sl_method"],
        atr_1h=analysis["atr_1h"], atr_multiplier=DEFAULT_ATR_MULTIPLIER,
        fixed_percent=profile["sl_fixed_percent"], tp_split_preset=profile["tp_split_preset"],
        breakeven_after_tp=profile["breakeven_after_tp"],
    )
    state = order_executor.OpenPositionState(
        position_id=result["position_id"], direction=trade_direction,
        avg_entry_price=result["avg_entry_price"], quantity=result["quantity"],
        stop_loss=result["stop_loss"], take_profits=result["take_profits"],
        breakeven_after_tp=profile["breakeven_after_tp"],
    )
    _open_positions[symbol] = {"chat_id": chat_id, "state": state, "atr_1h": analysis["atr_1h"]}
    trading_storage.update_trade_signal_status(signal_id, "executed")

    snapshot = get_position_snapshot(symbol)
    if snapshot is not None:
        await send_text(session, chat_id, format_entry_report(symbol, exchange, snapshot))

    return {"classification": "continuation", "signal_id": signal_id, "position_id": result["position_id"]}


async def _create_pending_reversal_setup(
    session, chat_id: int, symbol: str, exchange: str, direction: str, current_price: float,
    window_start_price: float, profile: dict, analysis: dict, signal_id: int, size_multiplier: float = 1.0,
) -> dict:
    daily_candles = await market_data.fetch_klines(session, exchange, symbol, "1d", limit=90)
    weekly_candles = await market_data.fetch_klines(session, exchange, symbol, "1w", limit=52)
    levels = magnet_levels_module.find_magnet_levels(daily_candles, weekly_candles, current_price, direction)

    trade_direction = position_manager.determine_trade_direction(direction, "reversal")
    estimated_stop_loss = position_manager.calculate_stop_loss(
        current_price, trade_direction, profile["sl_method"],
        analysis["atr_1h"], DEFAULT_ATR_MULTIPLIER, profile["sl_fixed_percent"],
    )
    balance = trading_storage.get_paper_balance(chat_id) or 0.0
    total_size = position_manager.calculate_position_size(
        balance, profile["risk_percent"], current_price, estimated_stop_loss
    ) * size_multiplier

    _pending_setups[symbol] = {
        "chat_id": chat_id, "exchange": exchange, "signal_id": signal_id,
        "impulse_direction": direction, "window_start_price": window_start_price,
        # Точка отсчёта потолка ожидания -- НЕ window_start_price детектора (он может
        # быть сильно устаревшим, например "цена ~24ч назад"), а цена на момент, когда
        # этот конкретный сетап реально начал мониториться. Ставится лениво на первом
        # тике в _process_pending_setup_tick, аналогично extreme_price у триггеров.
        "cap_reference_price": None, "last_atr_refresh_price": None,
        "trigger_part1": entry_engine.create_part1_trigger(direction, analysis["atr_15m"]),
        "trigger_part2": entry_engine.create_part2_trigger(direction, analysis["atr_15m"]),
        "part_size": total_size / 2,
        "atr_1h": analysis["atr_1h"], "magnet_levels": levels, "profile": profile,
    }
    return {"classification": "reversal", "signal_id": signal_id, "magnet_levels": levels}


def get_position_snapshot(symbol: str) -> dict | None:
    """
    Снимок открытой позиции для отчёта пользователю о факте входа в сделку --
    цена, объём, SL, сетка TP1-3 (TP4 не фиксирован -- трейлинг, только его доля).
    """
    entry = _open_positions.get(symbol)
    if entry is None:
        return None
    state = entry["state"]
    tp3_total_pct = sum(tp["size_pct"] for tp in state.take_profits)
    return {
        "chat_id": entry["chat_id"],
        "direction": state.direction,
        "avg_entry_price": state.avg_entry_price,
        "quantity": state.quantity,
        "stop_loss": state.stop_loss,
        "take_profits": [{"level": tp["level"], "size_pct": tp["size_pct"]} for tp in state.take_profits],
        "tp4_size_pct": 100 - tp3_total_pct,
        "risk_amount": state.quantity * abs(state.avg_entry_price - state.stop_loss),
    }


def handle_price_tick(symbol: str, price: float) -> list[str] | None:
    """
    Вызывается на каждый тик цены символа. Возвращает список произошедших
    событий или None, если по символу нет ни ожидающего сетапа, ни открытой
    позиции.

    Символ может одновременно быть и в _pending_setups, и в _open_positions
    (часть 1 уже открыла позицию, часть 2 ещё ждёт свой триггер независимо) --
    поэтому обе ветки проверяются на каждом тике, а не взаимоисключающе.
    Сначала проверяется ожидающий сетап (часть 2 может слить в позицию на
    этом же тике), затем состояние (возможно, уже обновлённой) открытой позиции.
    """
    events = []

    if symbol in _pending_setups:
        pending_events = _process_pending_setup_tick(symbol, price)
        if pending_events:
            events.extend(pending_events)

    if symbol in _open_positions:
        open_events = _process_open_position_tick(symbol, price)
        if open_events:
            events.extend(open_events)

    return events or None


def restore_open_positions() -> int:
    """
    Восстанавливает открытые позиции из БД в _open_positions при старте бота.
    Состояние сделки (SL/TP/Chandelier) живёт только в памяти процесса и не
    переживает рестарт иначе -- без этого любой редеплой во время открытой
    сделки "осиротит" её навсегда (см. прод-инцидент 12-13.09: VTHOUSDT/
    POWRUSDT остались висеть status='open' без какого-либо мониторинга).
    Возвращает число восстановленных позиций.
    """
    restored = 0
    for row in trading_storage.get_all_open_positions():
        take_profits = position_manager.calculate_take_profits(
            row["avg_entry_price"], row["original_stop_loss"], row["direction"], row["tp_split_preset"],
        )
        state = order_executor.OpenPositionState(
            position_id=row["id"], direction=row["direction"],
            avg_entry_price=row["avg_entry_price"], quantity=row["quantity"],
            stop_loss=row["stop_loss"], take_profits=take_profits,
            breakeven_after_tp=row["breakeven_after_tp"],
        )
        for idx, filled_key in enumerate(("tp1_filled", "tp2_filled", "tp3_filled")):
            if idx < len(state.take_profits):
                state.take_profits[idx]["filled"] = bool(row[filled_key])
        state.remaining_quantity = row["remaining_quantity"]
        state.tp_hit_count = int(row["tp1_filled"]) + int(row["tp2_filled"]) + int(row["tp3_filled"])

        if row["chandelier_active"]:
            chandelier = position_manager.ChandelierTrailingStop(direction=row["direction"])
            chandelier.extreme_price = row["chandelier_extreme_price"]
            chandelier.stop_price = row["chandelier_stop_price"]
            state.chandelier = chandelier

        _open_positions[row["symbol"]] = {"chat_id": row["chat_id"], "state": state, "atr_1h": row["atr_1h"]}
        restored += 1
    return restored


def _persist_position_progress(state: order_executor.OpenPositionState) -> None:
    chandelier = state.chandelier
    trading_storage.update_position_progress(
        state.position_id,
        tp1_filled=state.take_profits[0]["filled"] if len(state.take_profits) > 0 else False,
        tp2_filled=state.take_profits[1]["filled"] if len(state.take_profits) > 1 else False,
        tp3_filled=state.take_profits[2]["filled"] if len(state.take_profits) > 2 else False,
        remaining_quantity=state.remaining_quantity,
        chandelier_active=chandelier is not None,
        chandelier_extreme_price=chandelier.extreme_price if chandelier else None,
        chandelier_stop_price=chandelier.stop_price if chandelier else None,
    )


def _queue_notification(chat_id: int, text: str) -> None:
    _notification_queue.append({"chat_id": chat_id, "text": text})


def pop_notifications() -> list[dict]:
    """Вычитывает и очищает накопленные уведомления -- вызывается из main.py на каждом тике."""
    items = list(_notification_queue)
    _notification_queue.clear()
    return items


def _format_tp_report(symbol: str, event: dict, state: order_executor.OpenPositionState) -> str:
    tp_number = event["event"][2]  # "tp1_hit" -> "1"
    pct_of_total = event["size_closed"] / state.quantity * 100
    remaining_pct = state.remaining_quantity / state.quantity * 100
    return (
        f"🎯 *TP{tp_number} исполнен: {symbol}*\n\n"
        f"Цена: `{event['exit_price']:.6g}`\n"
        f"Зафиксировано: {pct_of_total:.0f}% объёма\n"
        f"PnL: `{event['pnl_delta']:+.2f}`\n"
        f"Остаток в позиции: {remaining_pct:.0f}%"
    )


def _format_breakeven_report(symbol: str, event: dict) -> str:
    return (
        f"🛡 *SL перенесён в безубыток+: {symbol}*\n\n"
        f"Новый стоп: `{event['new_stop_loss']:.6g}`\n"
        f"Комиссии обеих ног сделки покрыты — риск на этой сделке закрыт"
    )


def _format_chandelier_activated_report(symbol: str, state: order_executor.OpenPositionState) -> str:
    remaining_pct = state.remaining_quantity / state.quantity * 100
    return (
        f"🔄 *Включён трейлинг-стоп TP4: {symbol}*\n\n"
        f"Оставшиеся {remaining_pct:.0f}% объёма теперь едут за ценой (Chandelier), "
        f"фиксированной цели больше нет"
    )


def _format_close_report(symbol: str, event: dict) -> str:
    is_chandelier = event["event"] == "closed_chandelier"
    header = "Сделка закрыта трейлингом TP4" if is_chandelier else "Стоп сработал"
    icon = "🏁" if is_chandelier else "🛑"
    return (
        f"{icon} *{header}: {symbol}*\n\n"
        f"Цена закрытия: `{event['exit_price']:.6g}`\n"
        f"PnL: `{event['pnl_delta']:+.2f}`\n"
        f"Позиция полностью закрыта"
    )


def _process_open_position_tick(symbol: str, price: float) -> list[str] | None:
    entry = _open_positions[symbol]
    state = entry["state"]
    chat_id = entry["chat_id"]
    events = []

    stop_event = order_executor.check_stop_hit(state, price, entry["atr_1h"])
    if stop_event is not None:
        trading_storage.adjust_paper_balance(chat_id, stop_event["pnl_delta"])
        trading_storage.close_position(state.position_id, realized_pnl=stop_event["pnl_delta"])
        _queue_notification(chat_id, _format_close_report(symbol, stop_event))
        del _open_positions[symbol]
        return [stop_event["event"]]

    tp_events = order_executor.check_take_profit_hits(state, price)
    for event in tp_events:
        if event["event"].startswith("tp"):
            trading_storage.adjust_paper_balance(chat_id, event["pnl_delta"])
            _queue_notification(chat_id, _format_tp_report(symbol, event, state))
        elif event["event"] == "moved_to_breakeven":
            trading_storage.update_position_stop_loss(state.position_id, event["new_stop_loss"])
            _queue_notification(chat_id, _format_breakeven_report(symbol, event))
        elif event["event"] == "chandelier_activated":
            _queue_notification(chat_id, _format_chandelier_activated_report(symbol, state))
        events.append(event["event"])

    if tp_events or state.chandelier is not None:
        _persist_position_progress(state)

    return events or None


def _process_pending_setup_tick(symbol: str, price: float) -> list[str] | None:
    setup = _pending_setups[symbol]
    events = []

    if setup["cap_reference_price"] is None:
        setup["cap_reference_price"] = price
        setup["last_atr_refresh_price"] = price

    if not setup["trigger_part1"].fired and setup["trigger_part1"].update(price):
        _handle_part_fill(setup, symbol, price)
        events.append("part1_filled")

    if not setup["trigger_part2"].fired and setup["trigger_part2"].update(price):
        _handle_part_fill(setup, symbol, price)
        events.append("part2_filled")

    if setup["trigger_part1"].fired and setup["trigger_part2"].fired:
        del _pending_setups[symbol]
        events.append("setup_complete")
    elif not events and not setup["trigger_part1"].fired and not setup["trigger_part2"].fired:
        cap_pct = (
            magnet_levels_module.PUMP_EXTENSION_CAP_PCT if setup["impulse_direction"] == "up"
            else magnet_levels_module.DUMP_EXTENSION_CAP_PCT
        )
        if magnet_levels_module.is_beyond_extension_cap(setup["cap_reference_price"], price, cap_pct=cap_pct):
            trading_storage.update_trade_signal_status(setup["signal_id"], "expired")
            del _pending_setups[symbol]
            events.append("setup_expired")
        elif magnet_levels_module.is_beyond_extension_cap(
            setup["last_atr_refresh_price"], price, cap_pct=ATR_REFRESH_STEP_PCT
        ):
            setup["last_atr_refresh_price"] = price
            events.append("atr_refresh_needed")

    return events or None


def reset_all_state(chat_id: int, starting_balance: float = 10000.0) -> None:
    """Полный сброс paper-trading: чистит БД (баланс/позиции/сигналы) и in-memory состояние."""
    _pending_setups.clear()
    _open_positions.clear()
    trading_storage.reset_paper_trading(chat_id, starting_balance=starting_balance)


async def refresh_pending_setup_atr(session, symbol: str) -> None:
    """
    Пересчитывает ATR15м/ATR1ч для ожидающего сетапа и обновляет дистанции
    трейлинг-триггеров -- вызывается фоновой задачей в ответ на событие
    "atr_refresh_needed" из handle_price_tick (цена ушла далеко от точки
    старта мониторинга без отката, исходная ATR устарела относительно
    текущей волатильности). Экстремум триггера (extreme_price) не трогаем --
    только дистанцию срабатывания.
    """
    setup = _pending_setups.get(symbol)
    if setup is None:
        return

    exchange = setup["exchange"]
    candles_15m = await market_data.fetch_klines(session, exchange, symbol, "15m", limit=50)
    candles_1h = await market_data.fetch_klines(session, exchange, symbol, "1h", limit=24)
    atr_15m_values = indicators.atr(candles_15m, period=14)
    atr_1h_values = indicators.atr(candles_1h, period=14)
    atr_15m = atr_15m_values[-1] if atr_15m_values else None
    atr_1h = atr_1h_values[-1] if atr_1h_values else None
    if atr_15m is None or atr_1h is None or atr_15m <= 0 or atr_1h <= 0:
        return

    setup = _pending_setups.get(symbol)  # сетап мог исчезнуть/слиться, пока шёл запрос
    if setup is None:
        return

    setup["trigger_part1"].trigger_distance = atr_15m * entry_engine.PART1_ATR_MULTIPLIER
    setup["trigger_part2"].trigger_distance = atr_15m * entry_engine.PART2_ATR_MULTIPLIER
    setup["atr_1h"] = atr_1h


def _handle_part_fill(setup: dict, symbol: str, price: float) -> None:
    """
    Открывает новую позицию по первой сработавшей части, либо объединяет
    со второй частью, если позиция первой ещё открыта и ни один TP не сработал.
    Если позиция первой части уже закрыта (SL) или частично зафиксирована
    (сработал TP) -- часть открывает отдельную независимую позицию, чтобы не
    "расфиливать" уже зафиксированные тейки при пересборке сетки.
    """
    profile = setup["profile"]
    direction = position_manager.determine_trade_direction(setup["impulse_direction"], "reversal")
    existing = _open_positions.get(symbol)

    if existing is not None and not existing["state"].closed and existing["state"].tp_hit_count == 0:
        old_state = existing["state"]
        fills = [(old_state.avg_entry_price, old_state.quantity), (price, setup["part_size"])]
        trading_storage.close_position(old_state.position_id, realized_pnl=0.0)
    else:
        fills = [(price, setup["part_size"])]

    result = order_executor.open_paper_position(
        chat_id=setup["chat_id"], symbol=symbol, exchange=setup["exchange"], direction=direction,
        fills=fills, sl_method=profile["sl_method"], atr_1h=setup["atr_1h"],
        atr_multiplier=DEFAULT_ATR_MULTIPLIER, fixed_percent=profile["sl_fixed_percent"],
        tp_split_preset=profile["tp_split_preset"], breakeven_after_tp=profile["breakeven_after_tp"],
    )
    new_state = order_executor.OpenPositionState(
        position_id=result["position_id"], direction=direction,
        avg_entry_price=result["avg_entry_price"], quantity=result["quantity"],
        stop_loss=result["stop_loss"], take_profits=result["take_profits"],
        breakeven_after_tp=profile["breakeven_after_tp"],
    )
    _open_positions[symbol] = {"chat_id": setup["chat_id"], "state": new_state, "atr_1h": setup["atr_1h"]}
    trading_storage.update_trade_signal_status(setup["signal_id"], "executed")
