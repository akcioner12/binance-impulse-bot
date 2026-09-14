import time

from analyzer import DailyHighTracker


def test_daily_high_tracker_fires_signal_on_30_percent_drawdown_from_seeded_peak():
    tracker = DailyHighTracker()
    day0 = 10 * 86400

    tracker.seed_history("LSKUSDT", daily_highs=[100.0] * 9, current_day_high=100.0, current_day_start_ts=day0)

    signal = tracker.update("LSKUSDT", "Binance", price=69.0, ts=day0)

    assert signal is not None
    assert signal.direction == "down"
    assert signal.level == 30.0
    assert signal.window_start_price == 100.0
    assert signal.change_pct == -31.0


def test_daily_high_tracker_no_signal_below_threshold():
    tracker = DailyHighTracker()
    day0 = 10 * 86400

    tracker.seed_history("LSKUSDT", daily_highs=[100.0] * 9, current_day_high=100.0, current_day_start_ts=day0)

    signal = tracker.update("LSKUSDT", "Binance", price=75.0, ts=day0)  # -25%, ниже порога 30%

    assert signal is None
    assert tracker.is_active("LSKUSDT") is False


def test_daily_high_tracker_escalates_level_on_deeper_drop():
    tracker = DailyHighTracker()
    day0 = 10 * 86400

    tracker.seed_history("LSKUSDT", daily_highs=[100.0] * 9, current_day_high=100.0, current_day_start_ts=day0)

    first = tracker.update("LSKUSDT", "Binance", price=69.0, ts=day0)     # -31%
    second = tracker.update("LSKUSDT", "Binance", price=58.0, ts=day0)    # -42%

    assert first.level == 30.0
    assert second is not None
    assert second.level == 40.0
    assert second.window_start_price == 100.0  # anchor не сдвинулся


def test_daily_high_tracker_resets_on_hysteresis_recovery():
    tracker = DailyHighTracker()
    day0 = 10 * 86400

    tracker.seed_history("LSKUSDT", daily_highs=[100.0] * 9, current_day_high=100.0, current_day_start_ts=day0)

    tracker.update("LSKUSDT", "Binance", price=69.0, ts=day0)             # -31%, level 30
    recovered = tracker.update("LSKUSDT", "Binance", price=91.0, ts=day0)  # -9%, ниже порога сброса (30-20=10)

    assert recovered is None
    assert tracker.is_active("LSKUSDT") is False


def test_daily_high_tracker_keeps_anchor_pinned_while_signal_active_even_if_live_max_would_shrink():
    tracker = DailyHighTracker()
    day0 = 10 * 86400

    tracker.seed_history("LSKUSDT", daily_highs=[100.0] * 9, current_day_high=100.0, current_day_start_ts=day0)

    first = tracker.update("LSKUSDT", "Binance", price=69.0, ts=day0)  # -31% от 100 -- сигнал, anchor=100.0
    assert first is not None
    assert first.window_start_price == 100.0

    next_day = day0 + 86400
    second = tracker.update("LSKUSDT", "Binance", price=68.0, ts=next_day)  # ~-32% от anchor=100, эскалации до 40 нет

    assert tracker.is_active("LSKUSDT") is True
    assert second is None


def test_daily_high_tracker_recomputes_live_rolling_max_after_old_peak_expires():
    tracker = DailyHighTracker()
    day0 = 10 * 86400

    # Один высокий день (100) в истории среди восьми дней по 60 -- после
    # выпадения "100" из 9-элементного окна живой rolling max должен стать 60.
    tracker.seed_history("LSKUSDT", daily_highs=[100.0] + [60.0] * 8, current_day_high=60.0, current_day_start_ts=day0)

    next_day = day0 + 86400
    tracker.update("LSKUSDT", "Binance", price=60.0, ts=next_day)  # переход через сутки -- "100" вытесняется

    signal = tracker.update("LSKUSDT", "Binance", price=45.0, ts=next_day)  # -25% от 60 -- ниже порога
    assert signal is None

    signal = tracker.update("LSKUSDT", "Binance", price=41.0, ts=next_day)  # -31.7% от 60 -- сигнал
    assert signal is not None
    assert signal.window_start_price == 60.0


def test_daily_high_tracker_seed_history_sets_rolling_max_from_max_of_all_sources():
    tracker = DailyHighTracker()
    day0 = 10 * 86400

    tracker.seed_history("LSKUSDT", daily_highs=[80.0, 90.0], current_day_high=70.0, current_day_start_ts=day0)

    signal = tracker.update("LSKUSDT", "Binance", price=62.0, ts=day0)  # -31.1% от 90 (максимум среди 80/90/70)

    assert signal is not None
    assert signal.window_start_price == 90.0


def test_daily_high_tracker_seed_history_does_not_overwrite_existing_data():
    tracker = DailyHighTracker()
    day0 = 10 * 86400

    tracker.update("LSKUSDT", "Binance", price=50.0, ts=day0)  # реальный тик пришёл первым
    tracker.seed_history("LSKUSDT", daily_highs=[1000.0] * 9, current_day_high=1000.0, current_day_start_ts=day0)

    signal = tracker.update("LSKUSDT", "Binance", price=34.0, ts=day0)  # -32% от 50, а не от 1000

    assert signal is not None
    assert signal.window_start_price == 50.0
