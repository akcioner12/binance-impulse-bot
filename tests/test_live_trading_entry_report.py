import pytest

import order_executor
import live_trading


def setup_function():
    live_trading._pending_setups.clear()
    live_trading._open_positions.clear()


def test_get_position_snapshot_returns_none_when_no_position():
    assert live_trading.get_position_snapshot("BTCUSDT") is None


def test_get_position_snapshot_returns_full_details():
    state = order_executor.OpenPositionState(
        position_id=5, direction="short", avg_entry_price=1.7999, quantity=210.5,
        stop_loss=1.9424,
        take_profits=[
            {"level": 1.6574, "size_pct": 15},
            {"level": 1.5149, "size_pct": 20},
            {"level": 1.3724, "size_pct": 25},
        ],
        breakeven_after_tp=2,
    )
    live_trading._open_positions["LSKUSDT"] = {"chat_id": 111, "state": state, "atr_1h": 0.095}

    snapshot = live_trading.get_position_snapshot("LSKUSDT")

    assert snapshot["chat_id"] == 111
    assert snapshot["direction"] == "short"
    assert snapshot["avg_entry_price"] == 1.7999
    assert snapshot["quantity"] == 210.5
    assert snapshot["stop_loss"] == 1.9424
    assert snapshot["take_profits"] == [
        {"level": 1.6574, "size_pct": 15},
        {"level": 1.5149, "size_pct": 20},
        {"level": 1.3724, "size_pct": 25},
    ]
    assert snapshot["tp4_size_pct"] == 40  # 100 - (15+20+25)
    assert snapshot["risk_amount"] == pytest.approx(210.5 * abs(1.7999 - 1.9424))
