import pytest

import position_manager


def test_value_is_none_before_enough_samples():
    tracker = position_manager.RealizedVolatilityTracker(window=8)
    tracker.update(100.0)
    tracker.update(101.0)  # 1 diff
    assert tracker.value() is None  # нужно минимум 3 отсчёта (min_samples по умолчанию)


def test_value_becomes_available_at_min_samples():
    tracker = position_manager.RealizedVolatilityTracker(window=8)
    tracker.update(100.0)
    tracker.update(101.0)  # diff 1.0
    tracker.update(103.0)  # diff 2.0
    tracker.update(102.0)  # diff 1.0 -- 3-й отсчёт, теперь считается
    assert tracker.value() == 2.0  # максимум из [1.0, 2.0, 1.0]


def test_value_uses_max_not_average():
    """
    Максимум, а не среднее -- чтобы один резкий выброс (типичный для манипуляции)
    не "размывался" соседними спокойными тиками раньше времени.
    """
    tracker = position_manager.RealizedVolatilityTracker(window=8)
    tracker.update(100.0)
    tracker.update(100.1)  # diff 0.1
    tracker.update(105.0)  # diff 4.9 -- резкий выброс
    tracker.update(105.1)  # diff 0.1
    assert tracker.value() == pytest.approx(4.9)


def test_old_diffs_evicted_beyond_window():
    tracker = position_manager.RealizedVolatilityTracker(window=3)
    tracker.update(100.0)
    tracker.update(105.0)  # diff 5.0 -- позже вылетит из окна
    tracker.update(105.1)  # diff 0.1
    tracker.update(105.2)  # diff 0.1
    tracker.update(105.3)  # diff 0.1 -- теперь в окне только 3 последних: [0.1, 0.1, 0.1]
    assert tracker.value() == pytest.approx(0.1)


def test_value_respects_custom_min_samples():
    tracker = position_manager.RealizedVolatilityTracker(window=8)
    tracker.update(100.0)
    tracker.update(101.0)  # 1 diff
    assert tracker.value(min_samples=1) == 1.0
