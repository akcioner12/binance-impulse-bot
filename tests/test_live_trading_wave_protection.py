import pytest
from unittest.mock import AsyncMock, patch

import trading_storage
import live_trading


def setup_function():
    trading_storage.init_trading_db()
    trading_storage.init_paper_trading_db()
    live_trading._pending_setups.clear()
    live_trading._open_positions.clear()


PROFILE = {
    "is_active": 1, "max_concurrent_trades": 3, "risk_percent": 1.0,
    "sl_method": "atr", "sl_fixed_percent": None, "tp_split_preset": "equal",
    "breakeven_after_tp": 2,
}

ANALYSIS_CONTINUATION = {
    "classification": "continuation", "trend_4h": "up", "relevant_divergence": False,
    "is_climax": False, "funding_rate": 0.0001, "oi_diverging": False,
    "near_significant_level": False, "vwap_deviation": 1.0, "atr_15m": 1.0, "atr_1h": 2.0,
}


def _make_signal(chat_id=111, symbol="LSKUSDT"):
    return trading_storage.create_trade_signal(
        chat_id=chat_id, symbol=symbol, exchange="Binance",
        impulse_direction="up", classification="reversal",
    )


def test_first_wave_gets_full_multiplier():
    signal_id = _make_signal()
    multiplier = live_trading._compute_wave_size_multiplier(111, "LSKUSDT", signal_id)
    assert multiplier == 1.0


def test_second_wave_within_window_gets_half_multiplier():
    _make_signal()  # волна 1
    signal_id_2 = _make_signal()  # волна 2, тот же символ
    multiplier = live_trading._compute_wave_size_multiplier(111, "LSKUSDT", signal_id_2)
    assert multiplier == 0.5


def test_third_wave_within_window_returns_none():
    _make_signal()  # волна 1
    _make_signal()  # волна 2
    signal_id_3 = _make_signal()  # волна 3
    multiplier = live_trading._compute_wave_size_multiplier(111, "LSKUSDT", signal_id_3)
    assert multiplier is None


def test_different_symbol_does_not_count_as_wave():
    _make_signal(symbol="LSKUSDT")
    signal_id = _make_signal(symbol="ETHUSDT")
    multiplier = live_trading._compute_wave_size_multiplier(111, "ETHUSDT", signal_id)
    assert multiplier == 1.0


def test_different_chat_does_not_count_as_wave():
    _make_signal(chat_id=999, symbol="LSKUSDT")
    signal_id = _make_signal(chat_id=111, symbol="LSKUSDT")
    multiplier = live_trading._compute_wave_size_multiplier(111, "LSKUSDT", signal_id)
    assert multiplier == 1.0


@pytest.mark.asyncio
async def test_execute_setup_skips_third_wave_without_opening_anything():
    _make_signal()  # волна 1
    _make_signal()  # волна 2
    signal_id_3 = _make_signal()  # волна 3

    with patch("live_trading.trading_storage.create_position") as mock_create_position:
        result = await live_trading.execute_setup(
            session=None, chat_id=111, symbol="LSKUSDT", exchange="Binance", direction="up",
            classification="continuation", current_price=100.0, window_start_price=70.0,
            profile=PROFILE, analysis=ANALYSIS_CONTINUATION, signal_id=signal_id_3,
        )

    assert result["skipped"] == "multiwave_protection"
    assert "LSKUSDT" not in live_trading._open_positions
    assert "LSKUSDT" not in live_trading._pending_setups
    mock_create_position.assert_not_called()
    assert trading_storage.get_trade_signal(signal_id_3)["status"] == "expired"


@pytest.mark.asyncio
async def test_execute_setup_halves_size_on_second_wave():
    _make_signal()  # волна 1
    signal_id_2 = _make_signal()  # волна 2

    trading_storage.init_paper_balance(111, 10000.0)
    with patch("live_trading.trading_storage.create_position", return_value=99), \
         patch("live_trading.send_text", new=AsyncMock()):
        result = await live_trading.execute_setup(
            session=None, chat_id=111, symbol="LSKUSDT", exchange="Binance", direction="up",
            classification="continuation", current_price=100.0, window_start_price=70.0,
            profile=PROFILE, analysis=ANALYSIS_CONTINUATION, signal_id=signal_id_2,
        )

    assert result["classification"] == "continuation"
    state = live_trading._open_positions["LSKUSDT"]["state"]
    # direction="up" -> PUMP_RISK_PERCENT=2% (не profile["risk_percent"], см. 17.09.2026
    # асимметричный риск памп/дамп): risk_amount = 10000*2% = 200; SL = 100 - 1.5*2.0 = 97
    # -> stop_distance = 3 -> без волновой защиты qty = 200/3 = 66.67; на второй волне
    # множитель 0.5 -> 33.33
    assert state.quantity == pytest.approx(200 / 3 * 0.5)
