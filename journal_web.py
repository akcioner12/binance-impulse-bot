"""
HTTP-эндпоинт живого журнала автотрейдинга -- альтернатива Claude-артефакту,
который требует открытой сессии Claude Code и живёт максимум 7 дней (session-only
CronCreate). Страница строится заново на КАЖДЫЙ запрос из текущего состояния БД,
поэтому всегда актуальна -- обновлять её руками/по расписанию не нужно.

Телеграм-отчёт 2 раза в сутки (09:00/21:00 Киев, trading_journal_report_loop)
остаётся отдельно и не меняется -- это для push-уведомления с числами, здесь --
постоянная ссылка для быстрого визуального просмотра в любой момент.
"""
import asyncio
from datetime import datetime, timezone

from aiohttp import web

from config import ADMIN_CHAT_ID
import live_trading
import trading_journal_report as tjr
import trading_storage


async def build_journal_html_now(chat_id: int = ADMIN_CHAT_ID) -> str:
    events = trading_storage.get_trade_events(chat_id)
    balance = trading_storage.get_paper_balance(chat_id) or 0.0
    unrealized, open_count = live_trading.get_unrealized_pnl(chat_id)
    now = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
    data = tjr.build_journal_data(events, now, tjr.RESET_AT_LABEL, balance=balance, unrealized=unrealized, open_count=open_count)
    return tjr.render_journal_html(data)


async def journal_handler(request: web.Request) -> web.Response:
    html = await build_journal_html_now()
    return web.Response(text=html, content_type="text/html")


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/", journal_handler)
    app.router.add_get("/journal", journal_handler)
    return app


async def run_web_server(port: int):
    """Бесконечная задача для asyncio.gather -- держит HTTP-сервер живым, пока не отменят."""
    runner = web.AppRunner(create_app())
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()
