import pytest

import position_manager


def test_determine_trade_direction_reversal_of_up_impulse_is_short():
    # Фейдим памп ('up') -> шортим
    assert position_manager.determine_trade_direction("up", "reversal") == "short"


def test_determine_trade_direction_reversal_of_down_impulse_is_long():
    # Фейдим дамп ('down') -> лонгуем
    assert position_manager.determine_trade_direction("down", "reversal") == "long"


def test_determine_trade_direction_continuation_of_up_impulse_is_long():
    # Едем по тренду вверх -> лонгуем
    assert position_manager.determine_trade_direction("up", "continuation") == "long"


def test_determine_trade_direction_continuation_of_down_impulse_is_short():
    assert position_manager.determine_trade_direction("down", "continuation") == "short"


def test_calculate_average_entry_price_single_fill():
    avg = position_manager.calculate_average_entry_price([(100.0, 50.0)])
    assert avg == pytest.approx(100.0)


def test_calculate_average_entry_price_weighted_by_size():
    # Часть 1: 100 по цене 100.0, Часть 2: 100 по цене 90.0 -> средняя 95.0
    avg = position_manager.calculate_average_entry_price([(100.0, 100.0), (90.0, 100.0)])
    assert avg == pytest.approx(95.0)


def test_calculate_average_entry_price_unequal_sizes():
    # 75 по 100.0, 25 по 80.0 -> (75*100 + 25*80) / 100 = 95.0
    avg = position_manager.calculate_average_entry_price([(100.0, 75.0), (80.0, 25.0)])
    assert avg == pytest.approx(95.0)


def test_calculate_average_entry_price_empty_fills_returns_zero():
    assert position_manager.calculate_average_entry_price([]) == 0.0
