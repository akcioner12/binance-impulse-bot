import pytest
from unittest.mock import patch

import entry_engine
import live_trading


PROFILE = {
    "is_active": 1, "max_concurrent_trades": 3, "risk_percent": 1.0,
    "sl_method": "atr", "sl_fixed_percent": None, "tp_split_preset": "equal",
    "breakeven_after_tp": 2,
}


def _make_pending_setup(direction="up"):
    return {
        "chat_id": 111, "exchange": "Binance", "signal_id": 55,
        "impulse_direction": direction, "window_start_price": 70.0,
        "cap_reference_price": None, "last_atr_refresh_price": None,
        "trigger_part1": entry_engine.create_part1_trigger(direction, atr_15m=1.0),  # distance 0.75
        "trigger_part2": entry_engine.create_part2_trigger(direction, atr_15m=1.0),  # distance 2.0
        "part_size": 2.0, "atr_1h": 2.0, "magnet_levels": [], "profile": PROFILE,
    }


def setup_function():
    live_trading._pending_setups.clear()
    live_trading._open_positions.clear()


def test_tick_does_nothing_before_any_trigger_fires():
    live_trading._pending_setups["BTCUSDT"] = _make_pending_setup()
    with patch("live_trading.trading_storage.create_position", return_value=1):
        events = live_trading.handle_price_tick("BTCUSDT", price=100.0)  # первая цена, экстремум устанавливается
    assert events is None
    assert "BTCUSDT" in live_trading._pending_setups  # ещё ждём


def test_part1_fire_opens_position():
    live_trading._pending_setups["BTCUSDT"] = _make_pending_setup()
    with patch("live_trading.trading_storage.create_position", return_value=1), \
         patch("live_trading.trading_storage.update_trade_signal_status") as mock_status:
        live_trading.handle_price_tick("BTCUSDT", price=100.0)   # экстремум = 100
        events = live_trading.handle_price_tick("BTCUSDT", price=99.2)  # откат 0.8 >= 0.75 -> часть 1 срабатывает

    assert events == ["part1_filled"]
    assert "BTCUSDT" in live_trading._open_positions
    mock_status.assert_called_once_with(55, "executed")


def test_part2_merges_into_still_open_part1_position():
    live_trading._pending_setups["BTCUSDT"] = _make_pending_setup()
    with patch("live_trading.trading_storage.create_position", side_effect=[1, 2]), \
         patch("live_trading.trading_storage.close_position") as mock_close, \
         patch("live_trading.trading_storage.update_trade_signal_status"):
        live_trading.handle_price_tick("BTCUSDT", price=100.0)
        live_trading.handle_price_tick("BTCUSDT", price=99.2)   # часть 1 срабатывает (open, id=1)
        events = live_trading.handle_price_tick("BTCUSDT", price=98.0)  # откат 2.0 от 100 -> часть 2 срабатывает

    assert "part2_filled" in events
    assert "setup_complete" in events
    mock_close.assert_called_once()  # старая позиция части 1 технически закрыта при пересборке
    assert "BTCUSDT" not in live_trading._pending_setups  # обе части обработаны


def test_part2_opens_independent_position_when_part1_already_closed():
    live_trading._pending_setups["BTCUSDT"] = _make_pending_setup()
    with patch("live_trading.trading_storage.create_position", side_effect=[1, 2]), \
         patch("live_trading.trading_storage.update_trade_signal_status"):
        live_trading.handle_price_tick("BTCUSDT", price=100.0)
        live_trading.handle_price_tick("BTCUSDT", price=99.2)  # часть 1 срабатывает, position id=1

    # Имитируем, что позиция части 1 уже закрылась по стопу (до срабатывания части 2)
    live_trading._open_positions["BTCUSDT"]["state"].closed = True

    with patch("live_trading.trading_storage.create_position", return_value=2), \
         patch("live_trading.trading_storage.close_position") as mock_close, \
         patch("live_trading.trading_storage.update_trade_signal_status"):
        events = live_trading.handle_price_tick("BTCUSDT", price=98.0)  # часть 2 срабатывает

    assert "part2_filled" in events
    mock_close.assert_not_called()  # НЕ пересобираем закрытую позицию -- часть 2 отдельная


def test_setup_does_not_expire_below_pump_extension_cap():
    """
    Регрессия по ретроспективному анализу (13.09.2026): многие реальные манипуляции
    продолжаются значительно дальше +90% до разворота -- старый потолок 90% выбрасывал
    их из рассмотрения ещё до того, как трейлинг-триггер получал шанс сработать.
    Потолок для пампов поднят до 200%.
    """
    setup = _make_pending_setup()  # impulse_direction="up" по умолчанию
    live_trading._pending_setups["BTCUSDT"] = setup
    with patch("live_trading.trading_storage.update_trade_signal_status") as mock_status:
        live_trading.handle_price_tick("BTCUSDT", price=100.0)  # первый тик -- точка отсчёта потолка = 100
        # 100 -> 191 = +91% -- выше СТАРОГО потолка (90%), но ниже НОВОГО (200%).
        # Это также выше шага обновления ATR (50%), поэтому событие всё же есть,
        # но это запрос на обновление ATR, а не истечение сетапа.
        events = live_trading.handle_price_tick("BTCUSDT", price=191.0)

    assert events == ["atr_refresh_needed"]
    assert "BTCUSDT" in live_trading._pending_setups
    mock_status.assert_not_called()


def test_setup_expires_beyond_pump_extension_cap():
    setup = _make_pending_setup()
    live_trading._pending_setups["BTCUSDT"] = setup
    with patch("live_trading.trading_storage.update_trade_signal_status") as mock_status:
        live_trading.handle_price_tick("BTCUSDT", price=100.0)
        # 100 -> 305 = +205%, выше нового потолка 200% для пампов
        events = live_trading.handle_price_tick("BTCUSDT", price=305.0)

    assert events == ["setup_expired"]
    assert "BTCUSDT" not in live_trading._pending_setups
    mock_status.assert_called_once_with(55, "expired")


def test_setup_still_expires_at_old_cap_for_dump_direction():
    """
    Потолок для дампов НЕ поднимался (остаётся 90%) -- в отличие от пампов, падение
    физически ограничено -100% (цена не может уйти ниже нуля), поэтому "раздвигать"
    его так же, как для пампов, не имеет смысла.
    """
    setup = _make_pending_setup(direction="down")
    live_trading._pending_setups["BTCUSDT"] = setup
    with patch("live_trading.trading_storage.update_trade_signal_status") as mock_status:
        live_trading.handle_price_tick("BTCUSDT", price=100.0)
        # 100 -> 9 = -91%, выше потолка 90% для дампов
        events = live_trading.handle_price_tick("BTCUSDT", price=9.0)

    assert events == ["setup_expired"]
    assert "BTCUSDT" not in live_trading._pending_setups
    mock_status.assert_called_once_with(55, "expired")


def test_setup_does_not_expire_from_stale_window_start_price():
    """
    Регрессия по реальному прод-инциденту: window_start_price из детектора импульса
    может быть сильно устаревшим (например, "цена ~24ч назад"/на момент рестарта бота),
    а не реальным стартом ЭТОЙ конкретной попытки входа. Потолок должен считаться от
    цены на момент начала мониторинга сетапа (первый тик), а не от этого устаревшего
    значения -- иначе сетап истекает почти мгновенно даже без реального движения.
    """
    setup = _make_pending_setup()
    setup["window_start_price"] = 10.0  # сильно устаревшее значение (+900% от него уже сейчас)
    live_trading._pending_setups["BTCUSDT"] = setup
    with patch("live_trading.trading_storage.update_trade_signal_status") as mock_status:
        live_trading.handle_price_tick("BTCUSDT", price=100.0)  # точка отсчёта потолка = 100, не 10
        events = live_trading.handle_price_tick("BTCUSDT", price=102.0)  # +2% от точки старта мониторинга

    assert events is None
    assert "BTCUSDT" in live_trading._pending_setups
    mock_status.assert_not_called()


def test_tick_signals_atr_refresh_after_large_move_without_fill():
    """
    Триггеры считают дистанцию отката от ATR, посчитанного один раз в момент
    старта мониторинга сетапа. Если цена уходит далеко без отката, эта ATR
    устаревает -- нужно периодически её обновлять, иначе триггер сработает
    на шуме, несопоставимом с текущей волатильностью.
    """
    setup = _make_pending_setup()
    live_trading._pending_setups["BTCUSDT"] = setup
    with patch("live_trading.trading_storage.update_trade_signal_status"):
        live_trading.handle_price_tick("BTCUSDT", price=100.0)  # точка отсчёта = 100
        # 100 -> 151 = +51%, выше шага обновления ATR (50%), ниже потолка истечения (200%)
        events = live_trading.handle_price_tick("BTCUSDT", price=151.0)

    assert events == ["atr_refresh_needed"]
    assert "BTCUSDT" in live_trading._pending_setups  # сетап не истёк, просто просит обновить ATR
    assert live_trading._pending_setups["BTCUSDT"]["last_atr_refresh_price"] == 151.0


def test_tick_does_not_repeat_atr_refresh_before_next_step():
    setup = _make_pending_setup()
    live_trading._pending_setups["BTCUSDT"] = setup
    with patch("live_trading.trading_storage.update_trade_signal_status"):
        live_trading.handle_price_tick("BTCUSDT", price=100.0)
        live_trading.handle_price_tick("BTCUSDT", price=151.0)  # обновление #1, точка отсчёта обновления -> 151
        events = live_trading.handle_price_tick("BTCUSDT", price=160.0)  # +6% от 151 -- ниже следующего шага

    assert events is None


def test_tick_signals_atr_refresh_again_after_another_step():
    setup = _make_pending_setup()
    live_trading._pending_setups["BTCUSDT"] = setup
    with patch("live_trading.trading_storage.update_trade_signal_status"):
        live_trading.handle_price_tick("BTCUSDT", price=100.0)
        live_trading.handle_price_tick("BTCUSDT", price=151.0)  # обновление #1, точка отсчёта -> 151
        events = live_trading.handle_price_tick("BTCUSDT", price=227.0)  # +50.3% от 151

    assert events == ["atr_refresh_needed"]


def test_handle_price_tick_returns_none_for_unknown_symbol():
    assert live_trading.handle_price_tick("UNKNOWN", price=100.0) is None
