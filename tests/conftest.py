import pytest
from cryptography.fernet import Fernet

import storage
import crypto_utils


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    """Каждый тест получает свою временную БД и валидный ключ шифрования."""
    db_path = str(tmp_path / "test_bot_state.db")
    monkeypatch.setattr(storage, "DB_PATH", db_path)
    monkeypatch.setattr(crypto_utils, "ENCRYPTION_KEY", Fernet.generate_key().decode())
    storage.init_db()
    import trading_storage  # таблицы автотрейдинга нужны любому коду, читающему позиции/события (напр. охлаждение пампов)
    trading_storage.init_trading_db()
    trading_storage.init_paper_trading_db()
    yield
