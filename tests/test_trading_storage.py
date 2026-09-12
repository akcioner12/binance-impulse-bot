import storage
import trading_storage


def setup_function():
    trading_storage.init_trading_db()


def test_init_trading_db_is_idempotent():
    trading_storage.init_trading_db()
    trading_storage.init_trading_db()  # не должно падать при повторном вызове


def test_has_profile_false_when_not_saved():
    assert trading_storage.has_profile(111) is False


def test_save_and_get_profile_roundtrip():
    trading_storage.save_profile(
        chat_id=111,
        risk_percent=1.0,
        daily_loss_limit_percent=5.0,
        leverage=3.0,
        sl_method="atr",
        sl_fixed_percent=None,
        breakeven_after_tp=2,
        tp_split_preset="equal",
        max_concurrent_trades=3,
    )
    profile = trading_storage.get_profile(111)
    assert profile["chat_id"] == 111
    assert profile["risk_percent"] == 1.0
    assert profile["daily_loss_limit_percent"] == 5.0
    assert profile["leverage"] == 3.0
    assert profile["sl_method"] == "atr"
    assert profile["sl_fixed_percent"] is None
    assert profile["breakeven_after_tp"] == 2
    assert profile["tp_split_preset"] == "equal"
    assert profile["max_concurrent_trades"] == 3
    assert profile["trading_mode"] == "paper"
    assert profile["is_active"] == 1


def test_has_profile_true_after_save():
    trading_storage.save_profile(
        chat_id=222, risk_percent=1.0, daily_loss_limit_percent=5.0,
        leverage=3.0, sl_method="atr", sl_fixed_percent=None,
        breakeven_after_tp=2, tp_split_preset="equal", max_concurrent_trades=3,
    )
    assert trading_storage.has_profile(222) is True


def test_save_profile_upserts_existing():
    trading_storage.save_profile(
        chat_id=333, risk_percent=1.0, daily_loss_limit_percent=5.0,
        leverage=3.0, sl_method="atr", sl_fixed_percent=None,
        breakeven_after_tp=2, tp_split_preset="equal", max_concurrent_trades=3,
    )
    trading_storage.save_profile(
        chat_id=333, risk_percent=2.0, daily_loss_limit_percent=8.0,
        leverage=5.0, sl_method="fixed_percent", sl_fixed_percent=3.0,
        breakeven_after_tp=1, tp_split_preset="aggressive", max_concurrent_trades=3,
    )
    profile = trading_storage.get_profile(333)
    assert profile["risk_percent"] == 2.0
    assert profile["sl_method"] == "fixed_percent"
    assert profile["sl_fixed_percent"] == 3.0
    assert profile["tp_split_preset"] == "aggressive"


def test_get_api_credentials_none_when_not_saved():
    assert trading_storage.get_api_credentials(111, "binance") is None


def test_save_and_get_api_credentials_roundtrip_decrypts():
    trading_storage.save_api_credentials(111, "binance", "my-api-key", "my-api-secret")
    creds = trading_storage.get_api_credentials(111, "binance")
    assert creds["api_key"] == "my-api-key"
    assert creds["api_secret"] == "my-api-secret"


def test_api_credentials_stored_encrypted_at_rest():
    trading_storage.save_api_credentials(111, "binance", "my-api-key", "my-api-secret")
    with storage.get_conn() as conn:
        row = conn.execute(
            "SELECT api_key_encrypted, api_secret_encrypted FROM api_credentials "
            "WHERE chat_id = ? AND exchange = ?", (111, "binance")
        ).fetchone()
    assert "my-api-key" not in row["api_key_encrypted"]
    assert "my-api-secret" not in row["api_secret_encrypted"]


def test_api_credentials_separate_per_exchange():
    trading_storage.save_api_credentials(111, "binance", "binance-key", "binance-secret")
    trading_storage.save_api_credentials(111, "bybit", "bybit-key", "bybit-secret")
    binance_creds = trading_storage.get_api_credentials(111, "binance")
    bybit_creds = trading_storage.get_api_credentials(111, "bybit")
    assert binance_creds["api_key"] == "binance-key"
    assert bybit_creds["api_key"] == "bybit-key"
