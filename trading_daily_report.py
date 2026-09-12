"""
Ежедневный отчёт по paper-сделкам автотрейдинга: число сделок, win-rate,
реализованный PnL за сутки, текущий виртуальный баланс. Использует то же
расписание, что и существующий дневной отчёт топ-10 (daily_report.py).
"""

import asyncio
import logging
from datetime import datetime, timezone, timedelta

import aiohttp

from notifier import send_text
from daily_report import seconds_until_next_report
import trading_storage

logger = logging.getLogger(__name__)


def compute_daily_summary(closed_positions: list[dict], current_balance: float) -> dict:
    total_trades = len(closed_positions)
    wins = [p for p in closed_positions if p["realized_pnl"] > 0]
    losses = [p for p in closed_positions if p["realized_pnl"] <= 0]
    total_pnl = sum(p["realized_pnl"] for p in closed_positions)
    win_rate = (len(wins) / total_trades * 100) if total_trades > 0 else 0.0
    return {
        "total_trades": total_trades,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": win_rate,
        "total_pnl": total_pnl,
        "current_balance": current_balance,
    }


def _format_report(summary: dict) -> str:
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    pnl_sign = "+" if summary["total_pnl"] >= 0 else ""
    return (
        f"📈 *Автотрейдинг — отчёт за {date_str} (UTC)*\n\n"
        f"Сделок закрыто: {summary['total_trades']} "
        f"(прибыльных {summary['wins']} / убыточных {summary['losses']})\n"
        f"Win-rate: {summary['win_rate']:.0f}%\n"
        f"PnL за день: {pnl_sign}{summary['total_pnl']:.2f} USDT\n"
        f"Текущий виртуальный баланс: {summary['current_balance']:.2f} USDT"
    )


async def build_and_send_trading_report(chat_id: int):
    since = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
    closed_positions = trading_storage.get_positions_closed_since(chat_id, since)
    current_balance = trading_storage.get_paper_balance(chat_id) or 0.0

    summary = compute_daily_summary(closed_positions, current_balance)
    report_text = _format_report(summary)

    async with aiohttp.ClientSession() as session:
        await send_text(session, chat_id, report_text)

    logger.info(f"Отчёт автотрейдинга отправлен chat_id={chat_id}: сделок={summary['total_trades']}, PnL={summary['total_pnl']:.2f}")


async def trading_daily_report_loop(chat_id: int):
    """Бесконечный цикл: ждёт времени отчёта (то же расписание, что daily_report.py), шлёт отчёт."""
    while True:
        wait_sec = seconds_until_next_report()
        await asyncio.sleep(wait_sec)

        try:
            await build_and_send_trading_report(chat_id)
        except Exception as e:
            logger.exception(f"Ошибка формирования отчёта автотрейдинга: {e}")

        await asyncio.sleep(60)  # защита от повторного срабатывания при дрожании таймера
