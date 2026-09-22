from unittest.mock import patch

import pytest
from aiohttp.test_utils import TestClient, TestServer

import journal_web


@pytest.mark.asyncio
async def test_build_journal_html_now_reads_live_data_and_renders():
    events = [{"ts": "2026-09-20 10:00:00", "symbol": "AAAUSDT", "event": "tp1_hit", "pnl": 10.0}]
    with patch("journal_web.trading_storage.get_trade_events", return_value=events), \
         patch("journal_web.trading_storage.get_paper_balance", return_value=9500.0), \
         patch("journal_web.live_trading.get_unrealized_pnl", return_value=(123.45, 5)):
        html = await journal_web.build_journal_html_now(chat_id=111)

    assert "AAAUSDT" in html
    assert "9500" in html


@pytest.mark.asyncio
async def test_journal_handler_serves_html_over_http():
    with patch("journal_web.trading_storage.get_trade_events", return_value=[]), \
         patch("journal_web.trading_storage.get_paper_balance", return_value=10000.0), \
         patch("journal_web.live_trading.get_unrealized_pnl", return_value=(0.0, 0)):
        app = journal_web.create_app()
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/journal")
            body = await resp.text()

    assert resp.status == 200
    assert resp.content_type == "text/html"
    assert "Живой журнал" in body


@pytest.mark.asyncio
async def test_root_path_also_serves_journal():
    with patch("journal_web.trading_storage.get_trade_events", return_value=[]), \
         patch("journal_web.trading_storage.get_paper_balance", return_value=10000.0), \
         patch("journal_web.live_trading.get_unrealized_pnl", return_value=(0.0, 0)):
        app = journal_web.create_app()
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/")

    assert resp.status == 200
