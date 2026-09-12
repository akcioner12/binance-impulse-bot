import position_manager


def test_chandelier_long_stop_starts_below_first_price():
    trail = position_manager.ChandelierTrailingStop(direction="long", atr_multiplier=2.5)
    stop = trail.update(price=100.0, atr=2.0)
    assert stop == 95.0  # 100 - 2.5*2.0


def test_chandelier_long_stop_rises_with_new_highs():
    trail = position_manager.ChandelierTrailingStop(direction="long", atr_multiplier=2.5)
    trail.update(price=100.0, atr=2.0)
    stop = trail.update(price=110.0, atr=2.0)
    assert stop == 105.0  # 110 - 2.5*2.0, стоп подтянулся


def test_chandelier_long_stop_never_moves_down():
    trail = position_manager.ChandelierTrailingStop(direction="long", atr_multiplier=2.5)
    trail.update(price=100.0, atr=2.0)  # stop = 95.0
    trail.update(price=110.0, atr=2.0)  # stop = 105.0
    stop = trail.update(price=95.0, atr=2.0)  # откат -- экстремум остаётся 110, стоп не падает
    assert stop == 105.0


def test_chandelier_short_stop_starts_above_first_price():
    trail = position_manager.ChandelierTrailingStop(direction="short", atr_multiplier=2.5)
    stop = trail.update(price=100.0, atr=2.0)
    assert stop == 105.0  # 100 + 2.5*2.0


def test_chandelier_short_stop_falls_with_new_lows():
    trail = position_manager.ChandelierTrailingStop(direction="short", atr_multiplier=2.5)
    trail.update(price=100.0, atr=2.0)
    stop = trail.update(price=90.0, atr=2.0)
    assert stop == 95.0  # 90 + 2.5*2.0


def test_chandelier_short_stop_never_moves_up():
    trail = position_manager.ChandelierTrailingStop(direction="short", atr_multiplier=2.5)
    trail.update(price=100.0, atr=2.0)  # stop = 105.0
    trail.update(price=90.0, atr=2.0)  # stop = 95.0
    stop = trail.update(price=105.0, atr=2.0)  # откат вверх -- стоп не поднимается
    assert stop == 95.0


def test_chandelier_is_triggered_long():
    trail = position_manager.ChandelierTrailingStop(direction="long", atr_multiplier=2.5)
    trail.update(price=100.0, atr=2.0)  # stop = 95.0
    assert trail.is_triggered(price=96.0) is False
    assert trail.is_triggered(price=95.0) is True
    assert trail.is_triggered(price=94.0) is True


def test_chandelier_is_triggered_short():
    trail = position_manager.ChandelierTrailingStop(direction="short", atr_multiplier=2.5)
    trail.update(price=100.0, atr=2.0)  # stop = 105.0
    assert trail.is_triggered(price=104.0) is False
    assert trail.is_triggered(price=105.0) is True
    assert trail.is_triggered(price=106.0) is True


def test_chandelier_is_triggered_false_before_first_update():
    trail = position_manager.ChandelierTrailingStop(direction="long")
    assert trail.is_triggered(price=50.0) is False
