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
