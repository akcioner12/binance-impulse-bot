from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import order_executor
import live_trading
import trading_storage


def setup_function():
    live_trading._pending_setups.clear()
    live_trading._open_positions.clear()
    live_trading._notification_queue.clear()
    trading_storage.init_trading_db()
    trading_storage.init_paper_trading_db()


def _make_open_position(direction="long", opened_hours_ago=0.0):
    if direction == "long":
        state = order_executor.OpenPositionState(
            position_id=1, direction="long", avg_entry_price=100.0, quantity=4.0, stop_loss=97.0,
            take_profits=[{"level": 110.0, "size_pct": 25}, {"level": 120.0, "size_pct": 25}, {"level": 130.0, "size_pct": 25}],
            breakeven_after_tp=2,
        )
    else:
        state = order_executor.OpenPositionState(
            position_id=1, direction="short", avg_entry_price=100.0, quantity=4.0, stop_loss=110.0,
            take_profits=[{"level": 90.0, "size_pct": 25}, {"level": 80.0, "size_pct": 25}, {"level": 70.0, "size_pct": 25}],
            breakeven_after_tp=2,
        )
    opened_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=opened_hours_ago)
    live_trading._open_positions["BTCUSDT"] = {"chat_id": 111, "state": state, "atr_1h": 2.0, "opened_at": opened_at}
    return state


def test_tp_hit_is_recorded_as_trade_event():
    _make_open_position()
    with patch("live_trading.trading_storage.adjust_paper_balance"), \
         patch("live_trading.trading_storage.update_position_progress"):
        live_trading.handle_price_tick("BTCUSDT", price=110.0)

    events = trading_storage.get_trade_events(111)

    assert [(e["symbol"], e["event"], e["pnl"]) for e in events] == [("BTCUSDT", "tp1_hit", 10.0)]


def test_stop_loss_is_recorded_as_trade_event():
    _make_open_position()
    with patch("live_trading.trading_storage.adjust_paper_balance"), \
         patch("live_trading.trading_storage.close_position"):
        live_trading.handle_price_tick("BTCUSDT", price=96.0)

    events = trading_storage.get_trade_events(111)

    assert [(e["event"], e["pnl"]) for e in events] == [("closed_stop_loss", -16.0)]


def test_pump_timeout_close_is_recorded_as_trade_event():
    _make_open_position(direction="short", opened_hours_ago=25)
    with patch("live_trading.trading_storage.adjust_paper_balance"), \
         patch("live_trading.trading_storage.close_position"):
        live_trading.handle_price_tick("BTCUSDT", price=95.0)

    events = trading_storage.get_trade_events(111)

    assert [(e["event"], e["pnl"]) for e in events] == [("closed_timeout_24h", 20.0)]


def test_breakeven_and_chandelier_activation_are_not_recorded():
    state = _make_open_position()
    state.take_profits[0]["filled"] = True
    state.tp_hit_count = 1
    state.remaining_quantity = 3.0
    with patch("live_trading.trading_storage.adjust_paper_balance"), \
         patch("live_trading.trading_storage.update_position_stop_loss"), \
         patch("live_trading.trading_storage.update_position_progress"):
        live_trading.handle_price_tick("BTCUSDT", price=120.0)  # tp2_hit + moved_to_breakeven

    assert [e["event"] for e in trading_storage.get_trade_events(111)] == ["tp2_hit"]


def test_recording_failure_does_not_break_trading():
    _make_open_position()
    with patch("live_trading.trading_storage.adjust_paper_balance") as mock_adjust, \
         patch("live_trading.trading_storage.update_position_progress"), \
         patch("live_trading.trading_storage.record_trade_event", side_effect=RuntimeError("db down")):
        events = live_trading.handle_price_tick("BTCUSDT", price=110.0)

    assert events == ["tp1_hit"]
    mock_adjust.assert_called_once()
