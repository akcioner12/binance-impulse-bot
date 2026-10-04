# Исполнение сигналов стороннего Telegram-канала -- Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Бот входит в paper-trading сделку по сигналу из внешнего Telegram-канала (тикер +
направление), используя уже существующий движок автотрейдинга (ATR-стоп, сетка TP1-3 +
трейлинг TP4, риск-проценты по направлению) -- без изменения самой торговой логики.

**Architecture:** Новый Telethon-листенер (пользовательская сессия) слушает канал
`-1002487960768` в том же процессе, что и основной бот. Распознанный текст сообщения проходит
через чистый парсер (2 формата канала), результат (тикер + направление) передаётся в новую
функцию `live_trading.handle_channel_signal`, которая резолвит биржу, проходит те же проверки,
что и органический сигнал, и вызывает уже существующий `execute_setup(classification="reversal")`
-- тот же путь входа, что и у собственного детектора импульсов.

**Tech Stack:** Python 3.13, aiohttp, SQLite (`trading_storage.py`/`storage.py`), Telethon
(новая зависимость), pytest + pytest-asyncio, Railway (существующий Volume `/data`).

**Spec:** `docs/superpowers/specs/2026-10-04-channel-signal-autotrading-design.md`

## Global Constraints

- Только paper trading -- никаких изменений в сторону реальных денег.
- Исполняются только типы сообщений A и B из спеки; тип C (спот) не парсится и не исполняется.
- Выходы из позиции -- исключительно через существующий движок (ATR-стоп, TP1-3, трейлинг
  TP4); сообщения канала о закрытии/отмене не парсятся и не нужны.
- Конфликт по монете (уже открыта/ожидает позиция от любого источника) -- сигнал пропускается,
  параллельный слот не открывается.
- Биржа: Binance в приоритете, Bybit как fallback, если монеты нет на Binance.
- Направление канала -> направление детектора: SHORT/шорт -> `direction="up"` (риск 1%, как у
  пампа), LONG/лонг -> `direction="down"` (риск 4%, как у дампа). Никаких новых констант риска.
- Существующий Railway Volume (`RAILWAY_VOLUME_MOUNT_PATH=/data`) уже смонтирован на этом
  сервисе -- новый Volume создавать не нужно, файл Telethon-сессии кладётся туда же.

## Review Focus

- Сообщение типа C ("СДЕЛКА НА СПОТ", `UAI Long беру от текущих...`) не должно случайно
  распознаться как сигнал типа B -- структурно похоже (тикер сразу за словом направления), но
  без анкерной фразы "заходим в позицию"/"давай ... на". Тест на это — Task 1.
- Тикер, которого нет ни на Binance, ни на Bybit фьючерсах -- `handle_channel_signal` должен
  тихо пропустить сигнал (вернуть `None`), а не упасть с ошибкой сети/KeyError. Тест — Task 3.
- По монете уже есть открытая/ожидающая позиция (от своего детектора ИЛИ от другого сигнала
  канала) -- сигнал пропускается, не открывается второй параллельный слот. Тест — Task 3.
- ATR недоступен (мало свечей, например у совсем нового листинга) -- `handle_channel_signal`
  должен вернуть `None`, а не упасть на `None * ATR_MULT`. Тест — Task 3.
- Обрыв Telethon-соединения (сеть, протухшая сессия) не должен ронять остальные задачи
  `asyncio.gather` в `main.py` (торговый цикл, веб-сервер, отчёты) -- нужен внутренний
  retry-цикл. Тест — Task 4 (ручная проверка после деплоя, см. Task 7).

---

## File Structure

**Создать:**
- `channel_signal_parser.py` -- чистый парсер текста сообщения в `(ticker, direction)`.
- `channel_signal_listener.py` -- Telethon-клиент + тестируемый `on_channel_message()`.
- `auth_channel_session.py` -- разовый скрипт авторизации (адаптация
  `tg-forex-signal-monitor/auth_telethon.py`).
- `tests/test_channel_signal_parser.py`
- `tests/test_live_trading_channel_signal.py`
- `tests/test_channel_signal_listener.py`
- `tests/test_main_channel_signal_wiring.py`

**Изменить:**
- `trading_storage.py` -- колонка `source` в `trade_signals`, параметр `source` в
  `create_trade_signal`.
- `live_trading.py` -- новая функция `handle_channel_signal` + приватный хелпер
  `_resolve_channel_signal_exchange`.
- `config.py` -- новые константы `CHANNEL_SIGNAL_SOURCE_ID`, `TG_API_ID`, `TG_API_HASH`,
  `TG_CHANNEL_SESSION_PATH`.
- `requirements.txt` -- добавить `telethon`.
- `main.py` -- подключить `channel_signal_listener.run_channel_signal_listener()` в
  `asyncio.gather(...)`.
- `docs/LOGIC_CHANGELOG.md` -- запись о новом источнике сигналов.

---

### Task 1: Парсер сообщений канала

**Files:**
- Create: `channel_signal_parser.py`
- Test: `tests/test_channel_signal_parser.py`

**Interfaces:**
- Produces: `ParsedChannelSignal(ticker: str, direction: str)` dataclass (`direction` -- `"long"`
  или `"short"`, терминология канала); `parse_channel_signal(text: str | None) ->
  ParsedChannelSignal | None`.

- [ ] **Step 1: Написать падающие тесты на все 9 реальных примеров + отрицательные кейсы**

```python
# tests/test_channel_signal_parser.py
from channel_signal_parser import parse_channel_signal, ParsedChannelSignal


def test_type_a_short():
    text = (
        "ЗАХОДИМ В МАНИПУЛЯЦИЮ\n\n"
        "XAI SHORT  - опасный вид манипуляций, когда внутри нисходящего канала формируют такие пампы\n\n"
        "Пришли к сопротивлению\n"
        "И жду быстрый откат, если пойдем выше предыдущего максимума, то лучше стопиться\n\n"
        "Соблюдаем риски и не котлетим позицию!"
    )
    assert parse_channel_signal(text) == ParsedChannelSignal(ticker="XAI", direction="short")


def test_type_a_long():
    text = (
        "ЗАХОДИМ В МАНИПУЛЯЦИЮ\n\n"
        "US LONG  - хочу попробовать локальную позицию в Лонг на откат после снижения\n\n"
        "Если будет четкий закреп выше 0.03$, то возможен полноценный памп на 30-40% чистого\n\n"
        "Соблюдаем риски и не котлетим позицию!"
    )
    assert parse_channel_signal(text) == ParsedChannelSignal(ticker="US", direction="long")


def test_type_a_remaining_four_tickers():
    cases = [
        ("PHA SHORT  - монета часто склонна к подобным манипуляциям", "PHA", "short"),
        ("ARK SHORT  - закрылась 12ч свеча, можно взять откат локальный", "ARK", "short"),
        ("BTW SHORT  - очень волатильная и нестабильная монета", "BTW", "short"),
        ("CAP SHORT  - больше среднесрочная позиция и не стоит ждать", "CAP", "short"),
    ]
    for line, ticker, direction in cases:
        text = f"ЗАХОДИМ В МАНИПУЛЯЦИЮ\n\n{line}\n\nСоблюдаем риски и не котлетим позицию!"
        assert parse_channel_signal(text) == ParsedChannelSignal(ticker=ticker, direction=direction), line


def test_type_b_ticker_then_direction_word():
    text = (
        "Так, заходим в позицию MARSCOIN short\n\n"
        "Плечо: 20.0\nМаржа: 300$\nТейк: 0.1455$\n\n"
        "Я уже в позиции сижу, так что давай в темпе заходи"
    )
    assert parse_channel_signal(text) == ParsedChannelSignal(ticker="MARSCOIN", direction="short")


def test_type_b_ticker_then_direction_word_uppercase_long():
    text = (
        "заходим в позицию NIGHT LONG\n\n"
        "Плечо: 30.0\nМаржа: 1000$\nТейк: 0.375$\n\n"
        "Точно так же риск повышен, но надо умножать депозит дальше"
    )
    assert parse_channel_signal(text) == ParsedChannelSignal(ticker="NIGHT", direction="long")


def test_type_b_direction_word_then_ticker():
    text = (
        "Давай шорт на CELO\n\n"
        "Тейк: 0.102$\nПлечо: 50x\nМаржа: 250$\n\n"
        "Риск берем уже меньше, так как депозит больше стал"
    )
    assert parse_channel_signal(text) == ParsedChannelSignal(ticker="CELO", direction="short")


def test_type_c_spot_not_parsed():
    """
    Критично: "UAI Long беру от текущих..." структурно похож на тип B (тикер сразу
    перед словом направления), но БЕЗ анкерной фразы "заходим в позицию" -- не
    должен распознаваться (спот не входит в область фичи, см. спеку 2026-10-04).
    """
    text = (
        "СДЕЛКА НА СПОТ\n\n"
        "UAI Long беру от текущих, огромный потенциал в короткие сроки достичь цели 100% чистого и более\n\n"
        "И взяла с не большим плечом эту же монету на фьючерсы!"
    )
    assert parse_channel_signal(text) is None


def test_none_for_unrelated_chatter():
    assert parse_channel_signal("Всем привет, как дела?") is None


def test_none_for_empty_or_missing_text():
    assert parse_channel_signal("") is None
    assert parse_channel_signal(None) is None


def test_none_when_header_present_but_next_line_unrecognized():
    text = "ЗАХОДИМ В МАНИПУЛЯЦИЮ\n\nвсё сложно, без тикера тут"
    assert parse_channel_signal(text) is None
```

- [ ] **Step 2: Запустить тесты, убедиться что падают с ImportError/ModuleNotFoundError**

Run: `python -m pytest tests/test_channel_signal_parser.py -v`
Expected: FAIL -- `ModuleNotFoundError: No module named 'channel_signal_parser'`

- [ ] **Step 3: Реализовать парсер**

```python
# channel_signal_parser.py
"""
Парсер текста сигналов стороннего Telegram-канала (-1002487960768, см. спеку
docs/superpowers/specs/2026-10-04-channel-signal-autotrading-design.md).

Два распознаваемых формата:
- Тип A: заголовок "ЗАХОДИМ В МАНИПУЛЯЦИЮ", на следующей строке "<ТИКЕР> <SHORT|LONG>".
- Тип B (пересланные от другого автора): "заходим в позицию <ТИКЕР> <long|short>"
  ИЛИ "давай <шорт|лонг> на <ТИКЕР>" -- порядок слов варьируется у источника.

Всё остальное (включая тип C -- спотовые рекомендации) возвращает None.
"""
import re
from dataclasses import dataclass

_HEADER_RE = re.compile(r"заходим\s+в\s+манипуляцию", re.IGNORECASE)
_TICKER_DIRECTION_RE = re.compile(r"^([A-Za-z0-9]{2,10})\s+(SHORT|LONG|ШОРТ|ЛОНГ)\b", re.IGNORECASE)
_TYPE_B_TICKER_FIRST_RE = re.compile(
    r"заходим\s+в\s+позицию\s+([A-Za-z0-9]{2,10})\s+(long|short|лонг|шорт)\b", re.IGNORECASE
)
_TYPE_B_DIRECTION_FIRST_RE = re.compile(
    r"давай\s+(шорт|лонг)\s+на\s+([A-Za-z0-9]{2,10})\b", re.IGNORECASE
)

_DIRECTION_NORMALIZE = {
    "short": "short", "шорт": "short",
    "long": "long", "лонг": "long",
}


@dataclass
class ParsedChannelSignal:
    ticker: str
    direction: str  # "long" | "short"


def parse_channel_signal(text: str | None) -> ParsedChannelSignal | None:
    if not text:
        return None

    header_match = _HEADER_RE.search(text)
    if header_match:
        rest = text[header_match.end():].lstrip("\n\r ")
        for line in rest.splitlines():
            line = line.strip()
            if not line:
                continue
            m = _TICKER_DIRECTION_RE.match(line)
            if m:
                return ParsedChannelSignal(
                    ticker=m.group(1).upper(),
                    direction=_DIRECTION_NORMALIZE[m.group(2).lower()],
                )
            break  # первая непустая строка не подошла -- формат неизвестен, в тип B не пробуем

    m = _TYPE_B_TICKER_FIRST_RE.search(text)
    if m:
        return ParsedChannelSignal(ticker=m.group(1).upper(), direction=_DIRECTION_NORMALIZE[m.group(2).lower()])

    m = _TYPE_B_DIRECTION_FIRST_RE.search(text)
    if m:
        return ParsedChannelSignal(ticker=m.group(2).upper(), direction=_DIRECTION_NORMALIZE[m.group(1).lower()])

    return None
```

- [ ] **Step 4: Запустить тесты, убедиться что все проходят**

Run: `python -m pytest tests/test_channel_signal_parser.py -v`
Expected: PASS (все тесты)

- [ ] **Step 5: Commit**

```bash
git add channel_signal_parser.py tests/test_channel_signal_parser.py
git commit -m "feat: парсер сигналов стороннего Telegram-канала (типы A/B)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 2: Колонка `source` в `trade_signals`

**Files:**
- Modify: `trading_storage.py:123-150` (миграция колонок), `trading_storage.py:179-190`
  (`CREATE TABLE trade_signals`), `trading_storage.py:416-424` (`create_trade_signal`)
- Test: `tests/test_trading_storage_paper.py`

**Interfaces:**
- Produces: `trading_storage.create_trade_signal(chat_id, symbol, exchange, impulse_direction,
  classification, source: str = "analyzer") -> int`. Существующие вызовы без `source`
  продолжают работать без изменений (значение по умолчанию `"analyzer"`).

- [ ] **Step 1: Написать падающие тесты**

Добавить в конец `tests/test_trading_storage_paper.py`:

```python
import storage


def test_create_trade_signal_defaults_source_to_analyzer():
    signal_id = trading_storage.create_trade_signal(
        chat_id=111, symbol="BTCUSDT", exchange="Binance",
        impulse_direction="up", classification="reversal",
    )
    row = trading_storage.get_trade_signal(signal_id)
    assert row["source"] == "analyzer"


def test_create_trade_signal_accepts_explicit_source():
    signal_id = trading_storage.create_trade_signal(
        chat_id=111, symbol="XAIUSDT", exchange="Binance",
        impulse_direction="up", classification="reversal", source="channel",
    )
    row = trading_storage.get_trade_signal(signal_id)
    assert row["source"] == "channel"


def test_init_paper_trading_db_adds_source_column_to_pre_existing_trade_signals_table():
    """Защита уже развёрнутой в проде БД -- CREATE TABLE IF NOT EXISTS сам по себе
    не добавит новую колонку на таблицу, которая уже существует без неё."""
    with storage.get_conn() as conn:
        conn.execute("DROP TABLE IF EXISTS trade_signals")
        conn.execute("""
            CREATE TABLE trade_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                symbol TEXT NOT NULL,
                exchange TEXT NOT NULL,
                impulse_direction TEXT NOT NULL,
                classification TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()

    trading_storage.init_paper_trading_db()

    with storage.get_conn() as conn:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(trade_signals)")}
    assert "source" in columns
```

- [ ] **Step 2: Запустить тесты, убедиться что падают**

Run: `python -m pytest tests/test_trading_storage_paper.py -v -k source`
Expected: FAIL -- `TypeError: create_trade_signal() got an unexpected keyword argument 'source'`
(первые два теста), затем после их фикса -- третий тест упадёт на `assert "source" in columns`.

- [ ] **Step 3: Добавить миграцию колонки и параметр `source`**

В `trading_storage.py`, рядом с `_ensure_position_recovery_columns` (после неё, перед
`init_paper_trading_db`):

```python
_TRADE_SIGNAL_COLUMNS = {
    "source": "TEXT NOT NULL DEFAULT 'analyzer'",
}


def _ensure_trade_signal_columns(conn):
    """Аналогично _ensure_position_recovery_columns -- добавляет колонку source
    на уже развёрнутой в проде БД, где таблица trade_signals создана раньше этой фичи."""
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(trade_signals)")}
    for column, sql_type in _TRADE_SIGNAL_COLUMNS.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE trade_signals ADD COLUMN {column} {sql_type}")
```

В `init_paper_trading_db`, сразу после блока `CREATE TABLE IF NOT EXISTS trade_signals (...)`
(после закрывающего `""")`, перед `conn.execute("""CREATE TABLE IF NOT EXISTS trade_events`):

```python
        _ensure_trade_signal_columns(conn)
```

Обновить `create_trade_signal`:

```python
def create_trade_signal(
    chat_id: int, symbol: str, exchange: str, impulse_direction: str, classification: str,
    source: str = "analyzer",
) -> int:
    with get_conn() as conn:
        cursor = conn.execute("""
            INSERT INTO trade_signals (chat_id, symbol, exchange, impulse_direction, classification, source)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (chat_id, symbol, exchange, impulse_direction, classification, source))
        conn.commit()
        return cursor.lastrowid
```

- [ ] **Step 4: Запустить тесты, убедиться что все проходят**

Run: `python -m pytest tests/test_trading_storage_paper.py -v`
Expected: PASS (все тесты, включая уже существовавшие -- регрессий нет)

- [ ] **Step 5: Запустить полный набор тестов проекта (защита от регрессии в других вызовах create_trade_signal)**

Run: `python -m pytest -q`
Expected: PASS (все существующие тесты, т.к. `source` опционален с дефолтом)

- [ ] **Step 6: Commit**

```bash
git add trading_storage.py tests/test_trading_storage_paper.py
git commit -m "feat: колонка source в trade_signals -- различать сигналы детектора и канала

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 3: `live_trading.handle_channel_signal` -- интеграция с существующим движком

**Files:**
- Modify: `live_trading.py` (новый код в конце файла, после существующих функций)
- Test: `tests/test_live_trading_channel_signal.py`

**Interfaces:**
- Consumes: `trading_storage.get_profile`, `trading_storage.get_open_positions`,
  `trading_storage.create_trade_signal(..., source=...)` (Task 2), `market_data.fetch_klines`,
  `indicators.atr`, `magnet_levels_module.find_magnet_levels`, `execute_setup` (существующая,
  `live_trading.py:286`), `SYMBOL_BLACKLIST`, `_pending_setups`/`_open_positions`/
  `_reserved_symbols` (существующие module-level dict/set).
- Produces: `handle_channel_signal(session, chat_id: int, ticker: str, channel_direction: str) ->
  dict | None`.

- [ ] **Step 1: Написать падающие тесты (guard-проверки)**

```python
# tests/test_live_trading_channel_signal.py
import pytest
from unittest.mock import AsyncMock, patch

import live_trading


def setup_function():
    live_trading._pending_setups.clear()
    live_trading._open_positions.clear()
    live_trading._reserved_symbols.clear()


PROFILE = {"is_active": 1, "max_concurrent_trades": 3, "sl_method": "atr", "sl_fixed_percent": 2.0}


@pytest.mark.asyncio
async def test_handle_channel_signal_none_for_unknown_direction_word():
    result = await live_trading.handle_channel_signal(
        session=None, chat_id=111, ticker="XAI", channel_direction="moon",
    )
    assert result is None


@pytest.mark.asyncio
async def test_handle_channel_signal_none_when_no_profile():
    with patch("live_trading.trading_storage.get_profile", return_value=None):
        result = await live_trading.handle_channel_signal(
            session=None, chat_id=111, ticker="XAI", channel_direction="short",
        )
    assert result is None


@pytest.mark.asyncio
async def test_handle_channel_signal_none_when_profile_inactive():
    with patch("live_trading.trading_storage.get_profile", return_value={"is_active": 0}):
        result = await live_trading.handle_channel_signal(
            session=None, chat_id=111, ticker="XAI", channel_direction="short",
        )
    assert result is None


@pytest.mark.asyncio
async def test_handle_channel_signal_none_when_symbol_blacklisted():
    with patch("live_trading.trading_storage.get_profile", return_value=PROFILE):
        result = await live_trading.handle_channel_signal(
            session=None, chat_id=111, ticker="CLO", channel_direction="short",
        )
    assert result is None


@pytest.mark.asyncio
async def test_handle_channel_signal_none_when_symbol_already_pending():
    live_trading._pending_setups["XAIUSDT"] = {"dummy": True}
    with patch("live_trading.trading_storage.get_profile", return_value=PROFILE):
        result = await live_trading.handle_channel_signal(
            session=None, chat_id=111, ticker="XAI", channel_direction="short",
        )
    assert result is None


@pytest.mark.asyncio
async def test_handle_channel_signal_none_when_symbol_already_open():
    live_trading._open_positions["XAIUSDT"] = {"dummy": True}
    with patch("live_trading.trading_storage.get_profile", return_value=PROFILE):
        result = await live_trading.handle_channel_signal(
            session=None, chat_id=111, ticker="XAI", channel_direction="short",
        )
    assert result is None


@pytest.mark.asyncio
async def test_handle_channel_signal_none_when_at_max_concurrent_trades():
    profile = {**PROFILE, "max_concurrent_trades": 1}
    with patch("live_trading.trading_storage.get_profile", return_value=profile), \
         patch("live_trading.trading_storage.get_open_positions", return_value=[{"id": 1}]):
        result = await live_trading.handle_channel_signal(
            session=None, chat_id=111, ticker="XAI", channel_direction="short",
        )
    assert result is None


@pytest.mark.asyncio
async def test_handle_channel_signal_none_when_symbol_not_found_on_either_exchange():
    with patch("live_trading.trading_storage.get_profile", return_value=PROFILE), \
         patch("live_trading.trading_storage.get_open_positions", return_value=[]), \
         patch("live_trading.market_data.fetch_klines", new=AsyncMock(return_value=[])):
        result = await live_trading.handle_channel_signal(
            session=None, chat_id=111, ticker="NOPE", channel_direction="short",
        )
    assert result is None
    assert "NOPEUSDT" not in live_trading._reserved_symbols  # слот освобождён
```

- [ ] **Step 2: Запустить тесты, убедиться что падают**

Run: `python -m pytest tests/test_live_trading_channel_signal.py -v`
Expected: FAIL -- `AttributeError: module 'live_trading' has no attribute 'handle_channel_signal'`

- [ ] **Step 3: Реализовать `handle_channel_signal` (guard-часть, без исполнения)**

Добавить в конец `live_trading.py`:

```python
CHANNEL_DIRECTION_TO_DETECTOR_DIRECTION = {
    "short": "up", "шорт": "up",
    "long": "down", "лонг": "down",
}


async def _resolve_channel_signal_exchange(session, symbol: str) -> str | None:
    """
    Резолвит биржу для сигнала стороннего канала без полного списка пар (в отличие
    от собственного детектора, который уже подписан на все торгуемые символы) --
    один лёгкий запрос свечи на каждую биржу по очереди, Binance в приоритете.
    """
    for exchange in ("Binance", "Bybit"):
        try:
            candles = await market_data.fetch_klines(session, exchange, symbol, "1h", limit=1)
        except Exception:
            continue
        if candles:
            return exchange
    return None


async def handle_channel_signal(session, chat_id: int, ticker: str, channel_direction: str) -> dict | None:
    """
    Вызывается из channel_signal_listener.on_channel_message при распознанном
    сигнале стороннего Telegram-канала (см. docs/superpowers/specs/2026-10-04-
    channel-signal-autotrading-design.md). SHORT канала -> фейд пампа
    (direction="up", риск как у пампа), LONG -> фейд дампа (direction="down",
    риск как у дампа) -- исполнение идёт через тот же execute_setup(
    classification="reversal", ...), что и органические сигналы: стоп/TP-сетка/
    трейлинг не меняются.
    """
    direction = CHANNEL_DIRECTION_TO_DETECTOR_DIRECTION.get(channel_direction.lower())
    if direction is None:
        return None

    symbol = f"{ticker.upper()}USDT"

    profile = trading_storage.get_profile(chat_id)
    if profile is None or not profile["is_active"]:
        return None
    if symbol in SYMBOL_BLACKLIST:
        return None
    if symbol in _pending_setups or symbol in _open_positions or symbol in _reserved_symbols:
        return None
    if len(trading_storage.get_open_positions(chat_id)) + len(_reserved_symbols) >= profile["max_concurrent_trades"]:
        return None
    _reserved_symbols.add(symbol)

    try:
        exchange = await _resolve_channel_signal_exchange(session, symbol)
        if exchange is None:
            logger.info(f"Сигнал канала [{symbol}]: монета не найдена на Binance/Bybit фьючерсах, пропуск")
            return None
        return None  # TODO (Task 3 Step 8): исполнение добавится следующим шагом
    finally:
        _reserved_symbols.discard(symbol)
```

- [ ] **Step 4: Запустить тесты, убедиться что все проходят**

Run: `python -m pytest tests/test_live_trading_channel_signal.py -v`
Expected: PASS (все 8 тестов)

- [ ] **Step 5: Commit (промежуточный -- guard-логика без исполнения)**

```bash
git add live_trading.py tests/test_live_trading_channel_signal.py
git commit -m "feat: handle_channel_signal -- проверки доступа (профиль/чёрный список/конфликт/биржа)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

- [ ] **Step 6: Написать падающие тесты на исполнение (happy path + ATR-guard)**

Добавить в `tests/test_live_trading_channel_signal.py`:

```python
def _candle(close, high=None, low=None):
    return {"open_time": 0, "close": close, "high": high if high is not None else close, "low": low if low is not None else close}


def _klines_with_atr(n=60, base=1.0):
    """n свечей с небольшим разбросом high/low -- достаточно для atr(period=14) не-None."""
    out = []
    price = base
    for i in range(n):
        high = price * 1.01
        low = price * 0.99
        out.append({"open_time": i, "close": price, "high": high, "low": low})
        price *= 1.001
    return out


@pytest.mark.asyncio
async def test_handle_channel_signal_none_when_atr_unavailable():
    with patch("live_trading.trading_storage.get_profile", return_value=PROFILE), \
         patch("live_trading.trading_storage.get_open_positions", return_value=[]), \
         patch("live_trading.market_data.fetch_klines", new=AsyncMock(side_effect=[
             [_candle(1.0)],   # _resolve_channel_signal_exchange: Binance -- найдено
             [_candle(1.0)] * 2,  # candles_15m: слишком мало для ATR(14)
             [_candle(1.0)] * 2,  # candles_1h: слишком мало для ATR(14)
         ])):
        result = await live_trading.handle_channel_signal(
            session=None, chat_id=111, ticker="XAI", channel_direction="short",
        )
    assert result is None


@pytest.mark.asyncio
async def test_handle_channel_signal_short_maps_to_pump_risk_and_executes():
    klines_1h = _klines_with_atr(n=24)
    klines_15m = _klines_with_atr(n=50)
    with patch("live_trading.trading_storage.get_profile", return_value=PROFILE), \
         patch("live_trading.trading_storage.get_open_positions", return_value=[]), \
         patch("live_trading.market_data.fetch_klines", new=AsyncMock(side_effect=[
             [klines_1h[-1]],  # резолв биржи -- Binance
             klines_15m, klines_1h,  # ATR
             [], [],  # daily/weekly для magnet_levels
         ])), \
         patch("live_trading.magnet_levels_module.find_magnet_levels", return_value=[]), \
         patch("live_trading.trading_storage.create_trade_signal", return_value=99) as mock_create_signal, \
         patch("live_trading.send_text", new=AsyncMock()), \
         patch("live_trading.execute_setup", new=AsyncMock(return_value={"classification": "reversal", "signal_id": 99})) as mock_execute:
        result = await live_trading.handle_channel_signal(
            session=None, chat_id=111, ticker="XAI", channel_direction="short",
        )

    assert result == {"classification": "reversal", "signal_id": 99}
    mock_create_signal.assert_called_once()
    assert mock_create_signal.call_args.kwargs["source"] == "channel"
    assert mock_create_signal.call_args.kwargs["impulse_direction"] == "up"
    mock_execute.assert_called_once()
    assert mock_execute.call_args.args[4] == "up"  # direction
    assert mock_execute.call_args.args[5] == "reversal"  # classification


@pytest.mark.asyncio
async def test_handle_channel_signal_long_maps_to_dump_risk_direction():
    klines_1h = _klines_with_atr(n=24)
    klines_15m = _klines_with_atr(n=50)
    with patch("live_trading.trading_storage.get_profile", return_value=PROFILE), \
         patch("live_trading.trading_storage.get_open_positions", return_value=[]), \
         patch("live_trading.market_data.fetch_klines", new=AsyncMock(side_effect=[
             [klines_1h[-1]],
             klines_15m, klines_1h,
             [], [],
         ])), \
         patch("live_trading.magnet_levels_module.find_magnet_levels", return_value=[]), \
         patch("live_trading.trading_storage.create_trade_signal", return_value=100), \
         patch("live_trading.send_text", new=AsyncMock()), \
         patch("live_trading.execute_setup", new=AsyncMock(return_value={"classification": "reversal", "signal_id": 100})) as mock_execute:
        result = await live_trading.handle_channel_signal(
            session=None, chat_id=111, ticker="CELO", channel_direction="long",
        )

    assert result is not None
    assert mock_execute.call_args.args[4] == "down"  # direction


@pytest.mark.asyncio
async def test_handle_channel_signal_resolves_bybit_when_not_on_binance():
    klines_1h = _klines_with_atr(n=24)
    klines_15m = _klines_with_atr(n=50)
    with patch("live_trading.trading_storage.get_profile", return_value=PROFILE), \
         patch("live_trading.trading_storage.get_open_positions", return_value=[]), \
         patch("live_trading.market_data.fetch_klines", new=AsyncMock(side_effect=[
             [],              # Binance -- не найдено
             [klines_1h[-1]],  # Bybit -- найдено
             klines_15m, klines_1h,
             [], [],
         ])), \
         patch("live_trading.magnet_levels_module.find_magnet_levels", return_value=[]), \
         patch("live_trading.trading_storage.create_trade_signal", return_value=101), \
         patch("live_trading.send_text", new=AsyncMock()), \
         patch("live_trading.execute_setup", new=AsyncMock(return_value={"classification": "reversal", "signal_id": 101})) as mock_execute:
        result = await live_trading.handle_channel_signal(
            session=None, chat_id=111, ticker="NIGHT", channel_direction="long",
        )

    assert result is not None
    assert mock_execute.call_args.args[3] == "Bybit"  # exchange
```

- [ ] **Step 7: Запустить тесты, убедиться что новые 4 падают (старые 8 всё ещё проходят)**

Run: `python -m pytest tests/test_live_trading_channel_signal.py -v`
Expected: 4 новых FAIL (atr/short/long/bybit), 8 старых PASS

- [ ] **Step 8: Дополнить `handle_channel_signal` -- ATR, magnet_levels, создание сигнала, вызов `execute_setup`**

Заменить `return None  # TODO ...` из Step 3 на:

```python
        candles_15m = await market_data.fetch_klines(session, exchange, symbol, "15m", limit=50)
        candles_1h = await market_data.fetch_klines(session, exchange, symbol, "1h", limit=24)
        if not candles_1h:
            return None
        current_price = candles_1h[-1]["close"]

        atr_15m_values = indicators.atr(candles_15m, period=14)
        atr_1h_values = indicators.atr(candles_1h, period=14)
        atr_15m = atr_15m_values[-1] if atr_15m_values else None
        atr_1h = atr_1h_values[-1] if atr_1h_values else None
        if not atr_15m or not atr_1h:
            return None

        daily_candles = await market_data.fetch_klines(session, exchange, symbol, "1d", limit=90)
        weekly_candles = await market_data.fetch_klines(session, exchange, symbol, "1w", limit=52)
        magnet_levels = magnet_levels_module.find_magnet_levels(daily_candles, weekly_candles, current_price, direction)

        signal_id = trading_storage.create_trade_signal(
            chat_id=chat_id, symbol=symbol, exchange=exchange,
            impulse_direction=direction, classification="reversal", source="channel",
        )

        direction_label = "🔴 SHORT" if direction == "up" else "🟢 LONG"
        await send_text(
            session, chat_id,
            f"📡 Сигнал из канала: *{ticker.upper()}* {direction_label} — вхожу по нашей стратегии...",
        )

        analysis = {"atr_1h": atr_1h, "atr_15m": atr_15m, "magnet_levels": magnet_levels}
        return await execute_setup(
            session, chat_id, symbol, exchange, direction, "reversal",
            current_price, current_price, profile, analysis, signal_id,
        )
```

- [ ] **Step 9: Запустить тесты, убедиться что все проходят**

Run: `python -m pytest tests/test_live_trading_channel_signal.py -v`
Expected: PASS (все 12 тестов)

- [ ] **Step 10: Запустить полный набор тестов проекта**

Run: `python -m pytest -q`
Expected: PASS (регрессий нет -- `handle_new_impulse` и остальной код не менялись)

- [ ] **Step 11: Commit**

```bash
git add live_trading.py tests/test_live_trading_channel_signal.py
git commit -m "feat: handle_channel_signal исполняет сигнал через существующий execute_setup

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 4: Telethon-листенер

**Files:**
- Create: `channel_signal_listener.py`
- Modify: `config.py` (новые константы), `requirements.txt` (telethon)
- Test: `tests/test_channel_signal_listener.py`

**Interfaces:**
- Consumes: `channel_signal_parser.parse_channel_signal` (Task 1),
  `live_trading.handle_channel_signal` (Task 3), `config.ADMIN_CHAT_ID`,
  `config.CHANNEL_SIGNAL_SOURCE_ID`, `config.TG_API_ID`, `config.TG_API_HASH`,
  `config.TG_CHANNEL_SESSION_PATH`.
- Produces: `on_channel_message(session, text: str | None) -> dict | None` (тестируемое ядро,
  без Telethon), `run_channel_signal_listener() -> None` (бесконечная задача для
  `asyncio.gather`, Telethon-обвязка -- не юнит-тестируется).

- [ ] **Step 1: Добавить зависимость и константы**

`requirements.txt` -- добавить строку:
```
telethon>=1.36.0
```

`config.py` -- добавить в конец файла:
```python
# --- Сигналы стороннего Telegram-канала (см. docs/superpowers/specs/2026-10-04-...) ---
CHANNEL_SIGNAL_SOURCE_ID = int(os.getenv("CHANNEL_SIGNAL_SOURCE_ID", "-1002487960768"))
TG_API_ID = int(os.getenv("TG_API_ID", "0"))
TG_API_HASH = os.getenv("TG_API_HASH", "")
TG_CHANNEL_SESSION_PATH = os.getenv("TG_CHANNEL_SESSION_PATH", "/data/channel_signal")
```

Run: `pip install telethon` (локально, чтобы импорт работал при тестах следующего шага)

- [ ] **Step 2: Написать падающий тест на `on_channel_message`**

```python
# tests/test_channel_signal_listener.py
import pytest
from unittest.mock import AsyncMock, patch

from channel_signal_listener import on_channel_message


@pytest.mark.asyncio
async def test_on_channel_message_dispatches_recognized_signal():
    text = "ЗАХОДИМ В МАНИПУЛЯЦИЮ\n\nXAI SHORT  - текст"
    with patch("channel_signal_listener.ADMIN_CHAT_ID", 111), \
         patch("channel_signal_listener.live_trading.handle_channel_signal", new=AsyncMock(
             return_value={"classification": "reversal", "signal_id": 1}
         )) as mock_handle:
        result = await on_channel_message(session=None, text=text)
    mock_handle.assert_called_once_with(None, 111, "XAI", "short")
    assert result == {"classification": "reversal", "signal_id": 1}


@pytest.mark.asyncio
async def test_on_channel_message_none_for_unrecognized_text():
    with patch("channel_signal_listener.live_trading.handle_channel_signal", new=AsyncMock()) as mock_handle:
        result = await on_channel_message(session=None, text="СДЕЛКА НА СПОТ\n\nUAI Long беру от текущих")
    mock_handle.assert_not_called()
    assert result is None


@pytest.mark.asyncio
async def test_on_channel_message_none_for_missing_text():
    with patch("channel_signal_listener.live_trading.handle_channel_signal", new=AsyncMock()) as mock_handle:
        result = await on_channel_message(session=None, text=None)
    mock_handle.assert_not_called()
    assert result is None
```

- [ ] **Step 3: Запустить тест, убедиться что падает**

Run: `python -m pytest tests/test_channel_signal_listener.py -v`
Expected: FAIL -- `ModuleNotFoundError: No module named 'channel_signal_listener'`

- [ ] **Step 4: Реализовать листенер**

```python
# channel_signal_listener.py
"""
Telethon-листенер стороннего Telegram-канала с сигналами (см. спеку
docs/superpowers/specs/2026-10-04-channel-signal-autotrading-design.md).

on_channel_message() -- тестируемое ядро без сетевой Telethon-обвязки.
run_channel_signal_listener() -- бесконечная задача для asyncio.gather в main.py,
с собственным retry-циклом: обрыв сессии/сети не должен ронять остальные задачи бота.
"""
import asyncio
import logging

import aiohttp
from telethon import TelegramClient, events

import live_trading
from channel_signal_parser import parse_channel_signal
from config import ADMIN_CHAT_ID, CHANNEL_SIGNAL_SOURCE_ID, TG_API_ID, TG_API_HASH, TG_CHANNEL_SESSION_PATH

logger = logging.getLogger(__name__)


async def on_channel_message(session, text: str | None) -> dict | None:
    """Распознаёт сигнал и передаёт в handle_channel_signal. Возвращает None, если
    текст не распознан как сигнал типа A/B (включая тип C и постороннюю переписку)."""
    parsed = parse_channel_signal(text)
    if parsed is None:
        if text:
            logger.info(f"channel_signal: не распознано: {text[:200]!r}")
        return None
    return await live_trading.handle_channel_signal(session, ADMIN_CHAT_ID, parsed.ticker, parsed.direction)


async def run_channel_signal_listener():
    """Подключается к Telegram под пользовательской сессией и слушает
    CHANNEL_SIGNAL_SOURCE_ID. Обрыв соединения -- переподключение через 30с,
    не роняя остальные задачи asyncio.gather в main.py."""
    client = TelegramClient(TG_CHANNEL_SESSION_PATH, TG_API_ID, TG_API_HASH)

    @client.on(events.NewMessage(chats=CHANNEL_SIGNAL_SOURCE_ID))
    async def _handler(event):
        async with aiohttp.ClientSession() as session:
            try:
                await on_channel_message(session, event.message.text)
            except Exception as e:
                logger.error(f"channel_signal: ошибка обработки сообщения: {e}")

    while True:
        try:
            await client.start()
            logger.info("channel_signal_listener: подключен, слушаю канал")
            await client.run_until_disconnected()
        except Exception as e:
            logger.error(f"channel_signal_listener: соединение оборвалось, переподключение через 30с: {e}")
            await asyncio.sleep(30)
```

- [ ] **Step 5: Запустить тесты, убедиться что все проходят**

Run: `python -m pytest tests/test_channel_signal_listener.py -v`
Expected: PASS (все 3 теста)

- [ ] **Step 6: Запустить полный набор тестов проекта**

Run: `python -m pytest -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add channel_signal_listener.py config.py requirements.txt tests/test_channel_signal_listener.py
git commit -m "feat: Telethon-листенер канала сигналов (on_channel_message + retry-цикл)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 5: Скрипт разовой авторизации

**Files:**
- Create: `auth_channel_session.py`

Не TDD-код (интерактивный скрипт, запускается вручную один раз) -- адаптация уже проверенного
в проде `tg-forex-signal-monitor/auth_telethon.py`.

- [ ] **Step 1: Создать скрипт**

```python
# auth_channel_session.py
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
```

- [ ] **Step 2: Commit**

```bash
git add auth_channel_session.py
git commit -m "feat: скрипт разовой авторизации Telethon-сессии для канала сигналов

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 6: Подключить в `main.py` + журнал изменений

**Files:**
- Modify: `main.py:417-423` (`asyncio.gather`)
- Modify: `docs/LOGIC_CHANGELOG.md`
- Test: `tests/test_main_channel_signal_wiring.py`

**Interfaces:**
- Consumes: `channel_signal_listener.run_channel_signal_listener` (Task 4).

- [ ] **Step 1: Написать падающий тест на wiring (по образцу `test_main_trading_report_wiring.py`)**

```python
# tests/test_main_channel_signal_wiring.py
import inspect

import main


def test_main_source_starts_channel_signal_listener():
    assert "run_channel_signal_listener(" in inspect.getsource(main.main)
```

- [ ] **Step 2: Запустить тест, убедиться что падает**

Run: `python -m pytest tests/test_main_channel_signal_wiring.py -v`
Expected: FAIL -- `assert "run_channel_signal_listener(" in inspect.getsource(main.main)`

- [ ] **Step 3: Подключить задачу**

В `main.py`, добавить импорт рядом с остальными (после `from journal_web import run_web_server`):
```python
from channel_signal_listener import run_channel_signal_listener
```

В `asyncio.gather(...)` (main.py:417-423), добавить новую строку:
```python
        await asyncio.gather(
            collectors_supervisor(),
            run_command_listener(cmd_session),
            daily_report_loop(get_symbols_for_report, get_all_subscribers),
            trading_journal_report_loop(ADMIN_CHAT_ID),
            run_web_server(int(os.getenv("PORT", "8080"))),
            run_channel_signal_listener(),
        )
```

- [ ] **Step 4: Запустить тест, убедиться что проходит**

Run: `python -m pytest tests/test_main_channel_signal_wiring.py -v`
Expected: PASS

- [ ] **Step 5: Добавить запись в журнал изменений**

В `docs/LOGIC_CHANGELOG.md`, после последней записи за 03.10, добавить:

```markdown
**04.10** — новый источник входов: сторонний Telegram-канал (-1002487960768, манипуляции
рынка). Парсер под 2 реальных формата сообщений (`channel_signal_parser.py`), Telethon-
листенер под пользовательской сессией (`channel_signal_listener.py`), исполнение через уже
существующий `execute_setup(classification="reversal", ...)` -- стоп/TP-сетка/трейлинг не
меняются. Направление канала: SHORT → `direction="up"` (риск 1%, как памп), LONG →
`direction="down"` (риск 4%, как дамп). Конфликт по монете с уже открытой/ожидающей позицией
(от любого источника) -- сигнал пропускается. Тип "СДЕЛКА НА СПОТ" не исполняется. Колонка
`source` в `trade_signals` ('analyzer'/'channel') -- для будущего честного сравнения
доходности. Paper trading. См. спеку
docs/superpowers/specs/2026-10-04-channel-signal-autotrading-design.md.
```

- [ ] **Step 6: Запустить полный набор тестов проекта**

Run: `python -m pytest -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add main.py docs/LOGIC_CHANGELOG.md tests/test_main_channel_signal_wiring.py
git commit -m "feat: подключить слушатель канала сигналов в main.py

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 7: Деплой и разовая настройка (ручной раннбук, не код)

Существующий Railway Volume (`RAILWAY_VOLUME_MOUNT_PATH=/data`, уже смонтирован на этом
сервисе) переиспользуется для файла сессии -- создавать новый Volume не нужно.

- [ ] **Step 1: Получить `TG_API_ID`/`TG_API_HASH`**
  - Если уже зарегистрировано приложение на my.telegram.org для `tg-forex-signal-monitor` --
    взять те же значения из Railway-переменных того сервиса (это личные данные приложения
    пользователя, не привязаны к конкретному боту).
  - Иначе зарегистрировать новое приложение на https://my.telegram.org/apps.

- [ ] **Step 2: Задать переменные на Railway (сервис binance-impulse-bot, production)**
  - `TG_API_ID` -- из шага 1
  - `TG_API_HASH` -- из шага 1
  - (опционально) `CHANNEL_SIGNAL_SOURCE_ID` -- уже есть дефолт `-1002487960768` в `config.py`,
    переменная нужна только если ID канала изменится
  - `TG_CHANNEL_SESSION_PATH` -- не обязательно, дефолт `/data/channel_signal` уже указывает на
    существующий Volume

- [ ] **Step 3: Задеплоить код из Task 1-6** (обычный git push / Railway auto-deploy)

- [ ] **Step 4: Разово запустить `auth_channel_session.py` на Railway**
  - `railway ssh -p 0257fbc7-9eb8-41cf-970f-409b98b270a6 -e production -s 9efa0d2b-84f6-4764-a2cc-6731b974b98f -- "cd /app && python auth_channel_session.py"`
  - Скрипт запросит номер телефона и код подтверждения (интерактивно, нужен доступ к Telegram
    пользователя, под которым канал уже открыт)
  - Убедиться, что в выводе скрипт нашёл канал (`Канал найден: ...`), не только авторизовался

- [ ] **Step 5: Проверить живьём после деплоя**
  - Смотреть логи Railway на предмет `channel_signal_listener: подключен, слушаю канал`
  - Дождаться следующего реального сигнала в канале, проверить, что в логах появилось
    `channel_signal:` событие и (если сигнал распознан) `📡 Сигнал из канала` в Telegram
  - Если сигнал НЕ распознан -- в логах будет `channel_signal: не распознано: <текст>` --
    сверить формат с парсером из Task 1 и расширить при необходимости (отдельная небольшая
    правка, не часть этого плана)
