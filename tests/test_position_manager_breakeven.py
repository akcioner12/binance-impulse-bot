import pytest

import position_manager


def test_calculate_breakeven_plus_long_is_above_entry():
    price = position_manager.calculate_breakeven_plus_price(
        avg_entry_price=100.0, direction="long", commission_pct=0.08
    )
    assert price == pytest.approx(100.08)


def test_calculate_breakeven_plus_short_is_below_entry():
    price = position_manager.calculate_breakeven_plus_price(
        avg_entry_price=100.0, direction="short", commission_pct=0.08
    )
    assert price == pytest.approx(99.92)


def test_calculate_breakeven_plus_scales_with_entry_price():
    price = position_manager.calculate_breakeven_plus_price(
        avg_entry_price=50000.0, direction="long", commission_pct=0.08
    )
    assert price == pytest.approx(50040.0)  # 50000 * 1.0008


def test_calculate_breakeven_plus_default_commission():
    price = position_manager.calculate_breakeven_plus_price(avg_entry_price=100.0, direction="long")
    assert price > 100.0  # дефолт покрывает хоть какую-то комиссию, не просто безубыток
