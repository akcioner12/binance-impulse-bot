from unittest.mock import patch

import live_trading


def setup_function():
    live_trading._pending_setups.clear()
    live_trading._open_positions.clear()


def test_reset_all_state_clears_in_memory_pending_and_open():
    live_trading._pending_setups["BTCUSDT"] = {"dummy": True}
    live_trading._open_positions["ETHUSDT"] = {"dummy": True}

    with patch("live_trading.trading_storage.reset_paper_trading") as mock_reset:
        live_trading.reset_all_state(chat_id=111, starting_balance=10000.0)

    assert live_trading._pending_setups == {}
    assert live_trading._open_positions == {}
    mock_reset.assert_called_once_with(111, starting_balance=10000.0)
