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
         patch("trading_journal_report.send_text", new=AsyncMock()) as mock_text, \
         patch("trading_journal_report.send_document", new=AsyncMock(return_value=True)) as mock_doc:
        await tjr.build_and_send_journal(chat_id=111, now=NOW)

    assert mock_text.await_count == 1
    assert "10050.00" in mock_text.await_args.args[2]
    assert mock_doc.await_count == 1
    assert mock_doc.await_args.args[1] == 111
    assert mock_doc.await_args.args[2].endswith(".html")
    assert b"AAAUSDT" in mock_doc.await_args.args[3]
