import pytest
from unittest.mock import AsyncMock, patch

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
    with patch("live_trading.trading_storage.get_profile", return_value=CONTINUATION_PROFILE), \
         patch("live_trading.trading_storage.get_open_positions", return_value=[]), \
         patch("live_trading.trading_storage.get_paper_balance", return_value=1000.0), \
         patch("live_trading.trading_storage.create_trade_signal", return_value=42), \
         patch("live_trading.trading_storage.update_trade_signal_status") as mock_update_status, \
         patch("live_trading.trading_storage.create_position", return_value=7), \
         patch("live_trading.impulse_analysis.analyze_impulse", new=AsyncMock(return_value=ANALYSIS_RESULT_CONTINUATION)):
        result = await live_trading.handle_new_impulse(
            session=None, chat_id=111, symbol="BTCUSDT", exchange="Binance",
            direction="up", current_price=100.0, window_start_price=70.0,
        )

    assert result["classification"] == "continuation"
    assert result["position_id"] == 7
    assert "BTCUSDT" in live_trading._open_positions
    state = live_trading._open_positions["BTCUSDT"]["state"]
    assert state.direction == "long"  # continuation + 'up' -> long
    mock_update_status.assert_called_once_with(42, "executed")


@pytest.mark.asyncio
async def test_continuation_short_direction_for_down_impulse():
    with patch("live_trading.trading_storage.get_profile", return_value=CONTINUATION_PROFILE), \
         patch("live_trading.trading_storage.get_open_positions", return_value=[]), \
         patch("live_trading.trading_storage.get_paper_balance", return_value=1000.0), \
         patch("live_trading.trading_storage.create_trade_signal", return_value=43), \
         patch("live_trading.trading_storage.update_trade_signal_status"), \
         patch("live_trading.trading_storage.create_position", return_value=8), \
         patch("live_trading.impulse_analysis.analyze_impulse", new=AsyncMock(
             return_value={**ANALYSIS_RESULT_CONTINUATION, "classification": "continuation"}
         )):
        result = await live_trading.handle_new_impulse(
            session=None, chat_id=111, symbol="ETHUSDT", exchange="Binance",
            direction="down", current_price=100.0, window_start_price=140.0,
        )

    state = live_trading._open_positions["ETHUSDT"]["state"]
    assert state.direction == "short"  # continuation + 'down' -> short
