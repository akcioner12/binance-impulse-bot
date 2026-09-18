from unittest.mock import patch

import entry_engine
import order_executor
import live_trading


PROFILE = {
    "is_active": 1, "max_concurrent_trades": 3, "risk_percent": 1.0,
    "sl_method": "atr", "sl_fixed_percent": None, "tp_split_preset": "equal",
    "breakeven_after_tp": 2,
}


def setup_function():
    live_trading._pending_setups.clear()
    live_trading._open_positions.clear()


def _make_pending_setup(direction="up"):
    return {
        "chat_id": 111, "exchange": "Binance", "signal_id": 55,
        "impulse_direction": direction, "window_start_price": 70.0,
        "cap_reference_price": None, "last_atr_refresh_price": None,
        "trigger_part1": entry_engine.create_part1_trigger(direction, atr_15m=1.0),  # distance 0.75
        "trigger_part2": entry_engine.create_part2_trigger(direction, atr_15m=1.0),  # distance 2.0
        "part_size": 2.0, "atr_1h": 2.0, "magnet_levels": [], "profile": PROFILE,
    }


def test_part1_fill_sets_fill_stage_part1():
    live_trading._pending_setups["BTCUSDT"] = _make_pending_setup()
    with patch("live_trading.trading_storage.create_position", return_value=1), \
         patch("live_trading.trading_storage.update_trade_signal_status"):
        live_trading.handle_price_tick("BTCUSDT", price=100.0)
        live_trading.handle_price_tick("BTCUSDT", price=99.2)  # часть 1 срабатывает

    assert live_trading._open_positions["BTCUSDT"]["fill_stage"] == "part1"


def test_part2_merge_sets_fill_stage_part2_merged():
    live_trading._pending_setups["BTCUSDT"] = _make_pending_setup()
    with patch("live_trading.trading_storage.create_position", side_effect=[1, 2]), \
         patch("live_trading.trading_storage.close_position"), \
         patch("live_trading.trading_storage.update_trade_signal_status"):
        live_trading.handle_price_tick("BTCUSDT", price=100.0)
        live_trading.handle_price_tick("BTCUSDT", price=99.2)  # часть 1
        live_trading.handle_price_tick("BTCUSDT", price=98.0)  # часть 2, сливается

    assert live_trading._open_positions["BTCUSDT"]["fill_stage"] == "part2_merged"


def test_part2_independent_sets_fill_stage_part2_independent():
    live_trading._pending_setups["BTCUSDT"] = _make_pending_setup()
    with patch("live_trading.trading_storage.create_position", side_effect=[1, 2]), \
         patch("live_trading.trading_storage.update_trade_signal_status"):
        live_trading.handle_price_tick("BTCUSDT", price=100.0)
        live_trading.handle_price_tick("BTCUSDT", price=99.2)  # часть 1, position id=1

    live_trading._open_positions["BTCUSDT"]["state"].closed = True  # часть 1 уже закрылась

    with patch("live_trading.trading_storage.create_position", return_value=2), \
         patch("live_trading.trading_storage.close_position") as mock_close, \
         patch("live_trading.trading_storage.update_trade_signal_status"):
        live_trading.handle_price_tick("BTCUSDT", price=98.0)  # часть 2, независимый вход

    mock_close.assert_not_called()
    assert live_trading._open_positions["BTCUSDT"]["fill_stage"] == "part2_independent"


def test_get_position_snapshot_exposes_fill_stage():
    state = order_executor.OpenPositionState(
        position_id=1, direction="short", avg_entry_price=100.0, quantity=2.0,
        stop_loss=103.0, take_profits=[{"level": 97.0, "size_pct": 25}], breakeven_after_tp=2,
    )
    live_trading._open_positions["BTCUSDT"] = {"chat_id": 111, "state": state, "atr_1h": 2.0, "fill_stage": "part1"}

    snapshot = live_trading.get_position_snapshot("BTCUSDT")

    assert snapshot["fill_stage"] == "part1"


def test_get_position_snapshot_fill_stage_defaults_to_none_when_missing():
    """continuation-сделки (single-shot, без частей) не пишут fill_stage."""
    state = order_executor.OpenPositionState(
        position_id=1, direction="long", avg_entry_price=100.0, quantity=2.0,
        stop_loss=97.0, take_profits=[{"level": 103.0, "size_pct": 25}], breakeven_after_tp=2,
    )
    live_trading._open_positions["BTCUSDT"] = {"chat_id": 111, "state": state, "atr_1h": 2.0}

    snapshot = live_trading.get_position_snapshot("BTCUSDT")

    assert snapshot["fill_stage"] is None


def _base_snapshot(fill_stage=None):
    return {
        "chat_id": 111, "direction": "short", "avg_entry_price": 100.0, "quantity": 2.0,
        "stop_loss": 103.0, "take_profits": [{"level": 97.0, "size_pct": 25}],
        "tp4_size_pct": 75, "risk_amount": 6.0, "fill_stage": fill_stage,
    }


def test_format_entry_report_labels_part1():
    text = live_trading.format_entry_report("BTCUSDT", "Binance", _base_snapshot("part1"))
    assert "Часть 1 из 2" in text


def test_format_entry_report_labels_part2_merged():
    text = live_trading.format_entry_report("BTCUSDT", "Binance", _base_snapshot("part2_merged"))
    assert "Часть 2 из 2" in text
    assert "объедин" in text.lower()


def test_format_entry_report_labels_part2_independent():
    text = live_trading.format_entry_report("BTCUSDT", "Binance", _base_snapshot("part2_independent"))
    assert "Часть 2 из 2" in text
    assert "отдельн" in text.lower()


def test_format_entry_report_no_label_when_fill_stage_none():
    text = live_trading.format_entry_report("BTCUSDT", "Binance", _base_snapshot(None))
    assert "Часть" not in text
