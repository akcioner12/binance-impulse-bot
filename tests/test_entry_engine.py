import pytest

import entry_engine


def test_trigger_does_not_fire_on_first_price():
    trigger = entry_engine.TrailingEntryTrigger(direction="up", trigger_distance=2.0)
    fired = trigger.update(100.0)
    assert fired is False
    assert trigger.fired is False


def test_trigger_up_fires_on_pullback_from_max():
    # direction='up' -> ждём отката ВНИЗ от максимума (фейд пампа, шорт)
    trigger = entry_engine.TrailingEntryTrigger(direction="up", trigger_distance=2.0)
    trigger.update(100.0)
    trigger.update(105.0)  # новый максимум
    trigger.update(108.0)  # ещё выше -> максимум 108
    fired = trigger.update(106.5)  # откат 1.5 от 108 -- недостаточно (нужно 2.0)
    assert fired is False
    fired = trigger.update(105.9)  # откат 2.1 от 108 -- достаточно
    assert fired is True
    assert trigger.fired is True
    assert trigger.fire_price == 105.9


def test_trigger_down_fires_on_bounce_from_min():
    # direction='down' -> ждём отскока ВВЕРХ от минимума (фейд дампа, лонг)
    trigger = entry_engine.TrailingEntryTrigger(direction="down", trigger_distance=1.5)
    trigger.update(100.0)
    trigger.update(95.0)  # новый минимум
    trigger.update(93.0)  # ещё ниже -> минимум 93
    fired = trigger.update(94.0)  # отскок 1.0 от 93 -- недостаточно
    assert fired is False
    fired = trigger.update(94.6)  # отскок 1.6 от 93 -- достаточно
    assert fired is True
    assert trigger.fire_price == 94.6


def test_trigger_fires_only_once():
    trigger = entry_engine.TrailingEntryTrigger(direction="up", trigger_distance=1.0)
    trigger.update(100.0)
    trigger.update(105.0)
    assert trigger.update(103.5) is True  # первое срабатывание
    assert trigger.update(90.0) is False  # уже сработал -- игнорируем дальнейшие цены
    assert trigger.fire_price == 103.5  # не перезаписалось


def test_trigger_tracks_running_extreme_correctly():
    trigger = entry_engine.TrailingEntryTrigger(direction="up", trigger_distance=3.0)
    trigger.update(100.0)
    trigger.update(102.0)
    trigger.update(101.0)  # откат, но меньше trigger_distance -- максимум остаётся 102
    trigger.update(104.0)  # новый максимум 104
    fired = trigger.update(101.5)  # откат от 104 -- ровно 2.5, ещё недостаточно
    assert fired is False
    fired = trigger.update(101.0)  # откат 3.0 от 104 -- достаточно
    assert fired is True


def test_create_part1_trigger_uses_075_atr_multiplier():
    trigger = entry_engine.create_part1_trigger(direction="up", atr_15m=4.0)
    assert trigger.trigger_distance == pytest.approx(3.0)  # 0.75 * 4.0


def test_create_part2_trigger_uses_2x_atr_multiplier():
    trigger = entry_engine.create_part2_trigger(direction="up", atr_15m=4.0)
    assert trigger.trigger_distance == pytest.approx(8.0)  # 2.0 * 4.0


def test_part1_and_part2_triggers_are_independent_instances():
    part1 = entry_engine.create_part1_trigger(direction="down", atr_15m=2.0)
    part2 = entry_engine.create_part2_trigger(direction="down", atr_15m=2.0)

    part1.update(100.0)
    part1.update(95.0)
    part1_fired = part1.update(96.5)  # часть 1: тугой триггер 1.5 -- срабатывает

    part2.update(100.0)
    part2.update(95.0)
    part2_fired = part2.update(96.5)  # часть 2: широкий триггер 4.0 -- ещё не срабатывает

    assert part1_fired is True
    assert part2_fired is False
