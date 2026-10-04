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


def _candle(close, high=None, low=None):
    return {"open_time": 0, "close": close, "high": high if high is not None else close, "low": low if low is not None else close}


def _klines_with_atr(n=60, base=1.0):
    """n свечей с небольшим разбросом high/low -- достаточно для atr(period=14) не-None."""
    out = []
    price = base
    for i in range(n):
        high = price * 1.01
        low = price * 0.99
        out.append({"open_time": i, "close": price, "high": high, "low": low})
        price *= 1.001
    return out


@pytest.mark.asyncio
async def test_handle_channel_signal_none_when_atr_unavailable():
    with patch("live_trading.trading_storage.get_profile", return_value=PROFILE), \
         patch("live_trading.trading_storage.get_open_positions", return_value=[]), \
         patch("live_trading.market_data.fetch_klines", new=AsyncMock(side_effect=[
             [_candle(1.0)],   # _resolve_channel_signal_exchange: Binance -- найдено
             [_candle(1.0)] * 2,  # candles_15m: слишком мало для ATR(14)
             [_candle(1.0)] * 2,  # candles_1h: слишком мало для ATR(14)
         ])):
        result = await live_trading.handle_channel_signal(
            session=None, chat_id=111, ticker="XAI", channel_direction="short",
        )
    assert result is None


@pytest.mark.asyncio
async def test_handle_channel_signal_short_maps_to_pump_risk_and_executes():
    klines_1h = _klines_with_atr(n=24)
    klines_15m = _klines_with_atr(n=50)
    with patch("live_trading.trading_storage.get_profile", return_value=PROFILE), \
         patch("live_trading.trading_storage.get_open_positions", return_value=[]), \
         patch("live_trading.market_data.fetch_klines", new=AsyncMock(side_effect=[
             [klines_1h[-1]],  # резолв биржи -- Binance
             klines_15m, klines_1h,  # ATR
             [], [],  # daily/weekly для magnet_levels
         ])), \
         patch("live_trading.magnet_levels_module.find_magnet_levels", return_value=[]), \
         patch("live_trading.trading_storage.create_trade_signal", return_value=99) as mock_create_signal, \
         patch("live_trading.send_text", new=AsyncMock()), \
         patch("live_trading.execute_setup", new=AsyncMock(return_value={"classification": "reversal", "signal_id": 99})) as mock_execute:
        result = await live_trading.handle_channel_signal(
            session=None, chat_id=111, ticker="XAI", channel_direction="short",
        )

    assert result == {"classification": "reversal", "signal_id": 99}
    mock_create_signal.assert_called_once()
    assert mock_create_signal.call_args.kwargs["source"] == "channel"
    assert mock_create_signal.call_args.kwargs["impulse_direction"] == "up"
    mock_execute.assert_called_once()
    assert mock_execute.call_args.args[4] == "up"  # direction
    assert mock_execute.call_args.args[5] == "reversal"  # classification


@pytest.mark.asyncio
async def test_handle_channel_signal_long_maps_to_dump_risk_direction():
    klines_1h = _klines_with_atr(n=24)
    klines_15m = _klines_with_atr(n=50)
    with patch("live_trading.trading_storage.get_profile", return_value=PROFILE), \
         patch("live_trading.trading_storage.get_open_positions", return_value=[]), \
         patch("live_trading.market_data.fetch_klines", new=AsyncMock(side_effect=[
             [klines_1h[-1]],
             klines_15m, klines_1h,
             [], [],
         ])), \
         patch("live_trading.magnet_levels_module.find_magnet_levels", return_value=[]), \
         patch("live_trading.trading_storage.create_trade_signal", return_value=100), \
         patch("live_trading.send_text", new=AsyncMock()), \
         patch("live_trading.execute_setup", new=AsyncMock(return_value={"classification": "reversal", "signal_id": 100})) as mock_execute:
        result = await live_trading.handle_channel_signal(
            session=None, chat_id=111, ticker="CELO", channel_direction="long",
        )

    assert result is not None
    assert mock_execute.call_args.args[4] == "down"  # direction


@pytest.mark.asyncio
async def test_handle_channel_signal_resolves_bybit_when_not_on_binance():
    klines_1h = _klines_with_atr(n=24)
    klines_15m = _klines_with_atr(n=50)
    with patch("live_trading.trading_storage.get_profile", return_value=PROFILE), \
         patch("live_trading.trading_storage.get_open_positions", return_value=[]), \
         patch("live_trading.market_data.fetch_klines", new=AsyncMock(side_effect=[
             [],              # Binance -- не найдено
             [klines_1h[-1]],  # Bybit -- найдено
             klines_15m, klines_1h,
             [], [],
         ])), \
         patch("live_trading.magnet_levels_module.find_magnet_levels", return_value=[]), \
         patch("live_trading.trading_storage.create_trade_signal", return_value=101), \
         patch("live_trading.send_text", new=AsyncMock()), \
         patch("live_trading.execute_setup", new=AsyncMock(return_value={"classification": "reversal", "signal_id": 101})) as mock_execute:
        result = await live_trading.handle_channel_signal(
            session=None, chat_id=111, ticker="ZKJ", channel_direction="long",
        )

    assert result is not None
    assert mock_execute.call_args.args[3] == "Bybit"  # exchange
