import pytest

import position_manager


def test_calculate_take_profits_long_uses_r_multiples():
    # Вход 100, SL 90 -> R = 10. TP1=110(1R), TP2=120(2R), TP3=130(3R)
    tps = position_manager.calculate_take_profits(
        avg_entry_price=100.0, stop_loss=90.0, direction="long", tp_split_preset="equal"
    )
    assert [tp["level"] for tp in tps] == pytest.approx([110.0, 120.0, 130.0])


def test_calculate_take_profits_short_uses_r_multiples():
    # Вход 100, SL 110 -> R = 10. TP1=90(1R), TP2=80(2R), TP3=70(3R)
    tps = position_manager.calculate_take_profits(
        avg_entry_price=100.0, stop_loss=110.0, direction="short", tp_split_preset="equal"
    )
    assert [tp["level"] for tp in tps] == pytest.approx([90.0, 80.0, 70.0])


def test_calculate_take_profits_equal_preset_sizes():
    tps = position_manager.calculate_take_profits(
        avg_entry_price=100.0, stop_loss=90.0, direction="long", tp_split_preset="equal"
    )
    assert [tp["size_pct"] for tp in tps] == [25, 25, 25]


def test_calculate_take_profits_conservative_preset_sizes():
    tps = position_manager.calculate_take_profits(
        avg_entry_price=100.0, stop_loss=90.0, direction="long", tp_split_preset="conservative"
    )
    assert [tp["size_pct"] for tp in tps] == [40, 30, 20]


def test_calculate_take_profits_aggressive_preset_sizes():
    tps = position_manager.calculate_take_profits(
        avg_entry_price=100.0, stop_loss=90.0, direction="long", tp_split_preset="aggressive"
    )
    assert [tp["size_pct"] for tp in tps] == [15, 20, 25]


def test_calculate_take_profits_custom_r_multiples():
    tps = position_manager.calculate_take_profits(
        avg_entry_price=100.0, stop_loss=90.0, direction="long",
        tp_split_preset="equal", r_multiples=(0.5, 1.5, 2.5),
    )
    assert [tp["level"] for tp in tps] == pytest.approx([105.0, 115.0, 125.0])
