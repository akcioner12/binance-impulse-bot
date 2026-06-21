import os
from dotenv import load_dotenv

load_dotenv()

# Telegram
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")

# --- Логика импульса ---
IMPULSE_START_THRESHOLD = float(os.getenv("IMPULSE_START_THRESHOLD", "30.0"))   # % — порог первого сигнала
IMPULSE_STEP            = float(os.getenv("IMPULSE_STEP", "10.0"))              # % — шаг повторных сигналов
WINDOW_MINUTES          = int(os.getenv("WINDOW_MINUTES", "1440"))              # скользящее окно в минутах (1440 = 24ч)

# --- Фильтр рынка ---
MIN_DAILY_VOLUME_USDT = float(os.getenv("MIN_DAILY_VOLUME_USDT", "1500000"))    # $1.5M — отсекает мёртвые пары
SYMBOLS_REFRESH_SEC   = int(os.getenv("SYMBOLS_REFRESH_SEC", "3600"))           # как часто обновлять список пар

# --- Ежедневный отчёт топ-10 ---
DAILY_REPORT_HOUR_UTC   = int(os.getenv("DAILY_REPORT_HOUR_UTC", "17"))   # 20:00 Киев/Москва (UTC+3) = 17:00 UTC
DAILY_REPORT_MINUTE_UTC = int(os.getenv("DAILY_REPORT_MINUTE_UTC", "0"))
DAILY_REPORT_TOP_N      = int(os.getenv("DAILY_REPORT_TOP_N", "10"))

# --- Прочее ---
DB_PATH = os.getenv("DB_PATH", "bot_state.db")

BINANCE_FUTURES_REST = "https://fapi.binance.com"
BINANCE_FUTURES_WS   = "wss://fstream.binance.com"

BYBIT_FUTURES_REST = "https://api.bybit.com"
BYBIT_FUTURES_WS   = "wss://stream.bybit.com/v5/public/linear"

# Binance позволяет до 200 потоков на одно соединение, делаем чуть меньше для надёжности
SYMBOLS_PER_WS_CONNECTION = 150

# Bybit ограничивает число args в одной WS-подписке (обычно 10 в одном пакете подписки,
# но можно отправлять несколько пакетов подряд через одно соединение)
BYBIT_SYMBOLS_PER_SUBSCRIBE_BATCH = 10
