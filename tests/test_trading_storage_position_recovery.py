import trading_storage


def setup_function():
    trading_storage.init_trading_db()
    trading_storage.init_paper_trading_db()


def test_create_position_stores_recovery_fields_with_defaults():
    position_id = trading_storage.create_position(
        chat_id=111, symbol="BTCUSDT", exchange="Binance", direction="short",
        mode="paper", avg_entry_price=100.0, quantity=4.0, stop_loss=103.0,
    )
    position = trading_storage.get_position(position_id)
    assert position["original_stop_loss"] == 103.0  # по умолчанию = stop_loss на входе
    assert position["tp_split_preset"] == "equal"
    assert position["breakeven_after_tp"] == 2
    assert position["atr_1h"] is None
    assert position["remaining_quantity"] == 4.0  # изначально = полный объём
    assert position["tp1_filled"] == 0
    assert position["tp2_filled"] == 0
    assert position["tp3_filled"] == 0
    assert position["chandelier_active"] == 0
    assert position["chandelier_extreme_price"] is None
    assert position["chandelier_stop_price"] is None


def test_create_position_stores_explicit_recovery_fields():
    position_id = trading_storage.create_position(
        chat_id=111, symbol="BTCUSDT", exchange="Binance", direction="short",
        mode="paper", avg_entry_price=100.0, quantity=4.0, stop_loss=103.0,
        original_stop_loss=105.0, tp_split_preset="aggressive",
        breakeven_after_tp=3, atr_1h=1.5,
    )
    position = trading_storage.get_position(position_id)
    assert position["original_stop_loss"] == 105.0
    assert position["tp_split_preset"] == "aggressive"
    assert position["breakeven_after_tp"] == 3
    assert position["atr_1h"] == 1.5


def test_create_position_stores_tp_r_multiples_default():
    position_id = trading_storage.create_position(
        chat_id=111, symbol="BTCUSDT", exchange="Binance", direction="short",
        mode="paper", avg_entry_price=100.0, quantity=4.0, stop_loss=103.0,
    )
    position = trading_storage.get_position(position_id)
    assert position["tp_r_multiples"] == "1.0,2.0,3.0"


def test_create_position_stores_explicit_tp_r_multiples():
    position_id = trading_storage.create_position(
        chat_id=111, symbol="BTCUSDT", exchange="Binance", direction="long",
        mode="paper", avg_entry_price=100.0, quantity=4.0, stop_loss=97.0,
        tp_r_multiples=(1.5, 3.0, 5.0),
    )
    position = trading_storage.get_position(position_id)
    assert position["tp_r_multiples"] == "1.5,3.0,5.0"


def test_update_position_progress_persists_tp_and_chandelier_state():
    position_id = trading_storage.create_position(
        chat_id=111, symbol="BTCUSDT", exchange="Binance", direction="short",
        mode="paper", avg_entry_price=100.0, quantity=4.0, stop_loss=103.0,
    )
    trading_storage.update_position_progress(
        position_id,
        tp1_filled=True, tp2_filled=True, tp3_filled=False,
        remaining_quantity=1.0,
        chandelier_active=True, chandelier_extreme_price=90.0, chandelier_stop_price=95.0,
    )
    position = trading_storage.get_position(position_id)
    assert position["tp1_filled"] == 1
    assert position["tp2_filled"] == 1
    assert position["tp3_filled"] == 0
    assert position["remaining_quantity"] == 1.0
    assert position["chandelier_active"] == 1
    assert position["chandelier_extreme_price"] == 90.0
    assert position["chandelier_stop_price"] == 95.0


def test_get_all_open_positions_returns_across_all_chats():
    id1 = trading_storage.create_position(
        chat_id=111, symbol="BTCUSDT", exchange="Binance", direction="long",
        mode="paper", avg_entry_price=100.0, quantity=1.0, stop_loss=97.0,
    )
    id2 = trading_storage.create_position(
        chat_id=222, symbol="ETHUSDT", exchange="Binance", direction="short",
        mode="paper", avg_entry_price=3000.0, quantity=1.0, stop_loss=3100.0,
    )
    closed_id = trading_storage.create_position(
        chat_id=111, symbol="SOLUSDT", exchange="Binance", direction="long",
        mode="paper", avg_entry_price=50.0, quantity=1.0, stop_loss=48.0,
    )
    trading_storage.close_position(closed_id, realized_pnl=5.0)

    open_positions = trading_storage.get_all_open_positions()
    ids = {p["id"] for p in open_positions}
    assert ids == {id1, id2}


def test_count_recent_signals_counts_within_window():
    trading_storage.create_trade_signal(
        chat_id=111, symbol="LSKUSDT", exchange="Binance",
        impulse_direction="up", classification="reversal",
    )
    trading_storage.create_trade_signal(
        chat_id=111, symbol="LSKUSDT", exchange="Binance",
        impulse_direction="up", classification="reversal",
    )
    trading_storage.create_trade_signal(
        chat_id=111, symbol="ETHUSDT", exchange="Binance",  # другой символ -- не считается
        impulse_direction="up", classification="reversal",
    )
    trading_storage.create_trade_signal(
        chat_id=222, symbol="LSKUSDT", exchange="Binance",  # другой чат -- не считается
        impulse_direction="up", classification="reversal",
    )

    count = trading_storage.count_recent_signals(111, "LSKUSDT", since="2000-01-01 00:00:00")
    assert count == 2


def test_count_recent_signals_excludes_older_than_since():
    trading_storage.create_trade_signal(
        chat_id=111, symbol="LSKUSDT", exchange="Binance",
        impulse_direction="up", classification="reversal",
    )
    count = trading_storage.count_recent_signals(111, "LSKUSDT", since="2099-01-01 00:00:00")
    assert count == 0


def test_expire_all_pending_signals_marks_them_expired_and_leaves_others():
    pending_id = trading_storage.create_trade_signal(
        chat_id=111, symbol="BTCUSDT", exchange="Binance",
        impulse_direction="up", classification="reversal",
    )
    executed_id = trading_storage.create_trade_signal(
        chat_id=111, symbol="ETHUSDT", exchange="Binance",
        impulse_direction="down", classification="reversal",
    )
    trading_storage.update_trade_signal_status(executed_id, "executed")

    trading_storage.expire_all_pending_signals()

    assert trading_storage.get_trade_signal(pending_id)["status"] == "expired"
    assert trading_storage.get_trade_signal(executed_id)["status"] == "executed"  # не тронут
