import pytest
from unittest.mock import AsyncMock, patch

import trading_storage
import live_trading


def _candle(high, low):
    return {"open_time": 0, "open": high, "high": high, "low": low, "close": low, "volume": 1.0}


def test_fresh_peak_not_stale():
    """Пик -- самая последняя свеча (0 дней назад) -- не устарел."""
    candles = [_candle(100, 95) for _ in range(9)] + [_candle(150, 100)]
    assert live_trading._is_dump_anchor_stale(candles) is False


def test_old_peak_with_bounce_is_stale():
    """
    Бэктест 16-17.09.2026 (140 дамп-сделок, 2,5 мес.): устаревший якорь
    (пик 1.5+ дня назад + был отскок >=15% между пиком и текущим моментом) --
    avgR всего +0.471 против +1.168 у свежих. POWRUSDT (17.09) -- ровно
    такой случай: пик за 4.7 дня, отскок 26.4%.
    """
    candles = [
        _candle(150, 140),   # пик, 4 дня назад
        _candle(120, 100),   # резкое падение
        _candle(115, 105),   # отскок от 100 до 115 -> +15%
        _candle(110, 108),
        _candle(105, 100),   # текущая свеча, -30% от пика 150
    ]
    assert live_trading._is_dump_anchor_stale(candles) is True


def test_old_peak_without_bounce_not_stale():
    """Монотонное падение без заметного отскока -- всё ещё считается свежим движением."""
    candles = [
        _candle(150, 140),
        _candle(140, 130),
        _candle(130, 120),
        _candle(120, 110),
        _candle(110, 100),
    ]
    assert live_trading._is_dump_anchor_stale(candles) is False


def test_recent_peak_within_threshold_not_stale():
    """Пик 1 день назад (меньше порога 1.5 дня) -- не устарел, даже если был отскок."""
    candles = [
        _candle(100, 95),
        _candle(150, 100),   # пик, 1 день назад (последняя-1 свеча)
        _candle(140, 105),   # текущая, откат с отскоком
    ]
    assert live_trading._is_dump_anchor_stale(candles) is False


def test_too_few_candles_not_stale():
    assert live_trading._is_dump_anchor_stale([_candle(100, 90)]) is False


PROFILE = {
    "is_active": 1, "max_concurrent_trades": 3, "risk_percent": 1.0,
    "sl_method": "atr", "sl_fixed_percent": None, "tp_split_preset": "equal",
    "breakeven_after_tp": 2,
}


def _analysis_dump_reversal(stale_anchor):
    return {
        "classification": "reversal", "trend_4h": "down", "relevant_divergence": False,
        "is_climax": False, "funding_rate": 0.0, "oi_diverging": False,
        "near_significant_level": False, "vwap_deviation": 1.0, "atr_15m": 1.0, "atr_1h": 2.0,
        "magnet_levels": [], "stale_anchor": stale_anchor,
    }


def _make_signal(chat_id=111, symbol="LSKUSDT"):
    return trading_storage.create_trade_signal(
        chat_id=chat_id, symbol=symbol, exchange="Binance",
        impulse_direction="down", classification="reversal",
    )


def setup_function():
    trading_storage.init_trading_db()
    trading_storage.init_paper_trading_db()
    live_trading._pending_setups.clear()
    live_trading._open_positions.clear()


@pytest.mark.asyncio
async def test_execute_setup_halves_size_when_stale_anchor():
    signal_id = _make_signal()
    trading_storage.init_paper_balance(111, 10000.0)

    with patch("live_trading.trading_storage.create_position", return_value=99), \
         patch("live_trading.send_text", new=AsyncMock()):
        await live_trading.execute_setup(
            session=None, chat_id=111, symbol="LSKUSDT", exchange="Binance", direction="down",
            classification="reversal", current_price=100.0, window_start_price=150.0,
            profile=PROFILE, analysis=_analysis_dump_reversal(stale_anchor=True), signal_id=signal_id,
        )

    setup = live_trading._pending_setups["LSKUSDT"]
    # risk_amount = 10000*1% = 100; SL(long, atr=2.0*1.5=3.0) -> stop_distance=3 -> qty=100/3
    # без стейл-фильтра part_size = qty/2; со стейл-фильтром (0.5x) -- вдвое меньше
    assert setup["part_size"] == pytest.approx(100 / 3 * 0.5 / 2)


@pytest.mark.asyncio
async def test_execute_setup_full_size_when_anchor_fresh():
    signal_id = _make_signal()
    trading_storage.init_paper_balance(111, 10000.0)

    with patch("live_trading.trading_storage.create_position", return_value=99), \
         patch("live_trading.send_text", new=AsyncMock()):
        await live_trading.execute_setup(
            session=None, chat_id=111, symbol="LSKUSDT", exchange="Binance", direction="down",
            classification="reversal", current_price=100.0, window_start_price=150.0,
            profile=PROFILE, analysis=_analysis_dump_reversal(stale_anchor=False), signal_id=signal_id,
        )

    setup = live_trading._pending_setups["LSKUSDT"]
    assert setup["part_size"] == pytest.approx(100 / 3 / 2)
