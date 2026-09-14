import pytest
from unittest.mock import AsyncMock, patch

import entry_engine
import live_trading


def setup_function():
    live_trading._pending_setups.clear()
    live_trading._open_positions.clear()


def _make_pending_setup(direction="up"):
    return {
        "chat_id": 111, "exchange": "Binance", "signal_id": 55,
        "impulse_direction": direction, "window_start_price": 70.0,
        "cap_reference_price": 100.0, "last_atr_refresh_price": 151.0,
        "trigger_part1": entry_engine.create_part1_trigger(direction, atr_15m=1.0),  # distance 0.75
        "trigger_part2": entry_engine.create_part2_trigger(direction, atr_15m=1.0),  # distance 2.0
        "part_size": 2.0, "atr_1h": 2.0, "magnet_levels": [], "profile": {},
    }


@pytest.mark.asyncio
async def test_refresh_updates_trigger_distances_and_atr_1h():
    live_trading._pending_setups["BTCUSDT"] = _make_pending_setup()

    with patch("live_trading.market_data.fetch_klines", new=AsyncMock(return_value=[{"dummy": True}])), \
         patch("live_trading.indicators.atr", side_effect=[[3.0], [6.0]]):
        await live_trading.refresh_pending_setup_atr(session=None, symbol="BTCUSDT")

    setup = live_trading._pending_setups["BTCUSDT"]
    assert setup["trigger_part1"].trigger_distance == pytest.approx(3.0 * entry_engine.PART1_ATR_MULTIPLIER)
    assert setup["trigger_part2"].trigger_distance == pytest.approx(3.0 * entry_engine.PART2_ATR_MULTIPLIER)
    assert setup["atr_1h"] == pytest.approx(6.0)


@pytest.mark.asyncio
async def test_refresh_preserves_already_tracked_extreme_price():
    setup = _make_pending_setup()
    setup["trigger_part1"].update(100.0)  # экстремум части 1 = 100 (уже отслеживается)
    live_trading._pending_setups["BTCUSDT"] = setup

    with patch("live_trading.market_data.fetch_klines", new=AsyncMock(return_value=[{"dummy": True}])), \
         patch("live_trading.indicators.atr", side_effect=[[3.0], [6.0]]):
        await live_trading.refresh_pending_setup_atr(session=None, symbol="BTCUSDT")

    assert live_trading._pending_setups["BTCUSDT"]["trigger_part1"].extreme_price == 100.0


@pytest.mark.asyncio
async def test_refresh_does_nothing_when_setup_already_gone():
    with patch("live_trading.market_data.fetch_klines", new=AsyncMock(return_value=[{"dummy": True}])) as mock_fetch:
        await live_trading.refresh_pending_setup_atr(session=None, symbol="UNKNOWN")

    mock_fetch.assert_not_called()


@pytest.mark.asyncio
async def test_refresh_does_nothing_when_atr_unavailable():
    live_trading._pending_setups["BTCUSDT"] = _make_pending_setup()

    with patch("live_trading.market_data.fetch_klines", new=AsyncMock(return_value=[])), \
         patch("live_trading.indicators.atr", return_value=[]):
        await live_trading.refresh_pending_setup_atr(session=None, symbol="BTCUSDT")

    setup = live_trading._pending_setups["BTCUSDT"]
    assert setup["trigger_part1"].trigger_distance == pytest.approx(0.75)  # не изменилось
