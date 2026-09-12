"""
Управление позицией: направление сделки, средневзвешенный вход, сетка SL/TP,
безубыток+ после TP2, трейлинг-стоп TP4 (Chandelier Exit).
"""

from trading_onboarding import TP_SPLIT_PRESETS


def determine_trade_direction(impulse_direction: str, classification: str) -> str:
    """
    impulse_direction — 'up' (памп) или 'down' (дамп), направление импульса.
    classification — 'reversal' (фейдим манипуляцию) или 'continuation' (едем по тренду),
    из manipulation_detector.classify_impulse().

    reversal + 'up'   -> 'short' (фейдим памп)
    reversal + 'down' -> 'long'  (фейдим дамп)
    continuation + 'up'   -> 'long'  (по тренду вверх)
    continuation + 'down' -> 'short' (по тренду вниз)
    """
    if classification == "reversal":
        return "short" if impulse_direction == "up" else "long"
    return "long" if impulse_direction == "up" else "short"


def calculate_average_entry_price(fills: list[tuple[float, float]]) -> float:
    """fills — список (цена, размер). Средневзвешенная цена входа по объёму частей."""
    total_size = sum(size for _, size in fills)
    if total_size == 0:
        return 0.0
    return sum(price * size for price, size in fills) / total_size


def calculate_stop_loss(
    avg_entry_price: float,
    direction: str,
    sl_method: str = "atr",
    atr_1h: float | None = None,
    atr_multiplier: float = 1.5,
    fixed_percent: float | None = None,
) -> float:
    """
    direction — 'long' или 'short' (направление СДЕЛКИ, из determine_trade_direction()).
    sl_method='atr' -> distance = atr_1h * atr_multiplier (по умолчанию, адаптируется под волатильность).
    sl_method='fixed_percent' -> distance = avg_entry_price * fixed_percent / 100.
    """
    if sl_method == "fixed_percent":
        distance = avg_entry_price * (fixed_percent / 100)
    else:
        distance = atr_1h * atr_multiplier

    if direction == "long":
        return avg_entry_price - distance
    return avg_entry_price + distance


def calculate_take_profits(
    avg_entry_price: float,
    stop_loss: float,
    direction: str,
    tp_split_preset: str,
    r_multiples: tuple[float, float, float] = (1.0, 2.0, 3.0),
) -> list[dict]:
    """
    TP1-3 на R-кратных расстояниях от входа (R = |вход - SL|), доли позиции —
    из пресета TP_SPLIT_PRESETS (см. trading_onboarding.py). TP4 сюда не входит —
    это трейлинг-остаток позиции, управляется ChandelierTrailingStop (Task 5).
    """
    risk_distance = abs(avg_entry_price - stop_loss)
    size_splits = TP_SPLIT_PRESETS[tp_split_preset]

    take_profits = []
    for r, size_pct in zip(r_multiples, size_splits):
        if direction == "long":
            level = avg_entry_price + risk_distance * r
        else:
            level = avg_entry_price - risk_distance * r
        take_profits.append({"level": level, "size_pct": size_pct})

    return take_profits


def calculate_breakeven_plus_price(avg_entry_price: float, direction: str, commission_pct: float = 0.08) -> float:
    """
    Цена "безубыток+" — не ровно цена входа, а с запасом на комиссии обеих
    сделок (вход + выход). commission_pct=0.08 -> ~0.04% тейкер за сторону
    на Binance/Bybit, round-trip 0.08%. Переносится сюда после срабатывания TP2.
    """
    commission_distance = avg_entry_price * (commission_pct / 100)
    if direction == "long":
        return avg_entry_price + commission_distance
    return avg_entry_price - commission_distance


class ChandelierTrailingStop:
    """
    Трейлинг-стоп для TP4 (остаток позиции после TP1-3): стоп = экстремум цены
    с момента создания минус/плюс atr_multiplier×ATR. Стоп — храповик: двигается
    только в выгодную сторону, никогда не откатывается назад.
    """

    def __init__(self, direction: str, atr_multiplier: float = 2.5):
        self.direction = direction
        self.atr_multiplier = atr_multiplier
        self.extreme_price: float | None = None
        self.stop_price: float | None = None

    def update(self, price: float, atr: float) -> float:
        if self.direction == "long":
            self.extreme_price = price if self.extreme_price is None else max(self.extreme_price, price)
            candidate_stop = self.extreme_price - atr * self.atr_multiplier
            self.stop_price = candidate_stop if self.stop_price is None else max(self.stop_price, candidate_stop)
        else:
            self.extreme_price = price if self.extreme_price is None else min(self.extreme_price, price)
            candidate_stop = self.extreme_price + atr * self.atr_multiplier
            self.stop_price = candidate_stop if self.stop_price is None else min(self.stop_price, candidate_stop)
        return self.stop_price

    def is_triggered(self, price: float) -> bool:
        if self.stop_price is None:
            return False
        if self.direction == "long":
            return price <= self.stop_price
        return price >= self.stop_price


def calculate_position_size(balance: float, risk_percent: float, entry_price: float, stop_loss: float) -> float:
    """
    Размер позиции в единицах базового актива (например, BTC для BTCUSDT),
    рассчитанный так, чтобы срабатывание SL дало убыток ровно risk_percent%
    от баланса. Не зависит от плеча -- плечо влияет только на требуемую маржу,
    не на сам PnL при данном размере позиции.
    """
    risk_amount = balance * (risk_percent / 100)
    stop_distance = abs(entry_price - stop_loss)
    if stop_distance == 0:
        return 0.0
    return risk_amount / stop_distance
