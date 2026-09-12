import trading_storage


def setup_function():
    trading_storage.init_trading_db()
    trading_storage.init_paper_trading_db()


def test_set_trading_active_false_then_true():
    trading_storage.save_profile(
        chat_id=111, risk_percent=1.0, daily_loss_limit_percent=5.0, leverage=3.0,
        sl_method="atr", sl_fixed_percent=None, breakeven_after_tp=2,
        tp_split_preset="equal", max_concurrent_trades=3,
    )
    trading_storage.set_trading_active(111, False)
    assert trading_storage.get_profile(111)["is_active"] == 0

    trading_storage.set_trading_active(111, True)
    assert trading_storage.get_profile(111)["is_active"] == 1


def test_get_positions_closed_since_filters_by_chat_and_time():
    id1 = trading_storage.create_position(
        chat_id=111, symbol="BTCUSDT", exchange="Binance", direction="long",
        mode="paper", avg_entry_price=100.0, quantity=1.0, stop_loss=97.0,
    )
    trading_storage.create_position(
        chat_id=222, symbol="ETHUSDT", exchange="Binance", direction="long",
        mode="paper", avg_entry_price=100.0, quantity=1.0, stop_loss=97.0,
    )
    trading_storage.close_position(id1, realized_pnl=10.0)

    closed = trading_storage.get_positions_closed_since(111, "2000-01-01 00:00:00")
    assert len(closed) == 1
    assert closed[0]["id"] == id1


def test_get_positions_closed_since_excludes_older_than_cutoff():
    position_id = trading_storage.create_position(
        chat_id=111, symbol="BTCUSDT", exchange="Binance", direction="long",
        mode="paper", avg_entry_price=100.0, quantity=1.0, stop_loss=97.0,
    )
    trading_storage.close_position(position_id, realized_pnl=10.0)

    closed = trading_storage.get_positions_closed_since(111, "2099-01-01 00:00:00")
    assert closed == []
