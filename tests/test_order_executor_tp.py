import pytest

import order_executor


def _long_state():
    return order_executor.OpenPositionState(
        position_id=1, direction="long", avg_entry_price=100.0, quantity=4.0,
        stop_loss=97.0,
        take_profits=[{"level": 110.0, "size_pct": 25}, {"level": 120.0, "size_pct": 25}, {"level": 130.0, "size_pct": 25}],
        breakeven_after_tp=2,
    )


def test_tp1_hit_partial_closes_25_percent_with_pnl():
    state = _long_state()
    events = order_executor.check_take_profit_hits(state, price=110.0)

    assert len(events) == 1
    assert events[0]["event"] == "tp1_hit"
    assert events[0]["size_closed"] == pytest.approx(1.0)  # 25% от 4.0
    assert events[0]["pnl_delta"] == pytest.approx(10.0)  # 1.0 * (110-100)
    assert events[0]["exit_price"] == 110.0
    assert state.remaining_quantity == pytest.approx(3.0)
    assert state.tp_hit_count == 1
    assert state.take_profits[0]["filled"] is True


def test_tp1_hit_does_not_refire_on_next_tick():
    state = _long_state()
    order_executor.check_take_profit_hits(state, price=110.0)
    events = order_executor.check_take_profit_hits(state, price=111.0)
    assert events == []  # TP1 уже filled, TP2/TP3 ещё не достигнуты


def test_tp2_hit_triggers_breakeven_move():
    state = _long_state()
    order_executor.check_take_profit_hits(state, price=110.0)  # TP1
    events = order_executor.check_take_profit_hits(state, price=120.0)  # TP2

    event_names = [e["event"] for e in events]
    assert "tp2_hit" in event_names
    assert "moved_to_breakeven" in event_names

    breakeven_event = next(e for e in events if e["event"] == "moved_to_breakeven")
    assert breakeven_event["new_stop_loss"] == pytest.approx(100.08)  # 100 * 1.0008
    assert state.stop_loss == pytest.approx(100.08)


def test_tp3_hit_activates_chandelier():
    state = _long_state()
    order_executor.check_take_profit_hits(state, price=110.0)
    order_executor.check_take_profit_hits(state, price=120.0)
    events = order_executor.check_take_profit_hits(state, price=130.0)

    event_names = [e["event"] for e in events]
    assert "tp3_hit" in event_names
    assert "chandelier_activated" in event_names
    assert state.chandelier is not None
    assert state.remaining_quantity == pytest.approx(1.0)  # 25% осталось на трейлинг


def test_check_take_profit_hits_skips_when_closed():
    state = _long_state()
    state.closed = True
    events = order_executor.check_take_profit_hits(state, price=110.0)
    assert events == []


def test_check_take_profit_hits_jumps_multiple_levels_in_one_tick():
    # Резкий скачок цены сразу выше TP1 и TP2 в одном тике (гэп)
    state = _long_state()
    events = order_executor.check_take_profit_hits(state, price=125.0)

    event_names = [e["event"] for e in events]
    assert "tp1_hit" in event_names
    assert "tp2_hit" in event_names
    assert "moved_to_breakeven" in event_names
    assert "tp3_hit" not in event_names  # 125 не дотягивает до TP3=130
    assert state.tp_hit_count == 2
