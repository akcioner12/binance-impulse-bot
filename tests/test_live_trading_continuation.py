import pytest
from unittest.mock import patch

import live_trading


def setup_function():
    live_trading._pending_setups.clear()
    live_trading._open_positions.clear()


CONTINUATION_PROFILE = {
    "is_active": 1, "max_concurrent_trades": 3, "risk_percent": 1.0,
    "sl_method": "atr", "sl_fixed_percent": None, "tp_split_preset": "equal",
    "breakeven_after_tp": 2,
}

ANALYSIS_RESULT_CONTINUATION = {
    "classification": "continuation", "trend_4h": "up", "relevant_divergence": False,
    "is_climax": False, "funding_rate": 0.0001, "oi_diverging": False,
    "near_significant_level": False, "vwap_deviation": 1.0, "atr_15m": 1.0, "atr_1h": 2.0,
}


@pytest.mark.asyncio
async def test_continuation_opens_position_immediately():
    with patch("live_trading.trading_storage.get_paper_balance", return_value=1000.0), \
         patch("live_trading.trading_storage.update_trade_signal_status") as mock_update_status, \
         patch("live_trading.trading_storage.create_position", return_value=7), \
         patch("live_trading._compute_wave_size_multiplier", return_value=1.0):
        result = await live_trading.execute_setup(
            session=None, chat_id=111, symbol="BTCUSDT", exchange="Binance", direction="up",
            classification="continuation", current_price=100.0, window_start_price=70.0,
            profile=CONTINUATION_PROFILE, analysis=ANALYSIS_RESULT_CONTINUATION, signal_id=42,
        )

    assert result["classification"] == "continuation"
    assert result["position_id"] == 7
    assert "BTCUSDT" in live_trading._open_positions
    state = live_trading._open_positions["BTCUSDT"]["state"]
    assert state.direction == "long"  # continuation + 'up' -> long
    mock_update_status.assert_called_once_with(42, "executed")


@pytest.mark.asyncio
async def test_continuation_short_direction_for_down_impulse():
    with patch("live_trading.trading_storage.get_paper_balance", return_value=1000.0), \
         patch("live_trading.trading_storage.update_trade_signal_status"), \
         patch("live_trading.trading_storage.create_position", return_value=8), \
         patch("live_trading._compute_wave_size_multiplier", return_value=1.0):
        await live_trading.execute_setup(
            session=None, chat_id=111, symbol="ETHUSDT", exchange="Binance", direction="down",
            classification="continuation", current_price=100.0, window_start_price=140.0,
            profile=CONTINUATION_PROFILE, analysis=ANALYSIS_RESULT_CONTINUATION, signal_id=43,
        )

    state = live_trading._open_positions["ETHUSDT"]["state"]
    assert state.direction == "short"  # continuation + 'down' -> short
