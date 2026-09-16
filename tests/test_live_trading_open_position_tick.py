import logging

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


def test_tick_stop_loss_hit_logs_event(caplog):
    """
    Юзер попросил (15.09.2026) проверить, нормальна ли серия подряд идущих
    стопов в live paper-trading -- выяснилось, что закрытия/тейки нигде не
    логируются (только уведомление в Telegram), поэтому я не мог сам
    посмотреть историю через Railway logs. Добавляем logger.info на каждое
    событие, чтобы впредь можно было сверять живую историю сделок самому.
    """
    _make_open_position()
    with caplog.at_level(logging.INFO, logger="live_trading"), \
         patch("live_trading.trading_storage.adjust_paper_balance"), \
         patch("live_trading.trading_storage.close_position"):
        live_trading.handle_price_tick("BTCUSDT", price=96.0)

    assert any("BTCUSDT" in r.message and "closed_stop_loss" in r.message and "-16.00" in r.message for r in caplog.records)


def test_tick_tp_hit_logs_event(caplog):
    _make_open_position()
    with caplog.at_level(logging.INFO, logger="live_trading"), \
         patch("live_trading.trading_storage.adjust_paper_balance"), \
         patch("live_trading.trading_storage.update_position_progress"):
        live_trading.handle_price_tick("BTCUSDT", price=110.0)

    assert any("BTCUSDT" in r.message and "tp1_hit" in r.message for r in caplog.records)


def test_tick_stop_loss_with_zero_tp_invalidates_pending_setup():
    """
    Прод-находка 14-16.09.2026 (реальный live paper-trading): если позиция
    от части 1 стопится с НУЛЁМ взятых TP до того, как сработает часть 2,
    это означает, что тезис на разворот уже опровергнут рынком. Раньше часть 2
    всё равно открывала вторую НЕЗАВИСИМУЮ позицию вслепую (см. AKEUSDT/
    PUFFERUSDT/CVCUSDT 15-16.09 -- треть сигналов в сутки дали двойной стоп
    от одного и того же исходного сигнала). Бэктест на 2,5 мес. подтвердил:
    отмена части 2 в этом случае даёт +$1713 (+4.9%) за период. Часть 2
    по-прежнему ждёт своего триггера (setup остаётся в _pending_setups), но
    помечается invalidated -- при срабатывании она не откроет новую позицию.
    """
    _make_open_position()  # tp_hit_count=0 по умолчанию
    live_trading._pending_setups["BTCUSDT"] = {"dummy_setup": True}

    with patch("live_trading.trading_storage.adjust_paper_balance"), \
         patch("live_trading.trading_storage.close_position"):
        live_trading._process_open_position_tick("BTCUSDT", price=96.0)  # стоп, 0 TP взято

    assert live_trading._pending_setups["BTCUSDT"]["invalidated"] is True


def test_tick_stop_loss_after_partial_tp_does_not_invalidate_pending_setup():
    """
    Регрессия: если стоп срабатывает уже ПОСЛЕ того, как хотя бы один TP взят
    (например, стоп на безубытке+ после TP1), тезис на разворот был верным --
    здесь НЕ нужно отменять часть 2, старое поведение (независимая вторая
    нога) сохраняется как задумано.
    """
    state = _make_open_position()
    state.take_profits[0]["filled"] = True
    state.tp_hit_count = 1
    live_trading._pending_setups["BTCUSDT"] = {"dummy_setup": True}

    with patch("live_trading.trading_storage.adjust_paper_balance"), \
         patch("live_trading.trading_storage.close_position"):
        live_trading._process_open_position_tick("BTCUSDT", price=96.0)  # стоп после частичного TP

    assert "invalidated" not in live_trading._pending_setups["BTCUSDT"]


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
