from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import order_executor
import live_trading


def setup_function():
    live_trading._pending_setups.clear()
    live_trading._open_positions.clear()
    live_trading._notification_queue.clear()


def _make_short_position(opened_hours_ago: float, tp_hit_count: int = 0):
    """
    direction="short" -- фейд пампа. Бэктест 16.09.2026 (257 сделок, 2,5 мес.):
    пампы, застрявшие на 24ч (взяли максимум 1 тейк, не закрылись), в среднем
    ЕДУТ ДАЛЬШЕ против нас -- принудительный выход на 24ч дал бы +$2894 за
    период вместо естественного досиживания. Для дампов (direction="long")
    эффект обратный (досиживание выгоднее), поэтому правило -- ТОЛЬКО пампы.
    """
    state = order_executor.OpenPositionState(
        position_id=1, direction="short", avg_entry_price=100.0, quantity=4.0,
        stop_loss=110.0,
        take_profits=[{"level": 90.0, "size_pct": 25, "filled": tp_hit_count >= 1},
                      {"level": 80.0, "size_pct": 25}, {"level": 70.0, "size_pct": 25}],
        breakeven_after_tp=2,
    )
    state.tp_hit_count = tp_hit_count
    if tp_hit_count >= 1:
        state.remaining_quantity = 3.0
    opened_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=opened_hours_ago)
    live_trading._open_positions["BTCUSDT"] = {
        "chat_id": 111, "state": state, "atr_1h": 2.0, "opened_at": opened_at,
    }
    return state


def test_pump_force_closed_after_24h_with_zero_tp():
    _make_short_position(opened_hours_ago=25)
    with patch("live_trading.trading_storage.adjust_paper_balance") as mock_adjust, \
         patch("live_trading.trading_storage.close_position") as mock_close:
        events = live_trading.handle_price_tick("BTCUSDT", price=95.0)  # цена между входом и SL, между входом и TP1

    assert events == ["closed_timeout_24h"]
    assert "BTCUSDT" not in live_trading._open_positions
    mock_adjust.assert_called_once()
    mock_close.assert_called_once()

    notes = live_trading.pop_notifications()
    assert len(notes) == 1
    assert "24" in notes[0]["text"]


def test_pump_force_closed_after_24h_with_one_tp():
    _make_short_position(opened_hours_ago=30, tp_hit_count=1)
    with patch("live_trading.trading_storage.adjust_paper_balance"), \
         patch("live_trading.trading_storage.close_position"):
        events = live_trading.handle_price_tick("BTCUSDT", price=95.0)

    assert events == ["closed_timeout_24h"]


def test_pump_not_closed_before_24h():
    _make_short_position(opened_hours_ago=23)
    events = live_trading.handle_price_tick("BTCUSDT", price=95.0)

    assert events is None
    assert "BTCUSDT" in live_trading._open_positions


def test_pump_not_closed_by_timeout_if_two_tps_already_taken():
    """Реальный прогресс (2+ тейка) -- правило "застрял" больше не применимо."""
    state = _make_short_position(opened_hours_ago=30, tp_hit_count=2)
    state.stop_loss = 100.08  # уже перенесён в безубыток+
    events = live_trading.handle_price_tick("BTCUSDT", price=95.0)

    assert events is None
    assert "BTCUSDT" in live_trading._open_positions


def test_dump_never_force_closed_by_pump_timeout_rule():
    """Правило только для пампов (short) -- на дампах (long) досиживание выгоднее."""
    state = order_executor.OpenPositionState(
        position_id=1, direction="long", avg_entry_price=100.0, quantity=4.0,
        stop_loss=90.0,
        take_profits=[{"level": 110.0, "size_pct": 25}, {"level": 120.0, "size_pct": 25}, {"level": 130.0, "size_pct": 25}],
        breakeven_after_tp=2,
    )
    opened_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=48)
    live_trading._open_positions["BTCUSDT"] = {
        "chat_id": 111, "state": state, "atr_1h": 2.0, "opened_at": opened_at,
    }
    events = live_trading.handle_price_tick("BTCUSDT", price=105.0)

    assert events is None
    assert "BTCUSDT" in live_trading._open_positions


def test_position_without_opened_at_not_affected_by_timeout_rule():
    """Обратная совместимость: позиции без opened_at (старые/тестовые) не трогаем."""
    state = order_executor.OpenPositionState(
        position_id=1, direction="short", avg_entry_price=100.0, quantity=4.0,
        stop_loss=110.0,
        take_profits=[{"level": 90.0, "size_pct": 25}, {"level": 80.0, "size_pct": 25}, {"level": 70.0, "size_pct": 25}],
        breakeven_after_tp=2,
    )
    live_trading._open_positions["BTCUSDT"] = {"chat_id": 111, "state": state, "atr_1h": 2.0}
    events = live_trading.handle_price_tick("BTCUSDT", price=95.0)

    assert events is None
    assert "BTCUSDT" in live_trading._open_positions
