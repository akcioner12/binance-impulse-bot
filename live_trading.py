"""
Живая оркестрация автотрейдинга: от найденного импульса до открытой/закрытой
paper-позиции. Состояние (ожидающие сетапы, открытые позиции) хранится в
памяти процесса, keyed по символу.

НЕ подключён к живому потоку цен main.py -- см. отдельный план подключения.
"""

import logging

import trading_storage
import impulse_analysis
import magnet_levels as magnet_levels_module
import entry_engine
import position_manager
import order_executor
import market_data
import trade_signal_ux

logger = logging.getLogger(__name__)

_pending_setups: dict[str, dict] = {}
_open_positions: dict[str, dict] = {}

DEFAULT_ATR_MULTIPLIER = 1.5


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


async def execute_setup(
    session, chat_id: int, symbol: str, exchange: str, direction: str, classification: str,
    current_price: float, window_start_price: float, profile: dict, analysis: dict, signal_id: int,
) -> dict:
    """
    Реально исполняет сетап -- вызывается из trade_signal_ux после подтверждения
    (кнопкой или по таймауту), НЕ напрямую из handle_new_impulse().
    """
    if classification == "continuation":
        return await _open_continuation_position(
            chat_id, symbol, exchange, direction, current_price, profile, analysis, signal_id
        )
    return await _create_pending_reversal_setup(
        session, chat_id, symbol, exchange, direction, current_price,
        window_start_price, profile, analysis, signal_id,
    )


async def _open_continuation_position(
    chat_id: int, symbol: str, exchange: str, direction: str, current_price: float,
    profile: dict, analysis: dict, signal_id: int,
) -> dict:
    trade_direction = position_manager.determine_trade_direction(direction, "continuation")
    stop_loss = position_manager.calculate_stop_loss(
        current_price, trade_direction, profile["sl_method"],
        analysis["atr_1h"], DEFAULT_ATR_MULTIPLIER, profile["sl_fixed_percent"],
    )
    balance = trading_storage.get_paper_balance(chat_id) or 0.0
    size = position_manager.calculate_position_size(balance, profile["risk_percent"], current_price, stop_loss)

    result = order_executor.open_paper_position(
        chat_id=chat_id, symbol=symbol, exchange=exchange, direction=trade_direction,
        fills=[(current_price, size)], sl_method=profile["sl_method"],
        atr_1h=analysis["atr_1h"], atr_multiplier=DEFAULT_ATR_MULTIPLIER,
        fixed_percent=profile["sl_fixed_percent"], tp_split_preset=profile["tp_split_preset"],
    )
    state = order_executor.OpenPositionState(
        position_id=result["position_id"], direction=trade_direction,
        avg_entry_price=result["avg_entry_price"], quantity=result["quantity"],
        stop_loss=result["stop_loss"], take_profits=result["take_profits"],
        breakeven_after_tp=profile["breakeven_after_tp"],
    )
    _open_positions[symbol] = {"chat_id": chat_id, "state": state, "atr_1h": analysis["atr_1h"]}
    trading_storage.update_trade_signal_status(signal_id, "executed")

    return {"classification": "continuation", "signal_id": signal_id, "position_id": result["position_id"]}


async def _create_pending_reversal_setup(
    session, chat_id: int, symbol: str, exchange: str, direction: str, current_price: float,
    window_start_price: float, profile: dict, analysis: dict, signal_id: int,
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
    )

    _pending_setups[symbol] = {
        "chat_id": chat_id, "exchange": exchange, "signal_id": signal_id,
        "impulse_direction": direction, "window_start_price": window_start_price,
        # Точка отсчёта потолка ожидания -- НЕ window_start_price детектора (он может
        # быть сильно устаревшим, например "цена ~24ч назад"), а цена на момент, когда
        # этот конкретный сетап реально начал мониториться. Ставится лениво на первом
        # тике в _process_pending_setup_tick, аналогично extreme_price у триггеров.
        "cap_reference_price": None,
        "trigger_part1": entry_engine.create_part1_trigger(direction, analysis["atr_15m"]),
        "trigger_part2": entry_engine.create_part2_trigger(direction, analysis["atr_15m"]),
        "part_size": total_size / 2,
        "atr_1h": analysis["atr_1h"], "magnet_levels": levels, "profile": profile,
    }
    return {"classification": "reversal", "signal_id": signal_id, "magnet_levels": levels}


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


def _process_open_position_tick(symbol: str, price: float) -> list[str] | None:
    entry = _open_positions[symbol]
    state = entry["state"]
    chat_id = entry["chat_id"]
    events = []

    stop_event = order_executor.check_stop_hit(state, price, entry["atr_1h"])
    if stop_event is not None:
        trading_storage.adjust_paper_balance(chat_id, stop_event["pnl_delta"])
        trading_storage.close_position(state.position_id, realized_pnl=stop_event["pnl_delta"])
        del _open_positions[symbol]
        return [stop_event["event"]]

    tp_events = order_executor.check_take_profit_hits(state, price)
    for event in tp_events:
        if event["event"].startswith("tp"):
            trading_storage.adjust_paper_balance(chat_id, event["pnl_delta"])
        elif event["event"] == "moved_to_breakeven":
            trading_storage.update_position_stop_loss(state.position_id, event["new_stop_loss"])
        events.append(event["event"])

    return events or None


def _process_pending_setup_tick(symbol: str, price: float) -> list[str] | None:
    setup = _pending_setups[symbol]
    events = []

    if setup["cap_reference_price"] is None:
        setup["cap_reference_price"] = price

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
        if magnet_levels_module.is_beyond_extension_cap(setup["cap_reference_price"], price):
            trading_storage.update_trade_signal_status(setup["signal_id"], "expired")
            del _pending_setups[symbol]
            events.append("setup_expired")

    return events or None


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
        tp_split_preset=profile["tp_split_preset"],
    )
    new_state = order_executor.OpenPositionState(
        position_id=result["position_id"], direction=direction,
        avg_entry_price=result["avg_entry_price"], quantity=result["quantity"],
        stop_loss=result["stop_loss"], take_profits=result["take_profits"],
        breakeven_after_tp=profile["breakeven_after_tp"],
    )
    _open_positions[symbol] = {"chat_id": setup["chat_id"], "state": new_state, "atr_1h": setup["atr_1h"]}
    trading_storage.update_trade_signal_status(setup["signal_id"], "executed")
