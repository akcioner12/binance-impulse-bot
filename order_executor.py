"""
Исполнитель ордеров (paper): открытие позиции и обработка тиков цены
против открытой позиции (SL, TP1-3, безубыток+, Chandelier-трейлинг TP4).
"""

import trading_storage
from position_manager import (
    calculate_average_entry_price,
    calculate_stop_loss,
    calculate_take_profits,
    calculate_breakeven_plus_price,
    ChandelierTrailingStop,
)


def open_paper_position(
    chat_id: int,
    symbol: str,
    exchange: str,
    direction: str,
    fills: list[tuple[float, float]],
    sl_method: str,
    atr_1h: float | None,
    atr_multiplier: float,
    fixed_percent: float | None,
    tp_split_preset: str,
) -> dict:
    """
    fills — список (цена, размер) исполненных частей (часть 1/часть 2 из entry_engine).
    Считает среднюю цену входа, SL, TP1-3 и создаёт запись в positions.
    """
    avg_entry_price = calculate_average_entry_price(fills)
    quantity = sum(size for _, size in fills)
    stop_loss = calculate_stop_loss(
        avg_entry_price, direction, sl_method, atr_1h, atr_multiplier, fixed_percent
    )
    take_profits = calculate_take_profits(avg_entry_price, stop_loss, direction, tp_split_preset)

    position_id = trading_storage.create_position(
        chat_id=chat_id, symbol=symbol, exchange=exchange, direction=direction,
        mode="paper", avg_entry_price=avg_entry_price, quantity=quantity, stop_loss=stop_loss,
    )

    return {
        "position_id": position_id,
        "avg_entry_price": avg_entry_price,
        "quantity": quantity,
        "stop_loss": stop_loss,
        "take_profits": take_profits,
    }


class OpenPositionState:
    """
    Рантайм-состояние открытой позиции (в памяти, не в БД напрямую — запись
    изменений в trading_storage делает вызывающий код на основе событий,
    которые возвращают check_stop_hit()/check_take_profit_hits()).
    """

    def __init__(
        self,
        position_id: int,
        direction: str,
        avg_entry_price: float,
        quantity: float,
        stop_loss: float,
        take_profits: list[dict],
        breakeven_after_tp: int,
    ):
        self.position_id = position_id
        self.direction = direction
        self.avg_entry_price = avg_entry_price
        self.quantity = quantity
        self.remaining_quantity = quantity
        self.stop_loss = stop_loss
        self.take_profits = [dict(tp, filled=False) for tp in take_profits]
        self.breakeven_after_tp = breakeven_after_tp
        self.tp_hit_count = 0
        self.chandelier: ChandelierTrailingStop | None = None
        self.closed = False


def _partial_close_pnl(direction: str, entry_price: float, exit_price: float, size: float) -> float:
    if direction == "long":
        return size * (exit_price - entry_price)
    return size * (entry_price - exit_price)


def check_stop_hit(state: OpenPositionState, price: float, atr_1h: float) -> dict | None:
    """
    Проверяет срабатывание стопа (обычного или Chandelier, если уже активен).
    Полностью закрывает оставшийся объём позиции при срабатывании.
    """
    if state.closed:
        return None

    if state.chandelier is not None:
        state.chandelier.update(price, atr_1h)
        if not state.chandelier.is_triggered(price):
            return None
        event = "closed_chandelier"
    else:
        sl_hit = price <= state.stop_loss if state.direction == "long" else price >= state.stop_loss
        if not sl_hit:
            return None
        event = "closed_stop_loss"

    pnl = _partial_close_pnl(state.direction, state.avg_entry_price, price, state.remaining_quantity)
    size_closed = state.remaining_quantity
    state.closed = True
    return {"event": event, "pnl_delta": pnl, "size_closed": size_closed, "exit_price": price}
