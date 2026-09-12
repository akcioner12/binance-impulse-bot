import pytest
from cryptography.fernet import Fernet

import crypto_utils


@pytest.fixture(autouse=True)
def valid_encryption_key(monkeypatch):
    monkeypatch.setattr(crypto_utils, "ENCRYPTION_KEY", Fernet.generate_key().decode())


def test_encrypt_then_decrypt_roundtrip():
    original = "super-secret-api-key-12345"
    token = crypto_utils.encrypt_secret(original)
    assert crypto_utils.decrypt_secret(token) == original


def test_encrypted_token_does_not_contain_plaintext():
    original = "super-secret-api-key-12345"
    token = crypto_utils.encrypt_secret(original)
    assert original not in token


def test_same_plaintext_encrypts_differently_each_time():
    original = "same-secret"
    token1 = crypto_utils.encrypt_secret(original)
    token2 = crypto_utils.encrypt_secret(original)
    assert token1 != token2  # Fernet добавляет случайный IV — детерминизма быть не должно


def test_decrypt_with_wrong_key_fails():
    token = crypto_utils.encrypt_secret("secret")
    crypto_utils.ENCRYPTION_KEY = Fernet.generate_key().decode()
    from cryptography.fernet import InvalidToken
    with pytest.raises(InvalidToken):
        crypto_utils.decrypt_secret(token)
