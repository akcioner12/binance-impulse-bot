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
    if symbol in _pending_setups or symbol in _open_positions:
        return None
    if len(trading_storage.get_open_positions(chat_id)) >= profile["max_concurrent_trades"]:
        return None

    analysis = await impulse_analysis.analyze_impulse(session, symbol, exchange, direction, current_price)
    classification = analysis["classification"]

    signal_id = trading_storage.create_trade_signal(
        chat_id=chat_id, symbol=symbol, exchange=exchange,
        impulse_direction=direction, classification=classification,
    )

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
        "trigger_part1": entry_engine.create_part1_trigger(direction, analysis["atr_15m"]),
        "trigger_part2": entry_engine.create_part2_trigger(direction, analysis["atr_15m"]),
        "part_size": total_size / 2,
        "atr_1h": analysis["atr_1h"], "magnet_levels": levels, "profile": profile,
    }
    return {"classification": "reversal", "signal_id": signal_id, "magnet_levels": levels}
