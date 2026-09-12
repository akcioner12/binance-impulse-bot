import pytest

import position_manager


def test_calculate_position_size_loss_equals_risk_amount():
    # Баланс 1000, риск 1% = 10 USDT. Вход 100, SL 97 -> дистанция 3.
    # quantity = 10 / 3 = 3.333..., убыток при срабатывании SL = quantity * 3 = 10 USDT = 1% баланса
    size = position_manager.calculate_position_size(
        balance=1000.0, risk_percent=1.0, entry_price=100.0, stop_loss=97.0
    )
    assert size == pytest.approx(10.0 / 3.0)
    loss_if_sl_hit = size * abs(100.0 - 97.0)
    assert loss_if_sl_hit == pytest.approx(10.0)  # ровно 1% от 1000


def test_calculate_position_size_scales_with_risk_percent():
    size_1pct = position_manager.calculate_position_size(
        balance=1000.0, risk_percent=1.0, entry_price=100.0, stop_loss=97.0
    )
    size_2pct = position_manager.calculate_position_size(
        balance=1000.0, risk_percent=2.0, entry_price=100.0, stop_loss=97.0
    )
    assert size_2pct == pytest.approx(size_1pct * 2)


def test_calculate_position_size_smaller_for_wider_stop():
    tight_stop = position_manager.calculate_position_size(
        balance=1000.0, risk_percent=1.0, entry_price=100.0, stop_loss=99.0
    )
    wide_stop = position_manager.calculate_position_size(
        balance=1000.0, risk_percent=1.0, entry_price=100.0, stop_loss=90.0
    )
    assert wide_stop < tight_stop  # шире стоп -> меньше размер при том же риске


def test_calculate_position_size_works_for_short():
    # SL выше входа (шорт) -- дистанция считается по модулю
    size = position_manager.calculate_position_size(
        balance=1000.0, risk_percent=1.0, entry_price=100.0, stop_loss=103.0
    )
    assert size == pytest.approx(10.0 / 3.0)


def test_calculate_position_size_zero_when_stop_equals_entry():
    size = position_manager.calculate_position_size(
        balance=1000.0, risk_percent=1.0, entry_price=100.0, stop_loss=100.0
    )
    assert size == 0.0
