import pytest
from unittest.mock import AsyncMock, patch

import live_trading


def setup_function():
    live_trading._pending_setups.clear()
    live_trading._open_positions.clear()


REVERSAL_PROFILE = {
    "is_active": 1, "max_concurrent_trades": 3, "risk_percent": 1.0,
    "sl_method": "atr", "sl_fixed_percent": None, "tp_split_preset": "equal",
    "breakeven_after_tp": 2,
}

ANALYSIS_RESULT_REVERSAL = {
    "classification": "reversal", "trend_4h": "down", "relevant_divergence": True,
    "is_climax": True, "funding_rate": 0.002, "oi_diverging": False,
    "near_significant_level": False, "vwap_deviation": 1.0, "atr_15m": 1.0, "atr_1h": 2.0,
}


@pytest.mark.asyncio
async def test_reversal_creates_pending_setup_with_both_triggers():
    async def fake_fetch_klines(session, exchange, symbol, interval, limit=100):
        return []  # магнит-уровни на пустой истории -> просто пустой список уровней

    with patch("live_trading.trading_storage.get_paper_balance", return_value=1000.0), \
         patch("live_trading.market_data.fetch_klines", new=AsyncMock(side_effect=fake_fetch_klines)):
        result = await live_trading.execute_setup(
            session=None, chat_id=111, symbol="BTCUSDT", exchange="Binance", direction="up",
            classification="reversal", current_price=100.0, window_start_price=70.0,
            profile=REVERSAL_PROFILE, analysis=ANALYSIS_RESULT_REVERSAL, signal_id=55,
        )

    assert result["classification"] == "reversal"
    assert result["signal_id"] == 55
    assert "BTCUSDT" in live_trading._pending_setups
    setup = live_trading._pending_setups["BTCUSDT"]
    assert setup["trigger_part1"].fired is False
    assert setup["trigger_part2"].fired is False
    assert setup["trigger_part1"].trigger_distance == pytest.approx(0.75)  # 0.75 * atr_15m(1.0)
    assert setup["trigger_part2"].trigger_distance == pytest.approx(2.0)   # 2.0 * atr_15m(1.0)
    assert setup["part_size"] > 0
    assert setup["chat_id"] == 111
    assert setup["exchange"] == "Binance"
    assert setup["profile"] == REVERSAL_PROFILE
