import pytest
from unittest.mock import AsyncMock, patch

import trading_daily_report


def test_compute_daily_summary_calculates_win_rate_and_total_pnl():
    closed_positions = [
        {"realized_pnl": 10.0}, {"realized_pnl": -5.0}, {"realized_pnl": 20.0}, {"realized_pnl": -3.0},
    ]
    summary = trading_daily_report.compute_daily_summary(closed_positions, current_balance=1022.0)

    assert summary["total_trades"] == 4
    assert summary["wins"] == 2
    assert summary["losses"] == 2
    assert summary["win_rate"] == pytest.approx(50.0)
    assert summary["total_pnl"] == pytest.approx(22.0)
    assert summary["current_balance"] == 1022.0


def test_compute_daily_summary_zero_trades_gives_zero_win_rate():
    summary = trading_daily_report.compute_daily_summary([], current_balance=1000.0)
    assert summary["total_trades"] == 0
    assert summary["win_rate"] == 0.0
    assert summary["total_pnl"] == 0.0


def test_compute_daily_summary_break_even_trade_counts_as_loss():
    # realized_pnl == 0 (сделка вышла в ровный ноль) -- не считаем выигрышем
    summary = trading_daily_report.compute_daily_summary([{"realized_pnl": 0.0}], current_balance=1000.0)
    assert summary["wins"] == 0
    assert summary["losses"] == 1


@pytest.mark.asyncio
async def test_build_and_send_trading_report_sends_formatted_text():
    closed_positions = [{"realized_pnl": 15.0}, {"realized_pnl": -5.0}]
    with patch("trading_daily_report.trading_storage.get_positions_closed_since", return_value=closed_positions), \
         patch("trading_daily_report.trading_storage.get_paper_balance", return_value=1010.0), \
         patch("trading_daily_report.send_text", new=AsyncMock()) as mock_send:
        await trading_daily_report.build_and_send_trading_report(chat_id=111)

    mock_send.assert_called_once()
    args = mock_send.call_args[0]
    assert args[1] == 111
    text = args[2]
    assert "2" in text  # 2 сделки
    assert "1010" in text  # баланс
