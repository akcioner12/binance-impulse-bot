from datetime import datetime

import trading_storage
import position_manager
import live_trading


def setup_function():
    trading_storage.init_trading_db()
    trading_storage.init_paper_trading_db()
    live_trading._pending_setups.clear()
    live_trading._open_positions.clear()


def test_restore_open_positions_reconstructs_fresh_position():
    position_id = trading_storage.create_position(
        chat_id=111, symbol="BTCUSDT", exchange="Binance", direction="short",
        mode="paper", avg_entry_price=100.0, quantity=10.0, stop_loss=103.0,
        original_stop_loss=103.0, tp_split_preset="equal", breakeven_after_tp=2, atr_1h=2.0,
    )

    restored = live_trading.restore_open_positions()

    assert restored == 1
    assert "BTCUSDT" in live_trading._open_positions
    entry = live_trading._open_positions["BTCUSDT"]
    assert entry["chat_id"] == 111
    assert entry["atr_1h"] == 2.0
    state = entry["state"]
    assert state.position_id == position_id
    assert state.direction == "short"
    assert state.avg_entry_price == 100.0
    assert state.remaining_quantity == 10.0
    assert state.tp_hit_count == 0
    assert state.chandelier is None
    assert [tp["filled"] for tp in state.take_profits] == [False, False, False]


def test_restore_open_positions_reconstructs_partial_progress():
    trading_storage.create_position(
        chat_id=111, symbol="ETHUSDT", exchange="Binance", direction="short",
        mode="paper", avg_entry_price=100.0, quantity=10.0, stop_loss=99.0,  # уже в безубытке+
        original_stop_loss=103.0, tp_split_preset="equal", breakeven_after_tp=2, atr_1h=2.0,
    )
    position_id = trading_storage.get_all_open_positions()[0]["id"]
    trading_storage.update_position_progress(
        position_id, tp1_filled=True, tp2_filled=True, tp3_filled=False,
        remaining_quantity=5.0, chandelier_active=False,
        chandelier_extreme_price=None, chandelier_stop_price=None,
    )

    live_trading.restore_open_positions()

    state = live_trading._open_positions["ETHUSDT"]["state"]
    assert state.remaining_quantity == 5.0
    assert state.tp_hit_count == 2
    assert [tp["filled"] for tp in state.take_profits] == [True, True, False]
    assert state.stop_loss == 99.0  # уже перенесённый в безубыток+ стоп, не пересчитан заново


def test_restore_open_positions_reconstructs_active_chandelier():
    trading_storage.create_position(
        chat_id=111, symbol="LSKUSDT", exchange="Binance", direction="short",
        mode="paper", avg_entry_price=100.0, quantity=10.0, stop_loss=99.0,
        original_stop_loss=103.0, tp_split_preset="equal", breakeven_after_tp=2, atr_1h=2.0,
    )
    position_id = trading_storage.get_all_open_positions()[0]["id"]
    trading_storage.update_position_progress(
        position_id, tp1_filled=True, tp2_filled=True, tp3_filled=True,
        remaining_quantity=2.5, chandelier_active=True,
        chandelier_extreme_price=70.0, chandelier_stop_price=95.0,
    )

    live_trading.restore_open_positions()

    state = live_trading._open_positions["LSKUSDT"]["state"]
    assert state.chandelier is not None
    assert state.chandelier.direction == "short"
    assert state.chandelier.extreme_price == 70.0
    assert state.chandelier.stop_price == 95.0
    assert state.tp_hit_count == 3


def test_restore_open_positions_parses_opened_at():
    """
    Нужно для правила PUMP_STUCK_TIMEOUT_HOURS (16.09.2026) -- без времени
    входа "зависший памп" не может быть найден после рестарта бота.
    """
    trading_storage.create_position(
        chat_id=111, symbol="BTCUSDT", exchange="Binance", direction="short",
        mode="paper", avg_entry_price=100.0, quantity=10.0, stop_loss=103.0,
    )

    live_trading.restore_open_positions()

    opened_at = live_trading._open_positions["BTCUSDT"]["opened_at"]
    assert isinstance(opened_at, datetime)


def test_restore_open_positions_skips_closed_positions():
    position_id = trading_storage.create_position(
        chat_id=111, symbol="BTCUSDT", exchange="Binance", direction="short",
        mode="paper", avg_entry_price=100.0, quantity=10.0, stop_loss=103.0,
    )
    trading_storage.close_position(position_id, realized_pnl=10.0)

    restored = live_trading.restore_open_positions()

    assert restored == 0
    assert "BTCUSDT" not in live_trading._open_positions


def test_persist_position_progress_writes_current_state():
    position_id = trading_storage.create_position(
        chat_id=111, symbol="BTCUSDT", exchange="Binance", direction="long",
        mode="paper", avg_entry_price=100.0, quantity=4.0, stop_loss=97.0,
        original_stop_loss=97.0, tp_split_preset="equal", breakeven_after_tp=2, atr_1h=2.0,
    )
    state = live_trading.order_executor.OpenPositionState(
        position_id=position_id, direction="long", avg_entry_price=100.0, quantity=4.0,
        stop_loss=97.0,
        take_profits=[{"level": 110.0, "size_pct": 50}, {"level": 120.0, "size_pct": 50}],
        breakeven_after_tp=2,
    )
    state.take_profits[0]["filled"] = True
    state.remaining_quantity = 2.0
    state.chandelier = position_manager.ChandelierTrailingStop(direction="long")
    state.chandelier.extreme_price = 130.0
    state.chandelier.stop_price = 125.0

    live_trading._persist_position_progress(state)

    position = trading_storage.get_position(position_id)
    assert position["tp1_filled"] == 1
    assert position["tp2_filled"] == 0
    assert position["remaining_quantity"] == 2.0
    assert position["chandelier_active"] == 1
    assert position["chandelier_extreme_price"] == 130.0
    assert position["chandelier_stop_price"] == 125.0


def test_handle_price_tick_persists_progress_on_tp_hit():
    """
    Сквозная проверка: реальный тик, дошедший до TP1 через handle_price_tick,
    должен сразу же отразиться в БД -- не только в памяти -- иначе восстановление
    после рестарта откатится к состоянию до этого TP.
    """
    trading_storage.init_paper_balance(111, 1000.0)
    position_id = trading_storage.create_position(
        chat_id=111, symbol="BTCUSDT", exchange="Binance", direction="long",
        mode="paper", avg_entry_price=100.0, quantity=4.0, stop_loss=97.0,
        original_stop_loss=97.0, tp_split_preset="equal", breakeven_after_tp=2, atr_1h=2.0,
    )
    state = live_trading.order_executor.OpenPositionState(
        position_id=position_id, direction="long", avg_entry_price=100.0, quantity=4.0,
        stop_loss=97.0,
        take_profits=[{"level": 110.0, "size_pct": 50}, {"level": 120.0, "size_pct": 50}],
        breakeven_after_tp=2,
    )
    live_trading._open_positions["BTCUSDT"] = {"chat_id": 111, "state": state, "atr_1h": 2.0}

    live_trading.handle_price_tick("BTCUSDT", price=111.0)  # пробивает TP1 (110.0)

    position = trading_storage.get_position(position_id)
    assert position["tp1_filled"] == 1
    assert position["remaining_quantity"] == 2.0
