import trading_storage


def setup_function():
    trading_storage.init_trading_db()
    trading_storage.init_paper_trading_db()


def test_record_and_get_trade_events_in_time_order():
    trading_storage.record_trade_event(111, "BTCUSDT", "tp1_hit", 10.0, ts="2026-09-19 10:00:00")
    trading_storage.record_trade_event(111, "BTCUSDT", "closed_stop_loss", -4.5, ts="2026-09-19 12:00:00")
    trading_storage.record_trade_event(111, "ETHUSDT", "tp1_hit", 7.0, ts="2026-09-19 09:00:00")
    trading_storage.record_trade_event(222, "BTCUSDT", "tp1_hit", 99.0, ts="2026-09-19 09:30:00")  # чужой chat_id

    events = trading_storage.get_trade_events(111)

    assert [(e["ts"], e["symbol"], e["event"], e["pnl"]) for e in events] == [
        ("2026-09-19 09:00:00", "ETHUSDT", "tp1_hit", 7.0),
        ("2026-09-19 10:00:00", "BTCUSDT", "tp1_hit", 10.0),
        ("2026-09-19 12:00:00", "BTCUSDT", "closed_stop_loss", -4.5),
    ]


def test_record_trade_event_defaults_ts_to_utc_now():
    trading_storage.record_trade_event(111, "BTCUSDT", "tp1_hit", 1.0)

    ts = trading_storage.get_trade_events(111)[0]["ts"]

    assert len(ts) == 19 and ts[4] == "-" and ts[10] == " "  # "YYYY-MM-DD HH:MM:SS"


def test_seed_trade_events_fills_empty_table_once():
    rows = [("2026-09-16 06:18:00", "RAYSOLUSDT", "tp1_hit", 30.5), ("2026-09-18 09:54:00", "RAYSOLUSDT", "closed_chandelier", 900.0)]

    assert trading_storage.seed_trade_events_if_empty(111, rows) == 2
    assert len(trading_storage.get_trade_events(111)) == 2

    # повторный запуск (рестарт бота) ничего не дублирует
    assert trading_storage.seed_trade_events_if_empty(111, rows) == 0
    assert len(trading_storage.get_trade_events(111)) == 2


def test_seed_trade_events_skips_when_live_events_already_recorded():
    trading_storage.record_trade_event(111, "BTCUSDT", "tp1_hit", 1.0, ts="2026-09-20 10:00:00")

    added = trading_storage.seed_trade_events_if_empty(111, [("2026-09-16 06:18:00", "RAYSOLUSDT", "tp1_hit", 30.5)])

    assert added == 0
    assert len(trading_storage.get_trade_events(111)) == 1
