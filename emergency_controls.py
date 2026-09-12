"""
Аварийные контролы автотрейдинга: стоп/старт торговли, закрыть все позиции
сейчас, перенести все открытые позиции в безубыток+.

"Закрыть всё сейчас" НЕ делает сетевой запрос на закрытие по рынку -- вместо
этого временно выставляет SL так, чтобы штатный check_stop_hit() гарантированно
сработал на следующем тике цены (минутная гранулярность, как весь остальной
бот) -- переиспользуем уже протестированный путь закрытия вместо нового кода.
"""

import trading_storage
import live_trading
import position_manager


def stop_trading(chat_id: int) -> None:
    """Останавливает открытие НОВЫХ сделок. Открытые позиции не трогает."""
    trading_storage.set_trading_active(chat_id, False)


def start_trading(chat_id: int) -> None:
    trading_storage.set_trading_active(chat_id, True)


def close_all_positions_now(chat_id: int) -> list[str]:
    closed_symbols = []
    for symbol, entry in live_trading._open_positions.items():
        if entry["chat_id"] != chat_id:
            continue
        state = entry["state"]
        state.chandelier = None  # сбрасываем трейлинг -- сработает именно принудительный SL
        state.stop_loss = float("inf") if state.direction == "long" else float("-inf")
        closed_symbols.append(symbol)
    return closed_symbols


def move_all_to_breakeven_plus_now(chat_id: int, commission_pct: float = 0.08) -> list[str]:
    updated_symbols = []
    for symbol, entry in live_trading._open_positions.items():
        if entry["chat_id"] != chat_id:
            continue
        state = entry["state"]
        if state.chandelier is not None:
            continue  # уже на трейлинге TP4 -- переносить в безубыток+ уже не нужно
        new_stop = position_manager.calculate_breakeven_plus_price(
            state.avg_entry_price, state.direction, commission_pct
        )
        state.stop_loss = new_stop
        trading_storage.update_position_stop_loss(state.position_id, new_stop)
        updated_symbols.append(symbol)
    return updated_symbols
