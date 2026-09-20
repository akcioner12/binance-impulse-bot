import inspect
import time
from unittest.mock import patch

import pytest

import main


class _FakeSignal:
    def __init__(self, symbol="BTCUSDT", exchange="Binance", direction="down", level=None,
                 current_price=70.0, window_start_price=100.0):
        self.symbol = symbol
        self.exchange = exchange
        self.direction = direction
        self.level = main.IMPULSE_START_THRESHOLD if level is None else level
        self.change_pct = -30.0 if direction == "down" else 30.0
        self.window_start_price = window_start_price
        self.current_price = current_price
        self.is_new_peak = False


@pytest.fixture(autouse=True)
def restore_started_at():
    saved = main._started_at_monotonic
    yield
    main._started_at_monotonic = saved


async def _tick_with_dump_signal():
    with patch.object(main.tracker, "update", return_value=None), \
         patch.object(main.dump_tracker, "update", return_value=_FakeSignal(direction="down")), \
         patch("main.live_trading.handle_price_tick", return_value=None), \
         patch("main.asyncio.create_task") as mock_create_task:
        mock_create_task.side_effect = lambda coro: coro.close()
        await main.on_kline_close("BTCUSDT", "Binance", 70.0, 1000)
    return mock_create_task


@pytest.mark.asyncio
async def test_dump_signal_right_after_restart_is_not_traded():
    """
    20.09.2026: после каждого деплоя детектор дампов забывал, что уже сигналил
    по монетам, идущим в дампе давно, и за секунды выдавал пачку "новых"
    сигналов по старым падениям (8-13 сетапов, риск 4% каждый).
    """
    main._started_at_monotonic = time.monotonic()  # только что запустились

    mock_create_task = await _tick_with_dump_signal()

    mock_create_task.assert_not_called()


@pytest.mark.asyncio
async def test_dump_signal_after_grace_period_is_traded():
    main._started_at_monotonic = time.monotonic() - main.STARTUP_GRACE_SECONDS - 1

    mock_create_task = await _tick_with_dump_signal()

    mock_create_task.assert_called_once()


@pytest.mark.asyncio
async def test_pump_autotrading_signal_right_after_restart_is_not_traded():
    main._started_at_monotonic = time.monotonic()
    with patch.object(main.tracker, "update", return_value=_FakeSignal(direction="up")), \
         patch.object(main.dump_tracker, "update", return_value=None), \
         patch("main.live_trading.handle_price_tick", return_value=None), \
         patch("main.upsert_alert_state"), \
         patch("main.get_all_subscribers", return_value=[]), \
         patch("main.asyncio.create_task") as mock_create_task:
        mock_create_task.side_effect = lambda coro: coro.close()
        await main.on_kline_close("BTCUSDT", "Binance", 100.0, 1000)

    mock_create_task.assert_not_called()


def test_main_marks_startup_time_before_starting_collectors():
    source = inspect.getsource(main.main)
    assert "_started_at_monotonic = time.monotonic()" in source
    assert source.index("_started_at_monotonic = time.monotonic()") < source.index("asyncio.gather(")
