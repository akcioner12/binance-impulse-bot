import magnet_levels


def _candle(high, low):
    return {"open_time": 0, "open": (high + low) / 2, "high": high, "low": low, "close": (high + low) / 2, "volume": 1.0}


def _candles_with_swing_high(peak_value: float, base: float = 100.0) -> list[dict]:
    highs = [base + i for i in range(4)] + [peak_value] + [base + i for i in range(3, -1, -1)]
    return [_candle(high=h, low=h - 1) for h in highs]


def test_find_magnet_levels_up_returns_daily_levels_above_price():
    daily = _candles_with_swing_high(peak_value=150.0, base=100.0)
    weekly = _candles_with_swing_high(peak_value=200.0, base=100.0)

    levels = magnet_levels.find_magnet_levels(daily, weekly, current_price=120.0, direction="up", window=2)

    assert 150.0 in levels  # ближний/средний уровень с дневных свечей
    assert 200.0 in levels  # дальний уровень с недельных свечей
    # Ближе к цене должен идти раньше в списке
    assert levels.index(150.0) < levels.index(200.0)


def test_find_magnet_levels_down_returns_daily_levels_below_price():
    daily_lows = [100 - i for i in range(4)] + [80.0] + [100 - i for i in range(3, -1, -1)]
    daily = [_candle(high=l + 1, low=l) for l in daily_lows]
    weekly_lows = [100 - i for i in range(4)] + [50.0] + [100 - i for i in range(3, -1, -1)]
    weekly = [_candle(high=l + 1, low=l) for l in weekly_lows]

    levels = magnet_levels.find_magnet_levels(daily, weekly, current_price=90.0, direction="down", window=2)

    assert 80.0 in levels
    assert 50.0 in levels
    assert levels.index(80.0) < levels.index(50.0)


def test_find_magnet_levels_ignores_levels_on_wrong_side_of_price():
    daily = _candles_with_swing_high(peak_value=150.0, base=100.0)
    weekly = _candles_with_swing_high(peak_value=200.0, base=100.0)

    # current_price выше обоих уровней -> для направления 'up' магнитов быть не должно
    levels = magnet_levels.find_magnet_levels(daily, weekly, current_price=250.0, direction="up", window=2)
    assert levels == []


def test_find_magnet_levels_limits_daily_levels_to_two():
    # Две отдельные дневные вершины выше цены + ещё одна лишняя -> берём только 2 ближайшие
    highs = [100, 101, 102, 130.0, 101, 100, 99, 140.0, 99, 98, 97, 160.0, 97, 96]
    daily = [_candle(high=h, low=h - 1) for h in highs]
    weekly = _candles_with_swing_high(peak_value=200.0, base=100.0)

    levels = magnet_levels.find_magnet_levels(daily, weekly, current_price=110.0, direction="up", window=2)

    daily_levels_found = [lvl for lvl in levels if lvl in (130.0, 140.0, 160.0)]
    assert len(daily_levels_found) <= 2


def test_find_magnet_levels_empty_when_no_candles():
    assert magnet_levels.find_magnet_levels([], [], current_price=100.0, direction="up") == []
