from unittest.mock import patch

import entry_engine
import live_trading


PROFILE = {
    "is_active": 1, "max_concurrent_trades": 3, "risk_percent": 1.0,
    "sl_method": "atr", "sl_fixed_percent": None, "tp_split_preset": "equal",
    "breakeven_after_tp": 2,
}


def setup_function():
    live_trading._pending_setups.clear()
    live_trading._open_positions.clear()


def test_tp_r_multiples_for_pump_direction():
    assert live_trading._tp_r_multiples_for_direction("up") == live_trading.PUMP_TP_R_MULTIPLES


def test_tp_r_multiples_for_dump_direction():
    assert live_trading._tp_r_multiples_for_direction("down") == live_trading.DUMP_TP_R_MULTIPLES


def _make_pending_setup(direction):
    return {
        "chat_id": 111, "exchange": "Binance", "signal_id": 55,
        "impulse_direction": direction, "window_start_price": 70.0,
        "cap_reference_price": None, "last_atr_refresh_price": None,
        "trigger_part1": entry_engine.create_part1_trigger(direction, atr_15m=1.0),
        "trigger_part2": entry_engine.create_part2_trigger(direction, atr_15m=1.0),
        "part_size": 2.0, "atr_1h": 2.0, "magnet_levels": [], "profile": PROFILE,
    }


def test_dump_part_fill_uses_widened_tp_r_multiples():
    """
    Бэктест 17.09.2026 (257 сделок, 2,5 мес.): раздвинутая сетка TP1-3
    (R=1.5/3/5 вместо 1/2/3) на дампах даёт +21% PnL по дампам ($36792 vs
    $30357 за период) при том же сплите долей (15/20/25%) -- дамп-эдж сильнее,
    есть смысл давать прибыли бежать дальше. На пампах наоборот текущая сетка
    (R=1/2/3) лучше -- поэтому направление-зависимо, как и с риском (16.09).
    """
    live_trading._pending_setups["BTCUSDT"] = _make_pending_setup("down")
    with patch("live_trading.trading_storage.create_position", return_value=1), \
         patch("live_trading.trading_storage.update_trade_signal_status"):
        live_trading.handle_price_tick("BTCUSDT", price=100.0)
        live_trading.handle_price_tick("BTCUSDT", price=100.8)  # часть 1 срабатывает (long, вход=100.8)

    state = live_trading._open_positions["BTCUSDT"]["state"]
    # entry=100.8, SL(long, atr=2.0*1.5=3.0) -> SL=97.8, R=3.0
    # DUMP_TP_R_MULTIPLES=(1.5,3.0,5.0) -> TP1=100.8+4.5=105.3, TP2=109.8, TP3=115.8
    assert [round(tp["level"], 2) for tp in state.take_profits] == [105.3, 109.8, 115.8]


def test_pump_part_fill_keeps_default_tp_r_multiples():
    live_trading._pending_setups["ETHUSDT"] = _make_pending_setup("up")
    with patch("live_trading.trading_storage.create_position", return_value=1), \
         patch("live_trading.trading_storage.update_trade_signal_status"):
        live_trading.handle_price_tick("ETHUSDT", price=100.0)
        live_trading.handle_price_tick("ETHUSDT", price=99.2)  # часть 1 срабатывает (short, вход=99.2)

    state = live_trading._open_positions["ETHUSDT"]["state"]
    # entry=99.2, SL(short, atr=2.0*1.5=3.0) -> SL=102.2, R=3.0
    # PUMP_TP_R_MULTIPLES=(1.0,2.0,3.0) -> TP1=96.2, TP2=93.2, TP3=90.2
    assert [round(tp["level"], 2) for tp in state.take_profits] == [96.2, 93.2, 90.2]
