import pytest
from unittest.mock import AsyncMock, patch

import live_trading


def setup_function():
    live_trading._pending_setups.clear()
    live_trading._open_positions.clear()


@pytest.mark.asyncio
async def test_handle_new_impulse_none_when_no_profile():
    with patch("live_trading.trading_storage.get_profile", return_value=None):
        result = await live_trading.handle_new_impulse(
            session=None, chat_id=111, symbol="BTCUSDT", exchange="Binance",
            direction="up", current_price=100.0, window_start_price=70.0,
        )
    assert result is None


@pytest.mark.asyncio
async def test_handle_new_impulse_none_when_profile_inactive():
    with patch("live_trading.trading_storage.get_profile", return_value={"is_active": 0}):
        result = await live_trading.handle_new_impulse(
            session=None, chat_id=111, symbol="BTCUSDT", exchange="Binance",
            direction="up", current_price=100.0, window_start_price=70.0,
        )
    assert result is None


@pytest.mark.asyncio
async def test_handle_new_impulse_none_when_symbol_already_pending():
    live_trading._pending_setups["BTCUSDT"] = {"dummy": True}
    with patch("live_trading.trading_storage.get_profile", return_value={"is_active": 1, "max_concurrent_trades": 3}):
        result = await live_trading.handle_new_impulse(
            session=None, chat_id=111, symbol="BTCUSDT", exchange="Binance",
            direction="up", current_price=100.0, window_start_price=70.0,
        )
    assert result is None


@pytest.mark.asyncio
async def test_handle_new_impulse_none_when_symbol_already_open():
    live_trading._open_positions["BTCUSDT"] = {"dummy": True}
    with patch("live_trading.trading_storage.get_profile", return_value={"is_active": 1, "max_concurrent_trades": 3}):
        result = await live_trading.handle_new_impulse(
            session=None, chat_id=111, symbol="BTCUSDT", exchange="Binance",
            direction="up", current_price=100.0, window_start_price=70.0,
        )
    assert result is None


@pytest.mark.asyncio
async def test_handle_new_impulse_none_when_at_max_concurrent_trades():
    profile = {"is_active": 1, "max_concurrent_trades": 1}
    with patch("live_trading.trading_storage.get_profile", return_value=profile), \
         patch("live_trading.trading_storage.get_open_positions", return_value=[{"id": 1}]):
        result = await live_trading.handle_new_impulse(
            session=None, chat_id=111, symbol="BTCUSDT", exchange="Binance",
            direction="up", current_price=100.0, window_start_price=70.0,
        )
    assert result is None
