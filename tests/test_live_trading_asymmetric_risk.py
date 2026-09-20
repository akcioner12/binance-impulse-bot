import pytest
from unittest.mock import AsyncMock, patch

import trading_storage
import live_trading


def setup_function():
    trading_storage.init_trading_db()
    trading_storage.init_paper_trading_db()
    live_trading._pending_setups.clear()
    live_trading._open_positions.clear()


def test_pump_risk_reduced_to_1_percent_while_dump_stays_4_percent():
    """20.09.2026: живые пампы -0.45R за 5 дней (n=41) -- вдвое меньше риск, пока не разберёмся; дампы в норме."""
    assert live_trading.PUMP_RISK_PERCENT == 1.0
    assert live_trading.DUMP_RISK_PERCENT == 4.0


def test_risk_percent_for_pump_direction():
    assert live_trading._risk_percent_for_direction("up") == live_trading.PUMP_RISK_PERCENT


def test_risk_percent_for_dump_direction():
    assert live_trading._risk_percent_for_direction("down") == live_trading.DUMP_RISK_PERCENT


PROFILE = {
    "is_active": 1, "max_concurrent_trades": 3, "risk_percent": 1.0,
    "sl_method": "atr", "sl_fixed_percent": None, "tp_split_preset": "equal",
    "breakeven_after_tp": 2,
}

ANALYSIS = {
    "classification": "reversal", "trend_4h": "down", "relevant_divergence": False,
    "is_climax": False, "funding_rate": 0.0, "oi_diverging": False,
    "near_significant_level": False, "vwap_deviation": 1.0, "atr_15m": 1.0, "atr_1h": 2.0,
    "magnet_levels": [],
}


def _make_signal(chat_id=111, symbol="BTCUSDT", direction="up"):
    return trading_storage.create_trade_signal(
        chat_id=chat_id, symbol=symbol, exchange="Binance",
        impulse_direction=direction, classification="reversal",
    )


@pytest.mark.asyncio
async def test_reversal_setup_uses_pump_risk_percent_not_profile():
    """
    Находка 17.09.2026 (257 сделок, 2,5 мес.): эдж у дампов стабильно сильнее
    (avgR ~0.7-0.9), чем у пампов (~0.1-0.5). Асимметричный риск 2%/4% вместо
    равномерных 3%/3% (при том же среднем риске на портфель) даёт +$8019
    (+22%) за период -- сайзинг теперь зависит от направления, НЕ от
    единого profile["risk_percent"].
    """
    signal_id = _make_signal(direction="up")
    trading_storage.init_paper_balance(111, 10000.0)

    with patch("live_trading.trading_storage.create_position", return_value=99), \
         patch("live_trading.send_text", new=AsyncMock()):
        await live_trading.execute_setup(
            session=None, chat_id=111, symbol="BTCUSDT", exchange="Binance", direction="up",
            classification="reversal", current_price=100.0, window_start_price=70.0,
            profile=PROFILE, analysis=ANALYSIS, signal_id=signal_id,
        )

    setup = live_trading._pending_setups["BTCUSDT"]
    # risk_amount = 10000 * PUMP_RISK_PERCENT(1%) = 100; SL(short, atr=2.0*1.5=3.0) -> stop_distance=3
    # part_size = (100/3) / 2 -- НЕ по profile["risk_percent"], а по константе пампов
    expected_part_size = (10000 * live_trading.PUMP_RISK_PERCENT / 100 / 3) / 2
    assert setup["part_size"] == pytest.approx(expected_part_size)


@pytest.mark.asyncio
async def test_reversal_setup_uses_dump_risk_percent_not_profile():
    signal_id = _make_signal(symbol="ETHUSDT", direction="down")
    trading_storage.init_paper_balance(111, 10000.0)

    with patch("live_trading.trading_storage.create_position", return_value=99), \
         patch("live_trading.send_text", new=AsyncMock()):
        await live_trading.execute_setup(
            session=None, chat_id=111, symbol="ETHUSDT", exchange="Binance", direction="down",
            classification="reversal", current_price=100.0, window_start_price=150.0,
            profile=PROFILE, analysis=ANALYSIS, signal_id=signal_id,
        )

    setup = live_trading._pending_setups["ETHUSDT"]
    expected_part_size = (10000 * live_trading.DUMP_RISK_PERCENT / 100 / 3) / 2
    assert setup["part_size"] == pytest.approx(expected_part_size)
