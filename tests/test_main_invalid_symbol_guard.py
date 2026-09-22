import pytest
from unittest.mock import patch

import main


@pytest.mark.asyncio
async def test_on_kline_close_ignores_non_ascii_symbol_without_touching_trackers():
    """
    22.09.2026: в проде обнаружены реальные позиции/события с "символами" вроде
    "牛来USDT" и "龙虾USDT" -- не существующие на бирже пары, реального PnL по ним
    не может быть, но бот открывал по ним paper-позиции и терял на этом деньги
    (see docs/LOGIC_CHANGELOG.md, 22.09). Источник конкретной порчи не найден
    (возможно повреждение в цепочке WS/декодирования) -- защита здесь: не пускать
    такой "символ" ни в трекеры, ни в автотрейдинг, ни разу не расходуя цену.
    """
    with patch.object(main.tracker, "update") as mock_tracker_update, \
         patch.object(main.dump_tracker, "update") as mock_dump_update, \
         patch("main.live_trading.handle_price_tick") as mock_tick:
        await main.on_kline_close("牛来USDT", "Binance", 0.1, 1000)

    mock_tracker_update.assert_not_called()
    mock_dump_update.assert_not_called()
    mock_tick.assert_not_called()


@pytest.mark.asyncio
async def test_on_kline_close_still_processes_normal_ascii_symbol():
    with patch.object(main.tracker, "update", return_value=None) as mock_tracker_update, \
         patch.object(main.tracker, "is_active", return_value=True), \
         patch.object(main.dump_tracker, "update", return_value=None), \
         patch("main.live_trading.handle_price_tick", return_value=None):
        await main.on_kline_close("BTCUSDT", "Binance", 100.0, 1000)

    mock_tracker_update.assert_called_once()
