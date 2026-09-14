"""
Скользящее окно цен и детектор импульса.

Логика (см. объяснение пользователю):
- Для каждой пары храним буфер (timestamp, price) за последние WINDOW_MINUTES.
- На каждом тике (закрытие минутной свечи) сравниваем текущую цену
  с самой старой ценой в буфере (~WINDOW_MINUTES назад).
- НЕ сбрасываем счётчик по границам времени — окно скользит непрерывно.
- При пересечении IMPULSE_START_THRESHOLD (30%) — первый сигнал.
- Далее каждые IMPULSE_STEP (10%) — повторный сигнал на том же направлении.
- Если импульс затухает (откатывается ниже стартового порога) — состояние сбрасывается,
  и пара может просигналить заново при новом импульсе.
"""

import time
import logging
from collections import deque
from dataclasses import dataclass

from config import IMPULSE_START_THRESHOLD, IMPULSE_STEP, IMPULSE_RESET_HYSTERESIS, WINDOW_MINUTES

logger = logging.getLogger(__name__)

WINDOW_SECONDS = WINDOW_MINUTES * 60


EXCHANGE_LINK_TEMPLATES = {
    "Binance": "https://www.binance.com/en/futures/{symbol}",
    "Bybit":   "https://www.bybit.com/trade/usdt/{symbol}",
}


def build_exchange_link(exchange: str, symbol: str) -> str:
    template = EXCHANGE_LINK_TEMPLATES.get(exchange, EXCHANGE_LINK_TEMPLATES["Binance"])
    return template.format(symbol=symbol)


@dataclass
class ImpulseSignal:
    symbol: str
    exchange: str        # 'Binance' | 'Bybit' — биржа-источник данных
    direction: str        # 'up' | 'down'
    level: float          # достигнутый уровень: 30, 40, 50 ...
    change_pct: float     # фактическое изменение, например 31.4
    window_start_price: float
    current_price: float
    is_new_peak: bool     # True если это новый максимум импульса (не первый сигнал по нему)


class PriceWindowTracker:
    def __init__(self):
        # symbol -> deque[(timestamp, price)]
        self._buffers: dict[str, deque] = {}
        # symbol -> {"direction": "up"/"down", "level": 30.0}
        self._active: dict[str, dict] = {}

    def restore_state(self, symbol: str, direction: str, level: float):
        """Восстановление состояния из БД при старте бота."""
        self._active[symbol] = {"direction": direction, "level": level}

    def seed_history(self, symbol: str, points: list[tuple[int, float]]):
        """
        Заполняет буфер историческими точками (ts, price) БЕЗ генерации сигналов --
        вызывается один раз при старте бота (из исторических свечей биржи), чтобы
        рестарт не обнулял скользящее 24ч окно: буфер живёт только в памяти
        процесса, не в БД, и без сидирования окно эффективно "теряет память" на
        время, пока новые тики не накопят собственные 24ч заново.
        Если по символу уже есть данные (реальный тик пришёл раньше сидирования) --
        не трогаем, чтобы не затереть более свежую реальную историю устаревшей.
        """
        if not points or symbol in self._buffers:
            return
        buf = self._buffers.setdefault(symbol, deque())
        for ts, price in sorted(points):
            buf.append((ts, price))

    def is_active(self, symbol: str) -> bool:
        return symbol in self._active

    def update(self, symbol: str, exchange: str, price: float, ts: int | None = None) -> ImpulseSignal | None:
        """
        Добавляет новую точку цены и проверяет импульс.
        exchange — 'Binance' или 'Bybit', попадает в итоговый сигнал и в ссылку алерта.
        ts — unix timestamp в секундах (по умолчанию текущее время).
        """
        ts = ts or int(time.time())

        buf = self._buffers.setdefault(symbol, deque())
        buf.append((ts, price))

        # Удаляем точки старше окна
        cutoff = ts - WINDOW_SECONDS
        while buf and buf[0][0] < cutoff:
            buf.popleft()

        if len(buf) < 2:
            return None  # недостаточно данных

        window_start_price = buf[0][1]
        if window_start_price <= 0:
            return None

        change_pct = (price - window_start_price) / window_start_price * 100
        abs_change = abs(change_pct)
        direction = "up" if change_pct > 0 else "down"

        # Диагностика: логируем приближение к порогу (от 80% от стартового уровня),
        # даже если сигнал не отправлен. Помогает понять постфактум, видел ли бот
        # вообще движение по символу и почему не сработал сигнал.
        if abs_change >= IMPULSE_START_THRESHOLD * 0.8:  # от 24% и выше при пороге 30%
            logger.debug(
                f"{symbol}: abs_change={abs_change:.1f}% direction={direction} "
                f"buf_len={len(buf)} window_start={window_start_price} current={price} "
                f"active_state={self._active.get(symbol)}"
            )

        state = self._active.get(symbol)

        # --- Импульс активен ---
        if state and state["direction"] == direction:
            # Сброс происходит только при заметном откате — на IMPULSE_RESET_HYSTERESIS
            # процентных пунктов НИЖЕ ДОСТИГНУТОГО УРОВНЯ, а не ниже стартового порога.
            # Например: достигли 30% -> сброс только при откате до 10% (30 - 20).
            # Без этого любое мелкое колебание цены около 30% (даже на десятые доли
            # процента) сбрасывало бы счётчик и вызывало повторный сигнал на том же
            # уровне — именно это случилось с CLOUSDT.
            reset_threshold = state["level"] - IMPULSE_RESET_HYSTERESIS
            if abs_change < reset_threshold:
                del self._active[symbol]
                logger.info(
                    f"{symbol}: импульс {direction} затух (откат до {abs_change:.1f}%, "
                    f"был на уровне {state['level']:.0f}%)"
                )
                return None

            # Проверяем, не достигли ли следующего уровня (+10%)
            next_level = state["level"] + IMPULSE_STEP
            if abs_change >= next_level:
                # Может быть скачок сразу через несколько уровней — берём максимальный достигнутый
                level = next_level
                while abs_change >= level + IMPULSE_STEP:
                    level += IMPULSE_STEP
                self._active[symbol] = {"direction": direction, "level": level}
                return ImpulseSignal(
                    symbol=symbol, exchange=exchange, direction=direction, level=level,
                    change_pct=round(change_pct, 2),
                    window_start_price=window_start_price, current_price=price,
                    is_new_peak=True,
                )
            return None  # тот же уровень, ничего нового

        # --- Импульс сменил направление (был up, стал down резко) или не был активен ---
        if abs_change >= IMPULSE_START_THRESHOLD:
            self._active[symbol] = {"direction": direction, "level": IMPULSE_START_THRESHOLD}
            return ImpulseSignal(
                symbol=symbol, exchange=exchange, direction=direction, level=IMPULSE_START_THRESHOLD,
                change_pct=round(change_pct, 2),
                window_start_price=window_start_price, current_price=price,
                is_new_peak=False,  # первый сигнал по этому импульсу
            )

        return None


DUMP_WINDOW_DAYS = 10
DAY_SECONDS = 86400


class DailyHighTracker:
    """
    Скользящий 10-дневный максимум для детекции дампов -- ТОЛЬКО для
    автотрейдинга (см. docs/superpowers/specs/2026-09-14-multiday-dump-window-design.md).
    Не участвует в текстовых алертах подписчикам -- те остаются на
    PriceWindowTracker (24ч), который не меняется.

    В отличие от PriceWindowTracker, хранит не полный тик-буфер, а только
    дневные максимумы: до DUMP_WINDOW_DAYS-1 завершённых суток + текущий
    (незавершённый) день, обновляемый на каждом тике. Дёшево по памяти на
    несколько сотен символов.
    """

    def __init__(self):
        self._daily_highs: dict[str, deque] = {}
        self._current_day_high: dict[str, float] = {}
        self._current_day_start: dict[str, int] = {}
        # symbol -> {"level": 30.0, "anchor_price": float}
        self._active: dict[str, dict] = {}

    def is_active(self, symbol: str) -> bool:
        return symbol in self._active

    def seed_history(self, symbol: str, daily_highs: list[float], current_day_high: float, current_day_start_ts: int):
        """
        Заполняет историю дневных максимумов при старте бота -- без этого
        после каждого рестарта Railway 10-дневное окно "теряет память" так
        же, как раньше терял её 24ч-буфер PriceWindowTracker (см. инцидент
        13.09.2026, main._seed_price_history). Не перезаписывает, если по
        символу уже накоплены реальные тики.
        """
        if symbol in self._current_day_start:
            return
        self._daily_highs[symbol] = deque(daily_highs, maxlen=DUMP_WINDOW_DAYS - 1)
        self._current_day_high[symbol] = current_day_high
        self._current_day_start[symbol] = current_day_start_ts

    def _day_start(self, ts: int) -> int:
        return ts - (ts % DAY_SECONDS)

    def _advance_day(self, symbol: str, price: float, ts: int):
        day_start = self._day_start(ts)
        known_start = self._current_day_start.get(symbol)

        if known_start is None:
            self._current_day_start[symbol] = day_start
            self._current_day_high[symbol] = price
            return

        if day_start > known_start:
            highs = self._daily_highs.setdefault(symbol, deque(maxlen=DUMP_WINDOW_DAYS - 1))
            highs.append(self._current_day_high[symbol])
            self._current_day_start[symbol] = day_start
            self._current_day_high[symbol] = price
            return

        self._current_day_high[symbol] = max(self._current_day_high[symbol], price)

    def _rolling_max(self, symbol: str) -> float:
        highs = list(self._daily_highs.get(symbol, ()))
        current = self._current_day_high.get(symbol)
        if current is not None:
            highs.append(current)
        return max(highs) if highs else 0.0

    def update(self, symbol: str, exchange: str, price: float, ts: int | None = None) -> ImpulseSignal | None:
        """
        Аналог PriceWindowTracker.update(), но база -- скользящий 10-дневный
        максимум high вместо цены "24ч назад", и направление всегда "down".
        Пока сигнал активен, база зафиксирована (anchor_price) -- живой
        rolling max может уменьшиться сам по себе при выпадении старого
        пика из окна, это не должно сбрасывать уже идущий сигнал.
        """
        ts = ts or int(time.time())
        self._advance_day(symbol, price, ts)

        state = self._active.get(symbol)
        base_price = state["anchor_price"] if state else self._rolling_max(symbol)
        if base_price <= 0:
            return None

        change_pct = (price - base_price) / base_price * 100
        abs_change = abs(change_pct)

        if change_pct >= 0:
            if state:
                del self._active[symbol]
            return None

        if state:
            reset_threshold = state["level"] - IMPULSE_RESET_HYSTERESIS
            if abs_change < reset_threshold:
                del self._active[symbol]
                logger.info(f"{symbol}: дамп затух (откат до {abs_change:.1f}%, был на уровне {state['level']:.0f}%)")
                return None

            next_level = state["level"] + IMPULSE_STEP
            if abs_change >= next_level:
                level = next_level
                while abs_change >= level + IMPULSE_STEP:
                    level += IMPULSE_STEP
                self._active[symbol] = {"level": level, "anchor_price": base_price}
                return ImpulseSignal(
                    symbol=symbol, exchange=exchange, direction="down", level=level,
                    change_pct=round(change_pct, 2),
                    window_start_price=base_price, current_price=price,
                    is_new_peak=True,
                )
            return None

        if abs_change >= IMPULSE_START_THRESHOLD:
            self._active[symbol] = {"level": IMPULSE_START_THRESHOLD, "anchor_price": base_price}
            return ImpulseSignal(
                symbol=symbol, exchange=exchange, direction="down", level=IMPULSE_START_THRESHOLD,
                change_pct=round(change_pct, 2),
                window_start_price=base_price, current_price=price,
                is_new_peak=False,
            )
        return None
