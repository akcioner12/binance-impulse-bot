import pytest
from unittest.mock import patch

import order_executor
import live_trading


def setup_function():
    live_trading._pending_setups.clear()
    live_trading._open_positions.clear()
    live_trading._notification_queue.clear()


def _make_open_position():
    state = order_executor.OpenPositionState(
        position_id=1, direction="long", avg_entry_price=100.0, quantity=4.0,
        stop_loss=97.0,
        take_profits=[{"level": 110.0, "size_pct": 25}, {"level": 120.0, "size_pct": 25}, {"level": 130.0, "size_pct": 25}],
        breakeven_after_tp=2,
    )
    live_trading._open_positions["BTCUSDT"] = {"chat_id": 111, "state": state, "atr_1h": 2.0}
    return state


def test_tick_tp1_hit_adjusts_paper_balance():
    _make_open_position()
    with patch("live_trading.trading_storage.adjust_paper_balance") as mock_adjust, \
         patch("live_trading.trading_storage.update_position_progress"):
        events = live_trading.handle_price_tick("BTCUSDT", price=110.0)

    assert events == ["tp1_hit"]
    mock_adjust.assert_called_once_with(111, 10.0)  # 1.0 * (110-100)
    assert "BTCUSDT" in live_trading._open_positions  # позиция ещё открыта

    notes = live_trading.pop_notifications()
    assert len(notes) == 1
    assert notes[0]["chat_id"] == 111
    assert "TP1" in notes[0]["text"]
    assert "BTCUSDT" in notes[0]["text"]


def test_tick_stop_loss_hit_closes_position_and_removes_from_state():
    _make_open_position()
    with patch("live_trading.trading_storage.adjust_paper_balance") as mock_adjust, \
         patch("live_trading.trading_storage.close_position") as mock_close:
        events = live_trading.handle_price_tick("BTCUSDT", price=96.0)

    assert events == ["closed_stop_loss"]
    mock_adjust.assert_called_once_with(111, -16.0)  # 4.0 * (96-100)
    mock_close.assert_called_once_with(1, realized_pnl=-16.0)
    assert "BTCUSDT" not in live_trading._open_positions

    notes = live_trading.pop_notifications()
    assert len(notes) == 1
    assert notes[0]["chat_id"] == 111
    assert "Стоп" in notes[0]["text"]
    assert "-16.00" in notes[0]["text"]


def test_tick_moved_to_breakeven_updates_db_stop_loss():
    state = _make_open_position()
    state.take_profits[0]["filled"] = True  # TP1 уже сработал ранее
    state.tp_hit_count = 1
    state.remaining_quantity = 3.0

    with patch("live_trading.trading_storage.adjust_paper_balance"), \
         patch("live_trading.trading_storage.update_position_stop_loss") as mock_update_sl, \
         patch("live_trading.trading_storage.update_position_progress"):
        events = live_trading.handle_price_tick("BTCUSDT", price=120.0)  # TP2 -> безубыток+

    assert "tp2_hit" in events
    assert "moved_to_breakeven" in events
    mock_update_sl.assert_called_once()
    assert mock_update_sl.call_args[0][0] == 1  # position_id

    notes = live_trading.pop_notifications()
    assert len(notes) == 2  # tp2_hit + moved_to_breakeven
    texts = [n["text"] for n in notes]
    assert any("TP2" in t for t in texts)
    assert any("безубыток" in t for t in texts)


def test_tick_returns_none_when_no_stop_or_tp_event():
    _make_open_position()
    events = live_trading.handle_price_tick("BTCUSDT", price=105.0)  # между входом и TP1
    assert events is None
    assert live_trading.pop_notifications() == []


def test_tick_tp3_hit_activates_chandelier_and_notifies():
    state = _make_open_position()
    state.take_profits[0]["filled"] = True
    state.take_profits[1]["filled"] = True
    state.tp_hit_count = 2
    state.remaining_quantity = 2.0

    with patch("live_trading.trading_storage.adjust_paper_balance"), \
         patch("live_trading.trading_storage.update_position_progress"):
        events = live_trading.handle_price_tick("BTCUSDT", price=130.0)  # TP3

    assert "tp3_hit" in events
    assert "chandelier_activated" in events
    assert state.chandelier is not None

    notes = live_trading.pop_notifications()
    texts = [n["text"] for n in notes]
    assert any("TP3" in t for t in texts)
    assert any("трейлинг" in t.lower() for t in texts)


def test_tick_closed_chandelier_notifies_full_close():
    state = _make_open_position()
    state.take_profits[0]["filled"] = True
    state.take_profits[1]["filled"] = True
    state.take_profits[2]["filled"] = True
    state.tp_hit_count = 3
    state.remaining_quantity = 1.0
    state.chandelier = order_executor.ChandelierTrailingStop(direction="long", atr_multiplier=2.5)

    with patch("live_trading.trading_storage.adjust_paper_balance"), \
         patch("live_trading.trading_storage.close_position"), \
         patch("live_trading.trading_storage.update_position_progress"):
        live_trading.handle_price_tick("BTCUSDT", price=135.0)  # активирует трейлинг extreme=135, stop=130
        live_trading._notification_queue.clear()  # интересует только уведомление о закрытии
        events = live_trading.handle_price_tick("BTCUSDT", price=129.0)  # откат ниже -> закрытие

    assert events == ["closed_chandelier"]
    notes = live_trading.pop_notifications()
    assert len(notes) == 1
    assert "трейлинг" in notes[0]["text"].lower() or "TP4" in notes[0]["text"]
