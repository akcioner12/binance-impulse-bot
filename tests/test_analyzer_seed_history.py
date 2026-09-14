import time

from analyzer import PriceWindowTracker


def test_seed_history_lets_update_detect_signal_immediately():
    """
    Без сидирования буфер после рестарта пуст, и новый тик ничего не может
    сравнить -- окно эффективно "теряет память" на 24ч. Сидирование должно
    сразу дать update() достаточно истории для детекции.
    """
    tracker = PriceWindowTracker()
    now = int(time.time())
    day_ago = now - 24 * 3600

    tracker.seed_history("BTCUSDT", [(day_ago, 100.0), (now - 3600, 105.0)])
    signal = tracker.update("BTCUSDT", "Binance", price=132.0, ts=now)

    assert signal is not None
    assert signal.level == 30.0
    assert signal.window_start_price == 100.0


def test_seed_history_does_not_overwrite_existing_buffer():
    """Реальный тик, пришедший раньше сидирования (WS уже успел прислать данные), не должен затираться устаревшими сид-точками."""
    tracker = PriceWindowTracker()
    now = int(time.time())

    tracker.update("BTCUSDT", "Binance", price=50.0, ts=now - 10)  # реальный тик первым
    tracker.seed_history("BTCUSDT", [(now - 24 * 3600, 1.0)])  # сид пытается прийти позже

    signal = tracker.update("BTCUSDT", "Binance", price=51.0, ts=now)
    assert signal is None  # +2% от реального тика (50->51), сид ("1.0") не должен был подмешаться


def test_seed_history_orders_out_of_order_points_by_timestamp():
    tracker = PriceWindowTracker()
    now = int(time.time())
    day_ago = now - 24 * 3600

    # Передаём точки НЕ по порядку времени
    tracker.seed_history("ETHUSDT", [(now - 3600, 105.0), (day_ago, 100.0)])
    signal = tracker.update("ETHUSDT", "Binance", price=132.0, ts=now)

    assert signal is not None
    assert signal.window_start_price == 100.0  # самая старая точка, а не первая переданная


def test_seed_history_empty_points_is_noop():
    tracker = PriceWindowTracker()
    tracker.seed_history("BTCUSDT", [])
    assert tracker.is_active("BTCUSDT") is False
