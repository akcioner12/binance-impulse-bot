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


PROFILE = {"is_active": 1, "max_concurrent_trades": 3}


def _analysis(classification, funding_rate):
    return {
        "classification": classification, "trend_4h": "up", "relevant_divergence": False,
        "is_climax": False, "funding_rate": funding_rate, "oi_diverging": False,
        "near_significant_level": False, "vwap_deviation": 1.0, "atr_15m": 1.0, "atr_1h": 2.0,
    }


@pytest.mark.asyncio
async def test_handle_new_impulse_skips_pump_reversal_with_weak_funding():
    """
    Ретроспектива 13-14.09.2026: фейд пампа без экстремального funding rate не
    показывает эджа (avgR около нуля или в минус) -- топ-20% по экстремальности
    funding (>=0.00012) дают avgR +0.46 (t=4.94), остальные -- нет. Слабый funding
    -- сигнал вообще не создаётся, чтобы не слать пользователю запрос на
    подтверждение по заведомо неинтересному сетапу.
    """
    with patch("live_trading.trading_storage.get_profile", return_value=PROFILE), \
         patch("live_trading.trading_storage.get_open_positions", return_value=[]), \
         patch("live_trading.impulse_analysis.analyze_impulse", new=AsyncMock(
             return_value=_analysis("reversal", funding_rate=0.00005))), \
         patch("live_trading.trading_storage.create_trade_signal") as mock_create_signal, \
         patch("live_trading.trade_signal_ux.request_confirmation", new=AsyncMock()) as mock_request:
        result = await live_trading.handle_new_impulse(
            session=None, chat_id=111, symbol="BTCUSDT", exchange="Binance",
            direction="up", current_price=100.0, window_start_price=70.0,
        )

    assert result is None
    mock_create_signal.assert_not_called()
    mock_request.assert_not_called()


@pytest.mark.asyncio
async def test_handle_new_impulse_proceeds_pump_reversal_with_extreme_funding():
    with patch("live_trading.trading_storage.get_profile", return_value=PROFILE), \
         patch("live_trading.trading_storage.get_open_positions", return_value=[]), \
         patch("live_trading.impulse_analysis.analyze_impulse", new=AsyncMock(
             return_value=_analysis("reversal", funding_rate=0.0002))), \
         patch("live_trading.market_data.fetch_klines", new=AsyncMock(return_value=[])), \
         patch("live_trading.trading_storage.create_trade_signal", return_value=99), \
         patch("live_trading.trade_signal_ux.request_confirmation", new=AsyncMock()) as mock_request:
        result = await live_trading.handle_new_impulse(
            session=None, chat_id=111, symbol="BTCUSDT", exchange="Binance",
            direction="up", current_price=100.0, window_start_price=70.0,
        )

    assert result == {"classification": "reversal", "signal_id": 99, "awaiting_confirmation": True}
    mock_request.assert_called_once()


@pytest.mark.asyncio
async def test_handle_new_impulse_computes_real_magnet_levels_for_reversal():
    """
    Прод-баг 14.09.2026: сообщение подтверждения всегда показывало "Магнит-уровни: —"
    для ЛЮБОЙ монеты -- magnet_levels считался ПОСЛЕ отправки сообщения (в
    _create_pending_reversal_setup, уже после подтверждения), а не до. Теперь
    считается заранее и передаётся в само сообщение.
    """
    with patch("live_trading.trading_storage.get_profile", return_value=PROFILE), \
         patch("live_trading.trading_storage.get_open_positions", return_value=[]), \
         patch("live_trading.impulse_analysis.analyze_impulse", new=AsyncMock(
             return_value=_analysis("reversal", funding_rate=0.0002))), \
         patch("live_trading.market_data.fetch_klines", new=AsyncMock(return_value=[])), \
         patch("live_trading.magnet_levels_module.find_magnet_levels", return_value=[150.0, 200.0]) as mock_find, \
         patch("live_trading.trading_storage.create_trade_signal", return_value=99), \
         patch("live_trading.trade_signal_ux.request_confirmation", new=AsyncMock()) as mock_request:
        await live_trading.handle_new_impulse(
            session=None, chat_id=111, symbol="BTCUSDT", exchange="Binance",
            direction="up", current_price=100.0, window_start_price=70.0,
        )

    mock_find.assert_called_once()
    assert mock_request.call_args.kwargs["magnet_levels"] == [150.0, 200.0]


@pytest.mark.asyncio
async def test_handle_new_impulse_skips_magnet_levels_for_continuation():
    with patch("live_trading.trading_storage.get_profile", return_value=PROFILE), \
         patch("live_trading.trading_storage.get_open_positions", return_value=[]), \
         patch("live_trading.impulse_analysis.analyze_impulse", new=AsyncMock(
             return_value=_analysis("continuation", funding_rate=0.00001))), \
         patch("live_trading.magnet_levels_module.find_magnet_levels") as mock_find, \
         patch("live_trading.trading_storage.create_trade_signal", return_value=99), \
         patch("live_trading.trade_signal_ux.request_confirmation", new=AsyncMock()) as mock_request:
        await live_trading.handle_new_impulse(
            session=None, chat_id=111, symbol="BTCUSDT", exchange="Binance",
            direction="up", current_price=100.0, window_start_price=70.0,
        )

    mock_find.assert_not_called()
    assert mock_request.call_args.kwargs["magnet_levels"] == []


@pytest.mark.asyncio
async def test_handle_new_impulse_funding_filter_does_not_apply_to_pump_continuation():
    with patch("live_trading.trading_storage.get_profile", return_value=PROFILE), \
         patch("live_trading.trading_storage.get_open_positions", return_value=[]), \
         patch("live_trading.impulse_analysis.analyze_impulse", new=AsyncMock(
             return_value=_analysis("continuation", funding_rate=0.00001))), \
         patch("live_trading.trading_storage.create_trade_signal", return_value=99), \
         patch("live_trading.trade_signal_ux.request_confirmation", new=AsyncMock()) as mock_request:
        result = await live_trading.handle_new_impulse(
            session=None, chat_id=111, symbol="BTCUSDT", exchange="Binance",
            direction="up", current_price=100.0, window_start_price=70.0,
        )

    assert result is not None
    mock_request.assert_called_once()


@pytest.mark.asyncio
async def test_handle_new_impulse_funding_filter_does_not_apply_to_dumps():
    with patch("live_trading.trading_storage.get_profile", return_value=PROFILE), \
         patch("live_trading.trading_storage.get_open_positions", return_value=[]), \
         patch("live_trading.impulse_analysis.analyze_impulse", new=AsyncMock(
             return_value=_analysis("reversal", funding_rate=0.00001))), \
         patch("live_trading.market_data.fetch_klines", new=AsyncMock(return_value=[])), \
         patch("live_trading.trading_storage.create_trade_signal", return_value=99), \
         patch("live_trading.trade_signal_ux.request_confirmation", new=AsyncMock()) as mock_request:
        result = await live_trading.handle_new_impulse(
            session=None, chat_id=111, symbol="BTCUSDT", exchange="Binance",
            direction="down", current_price=100.0, window_start_price=130.0,
        )

    assert result is not None
    mock_request.assert_called_once()
