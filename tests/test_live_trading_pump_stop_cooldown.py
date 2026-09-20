from datetime import datetime, timedelta, timezone

import pytest
from unittest.mock import AsyncMock, patch

import live_trading

PROFILE = {
    "is_active": 1, "max_concurrent_trades": 3, "risk_percent": 1.0,
    "sl_method": "atr", "sl_fixed_percent": None, "tp_split_preset": "equal", "breakeven_after_tp": 2,
}


def _analysis(funding_rate=0.0002):
    return {
        "classification": "reversal", "trend_4h": "up", "relevant_divergence": False, "is_climax": False,
        "funding_rate": funding_rate, "oi_diverging": False, "near_significant_level": False,
        "vwap_deviation": 1.0, "atr_15m": 1.0, "atr_1h": 2.0,
    }


def setup_function():
    live_trading._pending_setups.clear()
    live_trading._open_positions.clear()
    live_trading._reserved_symbols.clear()


async def _run(direction, stopped_recently):
    with patch("live_trading.trading_storage.get_profile", return_value=PROFILE), \
         patch("live_trading.trading_storage.get_open_positions", return_value=[]), \
         patch("live_trading.trading_storage.had_recent_stop_out", return_value=stopped_recently) as mock_stop, \
         patch("live_trading.impulse_analysis.analyze_impulse", new=AsyncMock(return_value=_analysis())) as mock_analyze, \
         patch("live_trading.market_data.fetch_klines", new=AsyncMock(return_value=[])), \
         patch("live_trading.trading_storage.create_trade_signal", return_value=99), \
         patch("live_trading.trade_signal_ux.announce_and_execute", new=AsyncMock()):
        result = await live_trading.handle_new_impulse(
            session=None, chat_id=111, symbol="BTCUSDT", exchange="Binance",
            direction=direction, current_price=100.0, window_start_price=70.0,
        )
    return result, mock_stop, mock_analyze


@pytest.mark.asyncio
async def test_pump_setup_skipped_within_cooldown_after_stop_out():
    """
    20.09.2026: живые повторные входы по пампам после стопа -0.53R (n=17, -$985) --
    если памп продолжает идти и выбил стоп, повторный шорт по той же монете хуже среднего.
    """
    result, mock_stop, mock_analyze = await _run("up", stopped_recently=True)

    assert result is None
    mock_analyze.assert_not_called()  # отсекаем до сетевых запросов
    args = mock_stop.call_args[0]
    assert args[:3] == (111, "BTCUSDT", "short")
    since = datetime.strptime(args[3], "%Y-%m-%d %H:%M:%S")
    expected = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=live_trading.PUMP_STOP_COOLDOWN_HOURS)
    assert abs((since - expected).total_seconds()) < 10


@pytest.mark.asyncio
async def test_pump_setup_proceeds_when_no_recent_stop_out():
    result, _, _ = await _run("up", stopped_recently=False)

    assert result == {"classification": "reversal", "signal_id": 99}


@pytest.mark.asyncio
async def test_dump_setup_is_never_blocked_by_cooldown():
    """Для дампов повторные входы после стопа в плюсе (+0.09R) -- правило только для пампов."""
    result, mock_stop, _ = await _run("down", stopped_recently=True)

    assert result == {"classification": "reversal", "signal_id": 99}
    mock_stop.assert_not_called()


def test_cooldown_is_24_hours():
    assert live_trading.PUMP_STOP_COOLDOWN_HOURS == 24
