import pytest
from unittest.mock import AsyncMock, patch

import live_trading


def setup_function():
    live_trading._pending_setups.clear()
    live_trading._open_positions.clear()
    live_trading._reserved_symbols.clear()


PROFILE = {"is_active": 1, "max_concurrent_trades": 3, "sl_method": "atr", "sl_fixed_percent": 2.0}


@pytest.mark.asyncio
async def test_handle_channel_signal_none_for_unknown_direction_word():
    result = await live_trading.handle_channel_signal(
        session=None, chat_id=111, ticker="XAI", channel_direction="moon",
    )
    assert result is None


@pytest.mark.asyncio
async def test_handle_channel_signal_none_when_no_profile():
    with patch("live_trading.trading_storage.get_profile", return_value=None):
        result = await live_trading.handle_channel_signal(
            session=None, chat_id=111, ticker="XAI", channel_direction="short",
        )
    assert result is None


@pytest.mark.asyncio
async def test_handle_channel_signal_none_when_profile_inactive():
    with patch("live_trading.trading_storage.get_profile", return_value={"is_active": 0}):
        result = await live_trading.handle_channel_signal(
            session=None, chat_id=111, ticker="XAI", channel_direction="short",
        )
    assert result is None


@pytest.mark.asyncio
async def test_handle_channel_signal_none_when_symbol_blacklisted():
    with patch("live_trading.trading_storage.get_profile", return_value=PROFILE):
        result = await live_trading.handle_channel_signal(
            session=None, chat_id=111, ticker="CLO", channel_direction="short",
        )
    assert result is None


@pytest.mark.asyncio
async def test_handle_channel_signal_none_when_symbol_already_pending():
    live_trading._pending_setups["XAIUSDT"] = {"dummy": True}
    with patch("live_trading.trading_storage.get_profile", return_value=PROFILE):
        result = await live_trading.handle_channel_signal(
            session=None, chat_id=111, ticker="XAI", channel_direction="short",
        )
    assert result is None


@pytest.mark.asyncio
async def test_handle_channel_signal_none_when_symbol_already_open():
    live_trading._open_positions["XAIUSDT"] = {"dummy": True}
    with patch("live_trading.trading_storage.get_profile", return_value=PROFILE):
        result = await live_trading.handle_channel_signal(
            session=None, chat_id=111, ticker="XAI", channel_direction="short",
        )
    assert result is None


@pytest.mark.asyncio
async def test_handle_channel_signal_none_when_at_max_concurrent_trades():
    profile = {**PROFILE, "max_concurrent_trades": 1}
    with patch("live_trading.trading_storage.get_profile", return_value=profile), \
         patch("live_trading.trading_storage.get_open_positions", return_value=[{"id": 1}]):
        result = await live_trading.handle_channel_signal(
            session=None, chat_id=111, ticker="XAI", channel_direction="short",
        )
    assert result is None


@pytest.mark.asyncio
async def test_handle_channel_signal_none_when_symbol_not_found_on_either_exchange():
    with patch("live_trading.trading_storage.get_profile", return_value=PROFILE), \
         patch("live_trading.trading_storage.get_open_positions", return_value=[]), \
         patch("live_trading.market_data.fetch_klines", new=AsyncMock(return_value=[])):
        result = await live_trading.handle_channel_signal(
            session=None, chat_id=111, ticker="NOPE", channel_direction="short",
        )
    assert result is None
    assert "NOPEUSDT" not in live_trading._reserved_symbols  # слот освобождён
