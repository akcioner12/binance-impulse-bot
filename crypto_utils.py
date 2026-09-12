"""
Шифрование API-ключей бирж (Binance/Bybit) для хранения в БД.

В отличие от MT5-пароля в tg-forex-signal-monitor (хранится открытым текстом),
здесь ключ даёт право реально торговать — шифруем at rest через Fernet.
"""

from cryptography.fernet import Fernet

from config import ENCRYPTION_KEY


def _get_fernet() -> Fernet:
    return Fernet(ENCRYPTION_KEY.encode())


def encrypt_secret(plaintext: str) -> str:
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt_secret(token: str) -> str:
    return _get_fernet().decrypt(token.encode()).decode()
