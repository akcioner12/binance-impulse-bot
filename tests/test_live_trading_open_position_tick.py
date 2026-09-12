import pytest
from unittest.mock import patch

import order_executor
import live_trading


def setup_function():
    live_trading._pending_setups.clear()
    live_trading._open_positions.clear()


def _make_open_position():
    state = order_executor.OpenPositionState(
        position_id=1, direction="long", avg_entry_price=100.0, quantity=4.0,
        stop_loss=97.0,
        take_profits=[{"level": 110.0, "size_pct": 25}, {"level": 120.0, "size_pct": 25}, {"level": 130.0, "size_pct": 25}],
        breakeven_after_tp=2,
    )
    live_trading._open_positions["BTCUSDT"] = {"chat_id": 111, "state": state, "atr_1h": 2.0}
    return state


def test_tick_tp1_hit_adjusts_paper_balance():
    _make_open_position()
    with patch("live_trading.trading_storage.adjust_paper_balance") as mock_adjust:
        events = live_trading.handle_price_tick("BTCUSDT", price=110.0)

    assert events == ["tp1_hit"]
    mock_adjust.assert_called_once_with(111, 10.0)  # 1.0 * (110-100)
    assert "BTCUSDT" in live_trading._open_positions  # позиция ещё открыта


def test_tick_stop_loss_hit_closes_position_and_removes_from_state():
    _make_open_position()
    with patch("live_trading.trading_storage.adjust_paper_balance") as mock_adjust, \
         patch("live_trading.trading_storage.close_position") as mock_close:
        events = live_trading.handle_price_tick("BTCUSDT", price=96.0)

    assert events == ["closed_stop_loss"]
    mock_adjust.assert_called_once_with(111, -16.0)  # 4.0 * (96-100)
    mock_close.assert_called_once_with(1, realized_pnl=-16.0)
    assert "BTCUSDT" not in live_trading._open_positions


def test_tick_moved_to_breakeven_updates_db_stop_loss():
    state = _make_open_position()
    state.take_profits[0]["filled"] = True  # TP1 уже сработал ранее
    state.tp_hit_count = 1
    state.remaining_quantity = 3.0

    with patch("live_trading.trading_storage.adjust_paper_balance"), \
         patch("live_trading.trading_storage.update_position_stop_loss") as mock_update_sl:
        events = live_trading.handle_price_tick("BTCUSDT", price=120.0)  # TP2 -> безубыток+

    assert "tp2_hit" in events
    assert "moved_to_breakeven" in events
    mock_update_sl.assert_called_once()
    assert mock_update_sl.call_args[0][0] == 1  # position_id


def test_tick_returns_none_when_no_stop_or_tp_event():
    _make_open_position()
    events = live_trading.handle_price_tick("BTCUSDT", price=105.0)  # между входом и TP1
    assert events is None
