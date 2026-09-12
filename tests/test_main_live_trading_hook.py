import pytest
from unittest.mock import patch

import main


@pytest.mark.asyncio
async def test_on_kline_close_calls_handle_price_tick_every_time_even_without_signal():
    with patch.object(main.tracker, "update", return_value=None), \
         patch.object(main.tracker, "is_active", return_value=True), \
         patch("main.live_trading.handle_price_tick", return_value=None) as mock_tick:
        await main.on_kline_close("BTCUSDT", "Binance", 100.0, 1000)

    mock_tick.assert_called_once_with("BTCUSDT", 100.0)


@pytest.mark.asyncio
async def test_on_kline_close_swallows_errors_from_handle_price_tick():
    with patch.object(main.tracker, "update", return_value=None), \
         patch.object(main.tracker, "is_active", return_value=True), \
         patch("main.live_trading.handle_price_tick", side_effect=RuntimeError("boom")):
        await main.on_kline_close("BTCUSDT", "Binance", 100.0, 1000)  # не должно упасть
