from unittest.mock import patch

import entry_engine
import live_trading

PROFILE = {
    "is_active": 1, "max_concurrent_trades": 3, "risk_percent": 1.0,
    "sl_method": "atr", "sl_fixed_percent": None, "tp_split_preset": "equal",
    "breakeven_after_tp": 2,
}


def setup_function():
    live_trading._pending_setups.clear()
    live_trading._open_positions.clear()


def _make_pending_setup(direction):
    return {
        "chat_id": 111, "exchange": "Binance", "signal_id": 55,
        "impulse_direction": direction, "window_start_price": 70.0,
        "cap_reference_price": None, "last_atr_refresh_price": None,
        "trigger_part1": entry_engine.create_part1_trigger(direction, atr_15m=1.0),
        "trigger_part2": entry_engine.create_part2_trigger(direction, atr_15m=1.0),
        "part_size": 2.0, "atr_1h": 2.0, "magnet_levels": [], "profile": PROFILE,
    }


def test_constants_20_09_2026():
    """
    20.09.2026 (622 исторических + 80 живых сигналов): широкий стоп 2.0 ATR1ч снижает долю
    'стоп без единого TP' 45% -> 36% без потери R; TP1 дампов на 1.0R поднимает долю
    дошедших до TP1 с 53% до ~60% при том же R. Continuation остаётся на старом 1.5 ATR1ч.
    """
    assert live_trading.REVERSAL_ATR_MULTIPLIER == 2.0
    assert live_trading.DEFAULT_ATR_MULTIPLIER == 1.5
    assert live_trading.DUMP_TP_R_MULTIPLES == (1.0, 3.0, 5.0)
    assert live_trading.PUMP_TP_R_MULTIPLES == (1.0, 2.0, 3.0)


def test_reversal_dump_stop_is_2_atr_and_tp1_is_1r():
    live_trading._pending_setups["BTCUSDT"] = _make_pending_setup("down")
    with patch("live_trading.trading_storage.create_position", return_value=1), \
         patch("live_trading.trading_storage.update_trade_signal_status"):
        live_trading.handle_price_tick("BTCUSDT", price=100.0)
        live_trading.handle_price_tick("BTCUSDT", price=100.8)  # часть 1: long по 100.8

    state = live_trading._open_positions["BTCUSDT"]["state"]
    # SL = 100.8 - 2.0*2.0 = 96.8, R = 4.0; TP (1.0/3.0/5.0 R) = 104.8 / 112.8 / 120.8
    assert round(state.stop_loss, 2) == 96.8
    assert [round(tp["level"], 2) for tp in state.take_profits] == [104.8, 112.8, 120.8]


def test_reversal_pump_stop_is_2_atr_with_unchanged_tp_grid():
    live_trading._pending_setups["ETHUSDT"] = _make_pending_setup("up")
    with patch("live_trading.trading_storage.create_position", return_value=1), \
         patch("live_trading.trading_storage.update_trade_signal_status"):
        live_trading.handle_price_tick("ETHUSDT", price=100.0)
        live_trading.handle_price_tick("ETHUSDT", price=99.2)  # часть 1: short по 99.2

    state = live_trading._open_positions["ETHUSDT"]["state"]
    # SL = 99.2 + 2.0*2.0 = 103.2, R = 4.0; TP (1/2/3 R) = 95.2 / 91.2 / 87.2
    assert round(state.stop_loss, 2) == 103.2
    assert [round(tp["level"], 2) for tp in state.take_profits] == [95.2, 91.2, 87.2]
