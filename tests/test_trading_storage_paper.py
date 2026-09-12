import trading_storage


def setup_function():
    trading_storage.init_trading_db()
    trading_storage.init_paper_trading_db()


def test_get_paper_balance_none_when_not_initialized():
    assert trading_storage.get_paper_balance(111) is None


def test_init_paper_balance_sets_starting_value():
    trading_storage.init_paper_balance(111, starting_balance=1000.0)
    assert trading_storage.get_paper_balance(111) == 1000.0


def test_init_paper_balance_does_not_overwrite_existing():
    trading_storage.init_paper_balance(111, starting_balance=1000.0)
    trading_storage.init_paper_balance(111, starting_balance=5000.0)  # повторный вызов -- игнорируется
    assert trading_storage.get_paper_balance(111) == 1000.0


def test_adjust_paper_balance_adds_positive_delta():
    trading_storage.init_paper_balance(111, starting_balance=1000.0)
    new_balance = trading_storage.adjust_paper_balance(111, delta=50.0)
    assert new_balance == 1050.0
    assert trading_storage.get_paper_balance(111) == 1050.0


def test_adjust_paper_balance_subtracts_negative_delta():
    trading_storage.init_paper_balance(111, starting_balance=1000.0)
    new_balance = trading_storage.adjust_paper_balance(111, delta=-30.0)
    assert new_balance == 970.0


def test_paper_balance_isolated_per_chat_id():
    trading_storage.init_paper_balance(111, starting_balance=1000.0)
    trading_storage.init_paper_balance(222, starting_balance=2000.0)
    assert trading_storage.get_paper_balance(111) == 1000.0
    assert trading_storage.get_paper_balance(222) == 2000.0


def test_create_position_returns_id_and_defaults_to_open():
    position_id = trading_storage.create_position(
        chat_id=111, symbol="BTCUSDT", exchange="Binance", direction="short",
        mode="paper", avg_entry_price=50000.0, quantity=0.01, stop_loss=51000.0,
    )
    assert isinstance(position_id, int)
    position = trading_storage.get_position(position_id)
    assert position["status"] == "open"
    assert position["symbol"] == "BTCUSDT"
    assert position["direction"] == "short"
    assert position["avg_entry_price"] == 50000.0
    assert position["quantity"] == 0.01
    assert position["stop_loss"] == 51000.0
    assert position["realized_pnl"] == 0.0
    assert position["closed_at"] is None


def test_get_position_none_for_unknown_id():
    assert trading_storage.get_position(999999) is None


def test_get_open_positions_returns_only_open_for_chat():
    id1 = trading_storage.create_position(
        chat_id=111, symbol="BTCUSDT", exchange="Binance", direction="long",
        mode="paper", avg_entry_price=100.0, quantity=1.0, stop_loss=97.0,
    )
    id2 = trading_storage.create_position(
        chat_id=111, symbol="ETHUSDT", exchange="Binance", direction="short",
        mode="paper", avg_entry_price=3000.0, quantity=1.0, stop_loss=3100.0,
    )
    trading_storage.create_position(
        chat_id=222, symbol="BTCUSDT", exchange="Binance", direction="long",
        mode="paper", avg_entry_price=100.0, quantity=1.0, stop_loss=97.0,
    )
    trading_storage.close_position(id2, realized_pnl=50.0)

    open_positions = trading_storage.get_open_positions(111)
    assert len(open_positions) == 1
    assert open_positions[0]["id"] == id1


def test_update_position_stop_loss_changes_value():
    position_id = trading_storage.create_position(
        chat_id=111, symbol="BTCUSDT", exchange="Binance", direction="long",
        mode="paper", avg_entry_price=100.0, quantity=1.0, stop_loss=97.0,
    )
    trading_storage.update_position_stop_loss(position_id, new_stop_loss=100.08)
    position = trading_storage.get_position(position_id)
    assert position["stop_loss"] == 100.08


def test_close_position_sets_status_and_pnl():
    position_id = trading_storage.create_position(
        chat_id=111, symbol="BTCUSDT", exchange="Binance", direction="long",
        mode="paper", avg_entry_price=100.0, quantity=1.0, stop_loss=97.0,
    )
    trading_storage.close_position(position_id, realized_pnl=25.5)
    position = trading_storage.get_position(position_id)
    assert position["status"] == "closed"
    assert position["realized_pnl"] == 25.5
    assert position["closed_at"] is not None


def test_create_trade_signal_returns_id_and_defaults_to_pending():
    signal_id = trading_storage.create_trade_signal(
        chat_id=111, symbol="BTCUSDT", exchange="Binance",
        impulse_direction="up", classification="reversal",
    )
    assert isinstance(signal_id, int)
    signal = trading_storage.get_trade_signal(signal_id)
    assert signal["status"] == "pending"
    assert signal["symbol"] == "BTCUSDT"
    assert signal["impulse_direction"] == "up"
    assert signal["classification"] == "reversal"


def test_get_trade_signal_none_for_unknown_id():
    assert trading_storage.get_trade_signal(999999) is None


def test_update_trade_signal_status_changes_value():
    signal_id = trading_storage.create_trade_signal(
        chat_id=111, symbol="BTCUSDT", exchange="Binance",
        impulse_direction="down", classification="continuation",
    )
    trading_storage.update_trade_signal_status(signal_id, status="executed")
    signal = trading_storage.get_trade_signal(signal_id)
    assert signal["status"] == "executed"
