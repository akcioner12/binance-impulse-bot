import pytest
from unittest.mock import AsyncMock, patch

import live_trading


def setup_function():
    live_trading._pending_setups.clear()
    live_trading._open_positions.clear()


PROFILE = {
    "is_active": 1, "max_concurrent_trades": 3, "risk_percent": 1.0,
    "sl_method": "atr", "sl_fixed_percent": None, "tp_split_preset": "equal",
    "breakeven_after_tp": 2,
}

ANALYSIS_REVERSAL = {
    "classification": "reversal", "trend_4h": "down", "relevant_divergence": True,
    "is_climax": True, "funding_rate": 0.002, "oi_diverging": False,
    "near_significant_level": False, "vwap_deviation": 1.0, "atr_15m": 1.0, "atr_1h": 2.0,
}


@pytest.mark.asyncio
async def test_handle_new_impulse_executes_setup_right_away_without_waiting_for_confirmation():
    async def fake_fetch_klines(session, exchange, symbol, interval, limit=100):
        return []

    with patch("live_trading.trading_storage.get_profile", return_value=PROFILE), \
         patch("live_trading.trading_storage.get_open_positions", return_value=[]), \
         patch("live_trading.trading_storage.create_trade_signal", return_value=55), \
         patch("live_trading.impulse_analysis.analyze_impulse", new=AsyncMock(return_value=ANALYSIS_REVERSAL)), \
         patch("live_trading.market_data.fetch_klines", new=AsyncMock(side_effect=fake_fetch_klines)), \
         patch("live_trading.execute_setup", new=AsyncMock(return_value={"classification": "reversal", "signal_id": 55})) as mock_execute, \
         patch("trade_signal_ux.send_text", new=AsyncMock()):
        result = await live_trading.handle_new_impulse(
            session=None, chat_id=111, symbol="BTCUSDT", exchange="Binance",
            direction="up", current_price=100.0, window_start_price=70.0,
        )

    mock_execute.assert_awaited_once()
    assert result == {"classification": "reversal", "signal_id": 55}
    assert "awaiting_confirmation" not in result
