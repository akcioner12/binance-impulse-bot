"""
Трейлинг-триггеры входа для частей 1 и 2 сделки на разворот (фейд манипуляции).

Обе части трейлятся за экстремумом цены и срабатывают по рынку при откате —
разница только в туге отката (часть 1 тугая, срабатывает раньше; часть 2
широкая, ловит дополнительный стоп-хант перед истинным разворотом).
Части независимы: у каждой свой TrailingEntryTrigger, ведут собственный
мониторинг экстремума, не знают друг о друге.
"""

PART1_ATR_MULTIPLIER = 0.75
PART2_ATR_MULTIPLIER = 2.0


class TrailingEntryTrigger:
    def __init__(self, direction: str, trigger_distance: float):
        """
        direction — направление ИМПУЛЬСА ('up' или 'down'), не направление сделки.
        Для 'up'-импульса (пампа) ждём отката ВНИЗ от максимума -- готовим шорт.
        Для 'down'-импульса (дампа) ждём отскока ВВЕРХ от минимума -- готовим лонг.
        trigger_distance — абсолютное расстояние отката, вызывающее срабатывание
        (обычно N×ATR, посчитанный заранее).
        """
        self.direction = direction
        self.trigger_distance = trigger_distance
        self.extreme_price: float | None = None
        self.fired = False
        self.fire_price: float | None = None

    def update(self, price: float) -> bool:
        """Скармливаем новую цену. Возвращает True ровно в момент срабатывания."""
        if self.fired:
            return False

        if self.extreme_price is None:
            self.extreme_price = price
            return False

        if self.direction == "up":
            self.extreme_price = max(self.extreme_price, price)
            if price <= self.extreme_price - self.trigger_distance:
                self.fired = True
                self.fire_price = price
                return True
        else:
            self.extreme_price = min(self.extreme_price, price)
            if price >= self.extreme_price + self.trigger_distance:
                self.fired = True
                self.fire_price = price
                return True

        return False


def create_part1_trigger(direction: str, atr_15m: float) -> TrailingEntryTrigger:
    """Тугой триггер части 1 -- срабатывает раньше, ловит раннюю точку разворота."""
    return TrailingEntryTrigger(direction=direction, trigger_distance=atr_15m * PART1_ATR_MULTIPLIER)


def create_part2_trigger(direction: str, atr_15m: float) -> TrailingEntryTrigger:
    """Широкий триггер части 2 -- ловит дополнительный стоп-хант перед разворотом."""
    return TrailingEntryTrigger(direction=direction, trigger_distance=atr_15m * PART2_ATR_MULTIPLIER)
