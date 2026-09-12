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
