"""
Разовая авторизация в Telegram для слушателя стороннего канала сигналов --
вариант через QR-код (вместо номера телефона/SMS-кода), на случай если код
не доходит.

ВАЖНО: запускать ОДИН РАЗ (railway ssh), создаёт тот же файл сессии, что и
auth_channel_session.py -- если один из вариантов авторизации прошёл успешно,
второй запускать не нужно.

Как пользоваться: запусти, отсканируй выведенный в терминале QR-код
приложением Telegram (Настройки -> Устройства -> Привязать устройство).
QR обновляется автоматически каждые ~30 секунд, пока не будет отсканирован.
"""
import asyncio

import qrcode
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError

from config import TG_API_ID, TG_API_HASH, TG_CHANNEL_SESSION_PATH, CHANNEL_SIGNAL_SOURCE_ID


async def main():
    if not TG_API_ID or not TG_API_HASH:
        print("Ошибка: задай переменные окружения TG_API_ID и TG_API_HASH")
        return

    client = TelegramClient(TG_CHANNEL_SESSION_PATH, TG_API_ID, TG_API_HASH)
    await client.connect()

    if await client.is_user_authorized():
        print("Уже авторизован, QR не нужен.")
    else:
        qr_login = await client.qr_login()
        while True:
            print("\nОтсканируй QR-код в Telegram: Настройки -> Устройства -> Привязать устройство\n")
            qr = qrcode.QRCode()
            qr.add_data(qr_login.url)
            qr.print_ascii(invert=True)
            try:
                await qr_login.wait(timeout=30)
                break
            except asyncio.TimeoutError:
                print("QR истёк, обновляю...")
                await qr_login.recreate()
            except SessionPasswordNeededError:
                pw = input("На аккаунте включена двухфакторная аутентификация, введи облачный пароль: ")
                await client.sign_in(password=pw)
                break

    me = await client.get_me()
    print(f"\nАвторизация успешна: {me.first_name} (@{me.username}), id={me.id}")
    print(f"Файл сессии создан: {TG_CHANNEL_SESSION_PATH}.session")

    try:
        entity = await client.get_entity(CHANNEL_SIGNAL_SOURCE_ID)
        print(f"\nКанал найден: {getattr(entity, 'title', entity)} (id={CHANNEL_SIGNAL_SOURCE_ID})")
    except Exception as e:
        print(f"\nВНИМАНИЕ: не удалось найти канал {CHANNEL_SIGNAL_SOURCE_ID}: {e}")
        print("Проверь, что аккаунт, под которым авторизован, состоит в этом канале.")

    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
