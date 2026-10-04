"""
Разовая авторизация в Telegram для слушателя стороннего канала сигналов.

ВАЖНО: запускать ОДИН РАЗ для создания файла сессии. После этого сессия
сохраняется на Railway Volume (/data) и повторный ввод кода не требуется.

Запускать на Railway (`railway run python auth_channel_session.py` или через
`railway ssh`), НЕ локально -- см. тот же комментарий про блокировку MTProto
в tg-forex-signal-monitor/auth_telethon.py.
"""
import asyncio

from telethon import TelegramClient

from config import TG_API_ID, TG_API_HASH, TG_CHANNEL_SESSION_PATH, CHANNEL_SIGNAL_SOURCE_ID


async def main():
    if not TG_API_ID or not TG_API_HASH:
        print("Ошибка: задай переменные окружения TG_API_ID и TG_API_HASH")
        return

    client = TelegramClient(TG_CHANNEL_SESSION_PATH, TG_API_ID, TG_API_HASH)
    await client.start()  # запросит номер телефона и код при первом запуске

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
