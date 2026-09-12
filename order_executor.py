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
