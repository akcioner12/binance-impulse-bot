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

from config import IMPULSE_START_THRESHOLD, IMPULSE_STEP, WINDOW_MINUTES

logger = logging.getLogger(__name__)

WINDOW_SECONDS = WINDOW_MINUTES * 60


@dataclass
class ImpulseSignal:
    symbol: str
    direction: str       # 'up' | 'down'
    level: float         # достигнутый уровень: 30, 40, 50 ...
    change_pct: float    # фактическое изменение, например 31.4
    window_start_price: float
    current_price: float
    is_new_peak: bool    # True если это новый максимум импульса (не первый сигнал по нему)


class PriceWindowTracker:
    def __init__(self):
        # symbol -> deque[(timestamp, price)]
        self._buffers: dict[str, deque] = {}
        # symbol -> {"direction": "up"/"down", "level": 30.0}
        self._active: dict[str, dict] = {}

    def restore_state(self, symbol: str, direction: str, level: float):
        """Восстановление состояния из БД при старте бота."""
        self._active[symbol] = {"direction": direction, "level": level}

    def is_active(self, symbol: str) -> bool:
        return symbol in self._active

    def update(self, symbol: str, price: float, ts: int | None = None) -> ImpulseSignal | None:
        """
        Добавляет новую точку цены и проверяет импульс.
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

        state = self._active.get(symbol)

        # --- Импульс активен ---
        if state and state["direction"] == direction:
            # Откат ниже стартового порога — импульс затух, сбрасываем
            if abs_change < IMPULSE_START_THRESHOLD:
                del self._active[symbol]
                logger.info(f"{symbol}: импульс {direction} затух ({abs_change:.1f}%)")
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
                    symbol=symbol, direction=direction, level=level,
                    change_pct=round(change_pct, 2),
                    window_start_price=window_start_price, current_price=price,
                    is_new_peak=True,
                )
            return None  # тот же уровень, ничего нового

        # --- Импульс сменил направление (был up, стал down резко) или не был активен ---
        if abs_change >= IMPULSE_START_THRESHOLD:
            self._active[symbol] = {"direction": direction, "level": IMPULSE_START_THRESHOLD}
            return ImpulseSignal(
                symbol=symbol, direction=direction, level=IMPULSE_START_THRESHOLD,
                change_pct=round(change_pct, 2),
                window_start_price=window_start_price, current_price=price,
                is_new_peak=False,  # первый сигнал по этому импульсу
            )

        return None
