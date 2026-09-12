import pytest
from unittest.mock import patch

import order_executor
import live_trading
import emergency_controls


def setup_function():
    live_trading._pending_setups.clear()
    live_trading._open_positions.clear()


def test_stop_trading_calls_set_trading_active_false():
    with patch("emergency_controls.trading_storage.set_trading_active") as mock_set:
        emergency_controls.stop_trading(111)
    mock_set.assert_called_once_with(111, False)


def test_start_trading_calls_set_trading_active_true():
    with patch("emergency_controls.trading_storage.set_trading_active") as mock_set:
        emergency_controls.start_trading(111)
    mock_set.assert_called_once_with(111, True)


def test_close_all_positions_now_forces_stop_loss_to_trigger_on_next_tick():
    long_state = order_executor.OpenPositionState(
        position_id=1, direction="long", avg_entry_price=100.0, quantity=1.0,
        stop_loss=97.0, take_profits=[], breakeven_after_tp=2,
    )
    short_state = order_executor.OpenPositionState(
        position_id=2, direction="short", avg_entry_price=100.0, quantity=1.0,
        stop_loss=103.0, take_profits=[], breakeven_after_tp=2,
    )
    live_trading._open_positions["BTCUSDT"] = {"chat_id": 111, "state": long_state, "atr_1h": 2.0}
    live_trading._open_positions["ETHUSDT"] = {"chat_id": 111, "state": short_state, "atr_1h": 2.0}
    live_trading._open_positions["SOLUSDT"] = {"chat_id": 222, "state": long_state, "atr_1h": 2.0}  # другой пользователь

    closed_symbols = emergency_controls.close_all_positions_now(111)

    assert set(closed_symbols) == {"BTCUSDT", "ETHUSDT"}
    assert long_state.stop_loss == float("inf")
    assert short_state.stop_loss == float("-inf")
    # Следующий тик любой ценой должен закрыть позицию через штатный check_stop_hit()
    result = order_executor.check_stop_hit(long_state, price=99.0, atr_1h=2.0)
    assert result["event"] == "closed_stop_loss"


def test_close_all_positions_now_resets_active_chandelier():
    state = order_executor.OpenPositionState(
        position_id=1, direction="long", avg_entry_price=100.0, quantity=1.0,
        stop_loss=97.0, take_profits=[], breakeven_after_tp=2,
    )
    state.chandelier = order_executor.ChandelierTrailingStop(direction="long")
    state.chandelier.update(price=120.0, atr=2.0)  # трейлинг уже активен, стоп где-то около 115
    live_trading._open_positions["BTCUSDT"] = {"chat_id": 111, "state": state, "atr_1h": 2.0}

    emergency_controls.close_all_positions_now(111)

    assert state.chandelier is None  # сброшен -- сработает обычный (принудительный) SL, не Chandelier


def test_move_all_to_breakeven_plus_now_updates_stop_and_db():
    state = order_executor.OpenPositionState(
        position_id=1, direction="long", avg_entry_price=100.0, quantity=1.0,
        stop_loss=97.0, take_profits=[], breakeven_after_tp=2,
    )
    live_trading._open_positions["BTCUSDT"] = {"chat_id": 111, "state": state, "atr_1h": 2.0}

    with patch("emergency_controls.trading_storage.update_position_stop_loss") as mock_update:
        updated = emergency_controls.move_all_to_breakeven_plus_now(111)

    assert updated == ["BTCUSDT"]
    assert state.stop_loss == pytest.approx(100.08)  # 100 * 1.0008
    mock_update.assert_called_once_with(1, pytest.approx(100.08))


def test_move_all_to_breakeven_plus_now_skips_positions_on_chandelier():
    state = order_executor.OpenPositionState(
        position_id=1, direction="long", avg_entry_price=100.0, quantity=1.0,
        stop_loss=97.0, take_profits=[], breakeven_after_tp=2,
    )
    state.chandelier = order_executor.ChandelierTrailingStop(direction="long")
    live_trading._open_positions["BTCUSDT"] = {"chat_id": 111, "state": state, "atr_1h": 2.0}

    with patch("emergency_controls.trading_storage.update_position_stop_loss") as mock_update:
        updated = emergency_controls.move_all_to_breakeven_plus_now(111)

    assert updated == []
    mock_update.assert_not_called()
