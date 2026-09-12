import pytest

import position_manager


def test_calculate_stop_loss_atr_based_long():
    sl = position_manager.calculate_stop_loss(
        avg_entry_price=100.0, direction="long", sl_method="atr", atr_1h=2.0, atr_multiplier=1.5
    )
    assert sl == pytest.approx(97.0)  # 100 - 1.5*2.0


def test_calculate_stop_loss_atr_based_short():
    sl = position_manager.calculate_stop_loss(
        avg_entry_price=100.0, direction="short", sl_method="atr", atr_1h=2.0, atr_multiplier=1.5
    )
    assert sl == pytest.approx(103.0)  # 100 + 1.5*2.0


def test_calculate_stop_loss_fixed_percent_long():
    sl = position_manager.calculate_stop_loss(
        avg_entry_price=100.0, direction="long", sl_method="fixed_percent", fixed_percent=4.0
    )
    assert sl == pytest.approx(96.0)  # 100 - 4%


def test_calculate_stop_loss_fixed_percent_short():
    sl = position_manager.calculate_stop_loss(
        avg_entry_price=100.0, direction="short", sl_method="fixed_percent", fixed_percent=4.0
    )
    assert sl == pytest.approx(104.0)  # 100 + 4%


def test_calculate_stop_loss_default_atr_multiplier_is_1_5():
    sl = position_manager.calculate_stop_loss(
        avg_entry_price=100.0, direction="long", sl_method="atr", atr_1h=4.0
    )
    assert sl == pytest.approx(94.0)  # 100 - 1.5*4.0
