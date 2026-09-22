from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

import trading_journal_report as tjr

NOW = datetime(2026, 9, 19, 12, 0, 0)


def _e(ts, symbol, event, pnl):
    return {"ts": ts, "symbol": symbol, "event": event, "pnl": pnl}


def _events():
    return [
        _e("2026-09-17 10:00:00", "AAAUSDT", "tp1_hit", 10.0),
        _e("2026-09-17 12:00:00", "AAAUSDT", "tp2_hit", 20.0),
        _e("2026-09-18 08:00:00", "AAAUSDT", "closed_chandelier", 5.0),
        _e("2026-09-18 16:00:00", "BBBUSDT", "closed_stop_loss", -20.0),
        _e("2026-09-19 09:00:00", "CCCUSDT", "tp1_hit", 10.0),
    ]


def test_build_journal_data_groups_events_into_positions_and_summarizes():
    data = tjr.build_journal_data(_events(), NOW, reset_at="15.09.2026 09:08 UTC")

    full = data["full"]["summary"]
    assert full == {"count": 3, "closed": 2, "open": 1, "wins": 1, "losses": 1, "winrate": 50.0, "total_pnl": 25.0}
    aaa = data["full"]["positions"][0]
    assert aaa["symbol"] == "AAAUSDT" and aaa["pnl"] == 35.0
    assert aaa["tp1"] == "17.09 10:00" and aaa["tp2"] == "17.09 12:00" and aaa["tp3"] is None
    assert aaa["exit_type"] == "Трейлинг (TP4)" and aaa["open"] is False
    assert data["full"]["positions"][2]["open"] is True
    assert data["generated_at"] == "19.09.2026 12:00 UTC"
    assert data["reset_at"] == "15.09.2026 09:08 UTC"


def test_build_journal_data_last24h_contains_only_recently_active_positions():
    data = tjr.build_journal_data(_events(), NOW, reset_at="x")

    last24 = data["last24h"]
    assert [p["symbol"] for p in last24["positions"]] == ["BBBUSDT", "CCCUSDT"]  # AAA последний раз двигалась 18.09 08:00 (>24ч)
    assert last24["summary"]["total_pnl"] == -10.0
    assert last24["cutoff"] == "18.09 12:00 UTC"


def test_same_symbol_after_close_starts_new_position():
    events = [
        _e("2026-09-17 10:00:00", "AAAUSDT", "closed_stop_loss", -5.0),
        _e("2026-09-18 10:00:00", "AAAUSDT", "tp1_hit", 7.0),
    ]
    data = tjr.build_journal_data(events, NOW, reset_at="x")

    assert data["full"]["summary"]["count"] == 2
    assert [p["pnl"] for p in data["full"]["positions"]] == [-5.0, 7.0]


def test_build_journal_data_with_no_events():
    data = tjr.build_journal_data([], NOW, reset_at="x")

    assert data["full"]["summary"]["count"] == 0
    assert data["full"]["summary"]["winrate"] == 0.0


def test_render_journal_html_embeds_data_and_reset_label():
    data = tjr.build_journal_data(_events(), NOW, reset_at="15.09.2026 09:08 UTC")
    html = tjr.render_journal_html(data)

    assert "AAAUSDT" in html
    assert "15.09.2026 09:08 UTC" in html
    assert "__DATA_JSON__" not in html and "__RESET_AT__" not in html


def test_format_summary_shows_full_and_24h_numbers_and_balance():
    data = tjr.build_journal_data(_events(), NOW, reset_at="15.09.2026 09:08 UTC")
    text = tjr.format_summary(data, balance=10123.45)

    assert "+25.00" in text  # PnL за весь период
    assert "-10.00" in text  # PnL за 24ч
    assert "10123.45" in text
    assert "50" in text  # winrate


def test_format_summary_shows_realized_balance_unrealized_and_equity():
    data = tjr.build_journal_data(_events(), NOW, reset_at="15.09.2026 09:08 UTC")
    text = tjr.format_summary(data, balance=8603.0, unrealized=2300.5, open_count=26)

    assert "8603.00" in text  # реализованный баланс
    assert "+2300.50" in text and "26" in text  # нереализованное по открытым
    assert "10903.50" in text  # эквити
    assert "+9.0" in text  # к стартовым $10 000


@pytest.mark.parametrize("now_utc, expected_sec", [
    (datetime(2026, 9, 19, 5, 0, 0, tzinfo=timezone.utc), 3600),           # 08:00 Киев (лето, UTC+3) -> 09:00
    (datetime(2026, 9, 19, 6, 0, 1, tzinfo=timezone.utc), 12 * 3600 - 1),  # 09:00:01 -> 21:00
    (datetime(2026, 9, 19, 19, 0, 0, tzinfo=timezone.utc), 11 * 3600),     # 22:00 Киев -> 09:00 следующего дня
    (datetime(2026, 11, 1, 6, 59, 0, tzinfo=timezone.utc), 60),            # зима (UTC+2): 08:59 Киев -> 09:00
])
def test_seconds_until_next_report_uses_kyiv_time(now_utc, expected_sec):
    assert tjr.seconds_until_next_report(now_utc) == expected_sec


def test_parse_seed_lines_reads_events_with_signs_and_unicode_symbols():
    lines = [
        "2026-09-15 10:27:00 AKEUSDT closed_stop_loss -155.30\n",
        "2026-09-17 02:51:00 我踏马来了USDT tp1_hit +18.88\n",
        "\n",
    ]
    assert tjr.parse_seed_lines(lines) == [
        ("2026-09-15 10:27:00", "AKEUSDT", "closed_stop_loss", -155.30),
        ("2026-09-17 02:51:00", "我踏马来了USDT", "tp1_hit", 18.88),
    ]


def test_bundled_seed_file_is_parseable_and_nonempty():
    rows = tjr.load_seed_events()

    assert len(rows) > 100
    assert all(len(r) == 4 for r in rows)


@pytest.mark.asyncio
async def test_build_and_send_sends_summary_then_html_document():
    with patch("trading_journal_report.trading_storage.get_trade_events", return_value=_events()), \
         patch("trading_journal_report.trading_storage.get_paper_balance", return_value=10050.0), \
         patch("trading_journal_report.live_trading.get_unrealized_pnl", return_value=(200.0, 3)), \
         patch("trading_journal_report.send_text", new=AsyncMock()) as mock_text, \
         patch("trading_journal_report.send_document", new=AsyncMock(return_value=True)) as mock_doc:
        await tjr.build_and_send_journal(chat_id=111, now=NOW)

    assert mock_text.await_count == 1
    assert "10050.00" in mock_text.await_args.args[2]
    assert "10250.00" in mock_text.await_args.args[2]  # эквити = баланс + нереализованное
    assert mock_doc.await_count == 1
    assert mock_doc.await_args.args[1] == 111
    assert mock_doc.await_args.args[2].endswith(".html")
    assert b"AAAUSDT" in mock_doc.await_args.args[3]


def test_events_block_counts_every_tp_leg_and_stops_with_sums():
    """TP1, TP2, TP3 и TP4 (трейлинг) -- отдельные ноги; 'все TP' = сумма ног, стоп -- закрытие остатка."""
    data = tjr.build_journal_data(_events(), NOW, reset_at="x")

    ev = data["full"]["events"]
    assert ev["tp1"] == {"n": 2, "sum": 20.0}
    assert ev["tp2"] == {"n": 1, "sum": 20.0}
    assert ev["tp3"] == {"n": 0, "sum": 0.0}
    assert ev["tp4"] == {"n": 1, "sum": 5.0}
    assert ev["tp_all"] == {"n": 4, "sum": 45.0}
    assert ev["stop"] == {"n": 1, "sum": -20.0}
    assert ev["timeout"] == {"n": 0, "sum": 0.0}


def test_events_block_for_last24h_uses_only_events_inside_window():
    data = tjr.build_journal_data(_events(), NOW, reset_at="x")

    ev = data["last24h"]["events"]  # окно: 18.09 12:00 -- 19.09 12:00
    assert ev["tp_all"] == {"n": 1, "sum": 10.0}   # только CCC tp1
    assert ev["stop"] == {"n": 1, "sum": -20.0}    # BBB


def test_exits_block_splits_stops_with_and_without_tp_and_counts_trade_totals():
    events = _events() + [
        _e("2026-09-19 10:00:00", "DDDUSDT", "tp1_hit", 30.0),
        _e("2026-09-19 11:00:00", "DDDUSDT", "closed_stop_loss", -10.0),  # стоп после TP1: сделка в плюсе (+20)
    ]
    data = tjr.build_journal_data(events, NOW, reset_at="x")

    ex = data["full"]["exits"]
    assert ex["stop"] == {"n": 2, "sum": 0.0, "wins": 1, "without_tp": 1, "after_tp": 1}  # BBB -20 и DDD +20
    assert ex["trail"] == {"n": 1, "sum": 35.0, "wins": 1}
    assert ex["timeout"] == {"n": 0, "sum": 0.0, "wins": 0}


def test_rendered_html_contains_stops_and_take_profit_section():
    html = tjr.render_journal_html(tjr.build_journal_data(_events(), NOW, reset_at="x"))

    assert "Стопы и take profit" in html


def test_summary_text_shows_tp_legs_vs_stops_for_both_periods():
    data = tjr.build_journal_data(_events(), NOW, reset_at="x")
    text = tjr.format_summary(data, balance=10000.0)

    assert "Ноги take profit: 4 (+45.00)" in text and "Стопы: 1 (-20.00)" in text   # весь период
    assert "Ноги take profit: 1 (+10.00)" in text                                  # за 24 часа


def test_first_day_is_split_by_close_time_and_excluded_from_after_first_day():
    events = [
        _e("2026-09-15 10:00:00", "OLDUSDT", "closed_stop_loss", -100.0),   # закрыта в первые сутки
        _e("2026-09-16 06:00:00", "RAYUSDT", "tp1_hit", 40.0),              # начата в первые сутки, закрыта позже
        _e("2026-09-18 09:00:00", "RAYUSDT", "closed_chandelier", 1000.0),
        _e("2026-09-17 10:00:00", "NEWUSDT", "closed_stop_loss", -30.0),
    ]
    data = tjr.build_journal_data(events, NOW, reset_at="x", first_day_end=datetime(2026, 9, 16, 9, 8, 0))

    assert data["first_day"]["count"] == 1 and data["first_day"]["pnl"] == -100.0
    after = data["after_first_day"]
    assert {p["symbol"] for p in after["positions"]} == {"RAYUSDT", "NEWUSDT"}
    assert after["summary"]["total_pnl"] == 1010.0
    assert after["events"]["tp_all"] == {"n": 2, "sum": 1040.0}   # tp1 + трейлинг у RAY
    assert after["events"]["stop"]["n"] == 1
    assert data["full"]["summary"]["total_pnl"] == 910.0


def test_build_journal_data_includes_equity_block_when_balance_given():
    data = tjr.build_journal_data(_events(), NOW, reset_at="x", balance=8603.0, unrealized=2300.5, open_count=26)

    eq = data["equity"]
    assert eq["balance"] == 8603.0 and eq["unrealized"] == 2300.5 and eq["open_count"] == 26
    assert eq["equity"] == 10903.5
    assert eq["equity_pct"] == 9.0
    assert eq["equity_after_first_day"] == 10903.5  # в _events() первых суток нет


def test_build_journal_data_equity_accounts_for_first_day_pnl():
    events = [
        _e("2026-09-15 10:00:00", "OLDUSDT", "closed_stop_loss", -100.0),  # первые сутки
        _e("2026-09-17 10:00:00", "NEWUSDT", "closed_stop_loss", -30.0),
    ]
    data = tjr.build_journal_data(events, NOW, reset_at="x", first_day_end=datetime(2026, 9, 16, 9, 8, 0),
                                   balance=9870.0, unrealized=50.0, open_count=1)

    eq = data["equity"]
    assert eq["equity"] == 9920.0
    assert eq["equity_after_first_day"] == 10020.0  # 9920 - (-100)
    assert eq["equity_after_first_day_pct"] == 0.2


def test_build_journal_data_equity_is_none_without_balance():
    data = tjr.build_journal_data(_events(), NOW, reset_at="x")

    assert data["equity"] is None


def test_rendered_html_shows_equity_section_when_present():
    data = tjr.build_journal_data(_events(), NOW, reset_at="x", balance=8603.0, unrealized=2300.5, open_count=26)
    html = tjr.render_journal_html(data)

    assert "10903.5" in html


def test_format_summary_leads_with_equity_without_first_day():
    events = [
        _e("2026-09-15 10:00:00", "OLDUSDT", "closed_stop_loss", -100.0),
        _e("2026-09-17 10:00:00", "NEWUSDT", "closed_stop_loss", -30.0),
    ]
    data = tjr.build_journal_data(events, NOW, reset_at="x", first_day_end=datetime(2026, 9, 16, 9, 8, 0))
    text = tjr.format_summary(data, balance=9870.0, unrealized=50.0, open_count=1)

    # эквити 9920 минус PnL первых суток (-100) = 10020
    assert "Сводный баланс без первых суток: 10020.00" in text
    assert "Без первых суток" in text
