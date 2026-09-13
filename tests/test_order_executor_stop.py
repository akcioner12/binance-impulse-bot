import pytest

import order_executor


def _long_state(quantity=4.0, stop_loss=97.0):
    return order_executor.OpenPositionState(
        position_id=1, direction="long", avg_entry_price=100.0, quantity=quantity,
        stop_loss=stop_loss,
        take_profits=[{"level": 110.0, "size_pct": 25}, {"level": 120.0, "size_pct": 25}, {"level": 130.0, "size_pct": 25}],
        breakeven_after_tp=2,
    )


def test_check_stop_hit_long_triggers_below_stop():
    state = _long_state()
    result = order_executor.check_stop_hit(state, price=96.0, atr_1h=2.0)

    assert result["event"] == "closed_stop_loss"
    assert result["pnl_delta"] == pytest.approx(-16.0)  # 4.0 * (96 - 100)
    assert result["size_closed"] == 4.0
    assert result["exit_price"] == 96.0
    assert state.closed is True


def test_check_stop_hit_long_no_trigger_above_stop():
    state = _long_state()
    result = order_executor.check_stop_hit(state, price=98.0, atr_1h=2.0)
    assert result is None
    assert state.closed is False


def test_check_stop_hit_short_triggers_above_stop():
    state = order_executor.OpenPositionState(
        position_id=2, direction="short", avg_entry_price=100.0, quantity=4.0,
        stop_loss=103.0, take_profits=[], breakeven_after_tp=2,
    )
    result = order_executor.check_stop_hit(state, price=104.0, atr_1h=2.0)
    assert result["event"] == "closed_stop_loss"
    assert result["pnl_delta"] == pytest.approx(-16.0)  # 4.0 * (100 - 104)


def test_check_stop_hit_returns_none_when_already_closed():
    state = _long_state()
    order_executor.check_stop_hit(state, price=96.0, atr_1h=2.0)  # закрывает
    result = order_executor.check_stop_hit(state, price=50.0, atr_1h=2.0)
    assert result is None


def test_check_stop_hit_uses_chandelier_when_active():
    state = _long_state()
    state.chandelier = order_executor.ChandelierTrailingStop(direction="long", atr_multiplier=2.5)
    state.remaining_quantity = 1.0  # только остаток TP4 после частичных закрытий

    # Первый тик активирует трейлинг (стоп = 135 - 2.5*2 = 130), не триггерит сам по себе
    result = order_executor.check_stop_hit(state, price=135.0, atr_1h=2.0)
    assert result is None

    # Откат ниже уровня трейлинга -> закрытие
    result = order_executor.check_stop_hit(state, price=129.0, atr_1h=2.0)
    assert result["event"] == "closed_chandelier"
    assert result["size_closed"] == 1.0
    assert result["exit_price"] == 129.0
    assert result["pnl_delta"] == pytest.approx(29.0)  # 1.0 * (129 - 100)


def test_chandelier_widens_when_realized_volatility_spikes():
    """
    Регрессия по реальному прод-кейсу (LSKUSDT): если рынок после входа резко
    становится волатильнее, чем ATR(1ч) на момент входа предполагал, Chandelier
    должен расшириться за счёт локально накопленной реализованной волатильности
    (RealizedVolatilityTracker), а не выбивать позицию на первом же откате,
    посчитанном по устаревшему "спокойному" ATR.

    Важно: трекер копит волатильность с момента ОТКРЫТИЯ позиции (не с момента
    активации Chandelier) -- Chandelier сам "трещотка" (стоп только сужается),
    поэтому если резкие движения случились бы уже ПОСЛЕ первого тика Chandelier,
    расширить уже зафиксированный узкий стоп было бы нельзя. В реальном коде
    Chandelier включается на TP3, который наступает через несколько тиков после
    входа -- трекер к этому моменту уже "прогрет" реальными данными сделки.
    """
    state = order_executor.OpenPositionState(
        position_id=3, direction="short", avg_entry_price=100.0, quantity=1.0,
        stop_loss=999.0, take_profits=[], breakeven_after_tp=2,
    )
    state.remaining_quantity = 1.0

    # Позиция ещё без Chandelier (обычный SL, недостижим) -- копим реализованную
    # волатильность на будущее, как это происходит между входом и TP3 в реальном коде
    order_executor.check_stop_hit(state, price=100.0, atr_1h=2.0)  # diff нет (первая цена)
    order_executor.check_stop_hit(state, price=90.0, atr_1h=2.0)   # diff=10
    order_executor.check_stop_hit(state, price=70.0, atr_1h=2.0)   # diff=20
    order_executor.check_stop_hit(state, price=71.0, atr_1h=2.0)   # diff=1 -- 3 диффа накоплены: [10,20,1]

    # TP3 срабатывает -- активируем Chandelier (как в check_take_profit_hits)
    state.chandelier = order_executor.ChandelierTrailingStop(direction="short", atr_multiplier=2.5)

    # Первый тик Chandelier сразу видит прогретую реализованную волатильность (max=20)
    result = order_executor.check_stop_hit(state, price=72.0, atr_1h=2.0)
    assert result is None
    assert state.chandelier.stop_price == pytest.approx(122.0)  # 72 + 2.5*20 (не 72 + 2.5*2.0 = 77)

    # Резкий отскок до 90 пробил бы "спокойный" стоп (~77), но не пробивает 122
    result = order_executor.check_stop_hit(state, price=90.0, atr_1h=2.0)
    assert result is None
    assert state.closed is False
