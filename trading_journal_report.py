"""
Журнал paper-сделок автотрейдинга: дважды в сутки (09:00 и 21:00 по Киеву)
бот сам шлёт админу сводку и HTML-файл с таблицей сделок в хронологии.
Источник -- таблица trade_events (см. trading_storage.record_trade_event).
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import aiohttp

from notifier import send_text, send_document
import live_trading
import trading_storage

logger = logging.getLogger(__name__)

KYIV_TZ = ZoneInfo("Europe/Kyiv")
REPORT_HOURS_KYIV = (9, 21)
START_BALANCE = 10000.0
RESET_AT_LABEL = "15.09.2026 09:08 UTC (12:08 Киев)"  # момент обнуления баланса до $10 000; обновлять при новом обнулении
# Первые сутки после обнуления шли по старой логике: сделки, закрытые до этого момента, в «без первых суток» не входят.
# Считаем по моменту ЗАКРЫТИЯ сделки (открытые и закрытые позже — уже «после»).
FIRST_DAY_END_UTC = datetime(2026, 9, 16, 9, 8, 0)
FIRST_DAY_END_LABEL = "16.09.2026 09:08 UTC (12:08 Киев)"

_HERE = os.path.dirname(os.path.abspath(__file__))
_TEMPLATE_PATH = os.path.join(_HERE, "trading_journal_template.html")
_SEED_PATH = os.path.join(_HERE, "trade_events_seed.txt")

_CLOSE_LABELS = {"closed_stop_loss": "Стоп", "closed_chandelier": "Трейлинг (TP4)", "closed_timeout_24h": "Таймаут 24ч"}
_TP_EVENTS = ("tp1_hit", "tp2_hit", "tp3_hit")


def _parse_ts(ts: str) -> datetime:
    return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")


def _fmt(dt: datetime | None) -> str | None:
    return dt.strftime("%d.%m %H:%M") if dt else None


def _group_positions(events: list[dict]) -> list[dict]:
    """Событие по символу открывает новую позицию, если предыдущая по нему уже закрыта."""
    open_by_symbol, positions = {}, []
    for e in sorted(events, key=lambda e: e["ts"]):
        ts = _parse_ts(e["ts"])
        pos = open_by_symbol.get(e["symbol"])
        if pos is None:
            pos = {"symbol": e["symbol"], "events": [], "tp1": None, "tp2": None, "tp3": None,
                   "exit_ts": None, "exit_type": None, "pnl": 0.0, "first_ts": ts, "raw": []}
            open_by_symbol[e["symbol"]] = pos
            positions.append(pos)
        pos["events"].append(ts)
        pos["raw"].append(e)
        pos["pnl"] += e["pnl"]
        if e["event"] in _TP_EVENTS:
            pos[e["event"][:3]] = ts
        elif e["event"] in _CLOSE_LABELS:
            pos["exit_ts"], pos["exit_type"] = ts, e["event"]
            del open_by_symbol[e["symbol"]]
    return sorted(positions, key=lambda p: p["first_ts"])


def _position_row(p: dict) -> dict:
    return {
        "symbol": p["symbol"], "tp1": _fmt(p["tp1"]), "tp2": _fmt(p["tp2"]), "tp3": _fmt(p["tp3"]),
        "exit_ts": _fmt(p["exit_ts"]), "exit_type": _CLOSE_LABELS.get(p["exit_type"]),
        "pnl": round(p["pnl"], 2), "open": p["exit_ts"] is None, "first_ts": _fmt(p["first_ts"]),
    }


def _summarize(positions: list[dict]) -> dict:
    closed = [p for p in positions if p["exit_ts"] is not None]
    wins = [p for p in closed if p["pnl"] > 0]
    return {
        "count": len(positions), "closed": len(closed), "open": len(positions) - len(closed),
        "wins": len(wins), "losses": len(closed) - len(wins),
        "winrate": round(len(wins) / len(closed) * 100, 1) if closed else 0.0,
        "total_pnl": round(sum(p["pnl"] for p in positions), 2),
    }


def _event_stats(events: list[dict]) -> dict:
    """Каждая нога -- отдельное событие: TP1/TP2/TP3, TP4 (закрытие трейлингом), стоп, таймаут."""
    def agg(names) -> dict:
        x = [e for e in events if e["event"] in names]
        return {"n": len(x), "sum": round(sum(e["pnl"] for e in x), 2)}

    return {
        "tp1": agg({"tp1_hit"}), "tp2": agg({"tp2_hit"}), "tp3": agg({"tp3_hit"}),
        "tp4": agg({"closed_chandelier"}),
        "tp_all": agg({"tp1_hit", "tp2_hit", "tp3_hit", "closed_chandelier"}),
        "stop": agg({"closed_stop_loss"}), "timeout": agg({"closed_timeout_24h"}),
    }


def _exit_stats(closed: list[dict]) -> dict:
    """Закрытые сделки по способу выхода; PnL -- по сделке целиком (все ноги)."""
    def block(kind: str) -> dict:
        x = [p for p in closed if p["exit_type"] == kind]
        return {"n": len(x), "sum": round(sum(p["pnl"] for p in x), 2), "wins": sum(1 for p in x if p["pnl"] > 0)}

    stop = block("closed_stop_loss")
    stops = [p for p in closed if p["exit_type"] == "closed_stop_loss"]
    without_tp = sum(1 for p in stops if p["tp1"] is None and p["tp2"] is None and p["tp3"] is None)
    stop.update({"without_tp": without_tp, "after_tp": len(stops) - without_tp})
    return {"stop": stop, "trail": block("closed_chandelier"), "timeout": block("closed_timeout_24h")}


def build_journal_data(events: list[dict], now: datetime, reset_at: str,
                       first_day_end: datetime = FIRST_DAY_END_UTC) -> dict:
    positions = _group_positions(events)
    def _in_first_day(p: dict) -> bool:
        return p["exit_ts"] is not None and p["exit_ts"] < first_day_end

    first_day = [p for p in positions if _in_first_day(p)]
    after = [p for p in positions if not _in_first_day(p)]
    after_events = [e for p in after for e in p["raw"]]
    cutoff = now - timedelta(hours=24)
    cutoff_str = cutoff.strftime("%Y-%m-%d %H:%M:%S")
    recent = [p for p in positions if any(t >= cutoff for t in p["events"])]
    return {
        "generated_at": now.strftime("%d.%m.%Y %H:%M UTC"),
        "reset_at": reset_at,
        "full": {
            "summary": _summarize(positions), "positions": [_position_row(p) for p in positions],
            "events": _event_stats(events), "exits": _exit_stats([p for p in positions if p["exit_ts"]]),
        },
        "first_day": {"count": len(first_day), "pnl": round(sum(p["pnl"] for p in first_day), 2),
                      "end_label": FIRST_DAY_END_LABEL},
        "after_first_day": {
            "summary": _summarize(after), "positions": [_position_row(p) for p in after],
            "events": _event_stats(after_events), "exits": _exit_stats([p for p in after if p["exit_ts"]]),
        },
        "last24h": {
            "summary": _summarize(recent), "positions": [_position_row(p) for p in recent],
            "cutoff": cutoff.strftime("%d.%m %H:%M UTC"),
            "events": _event_stats([e for e in events if e["ts"] >= cutoff_str]),
            "exits": _exit_stats([p for p in positions if p["exit_ts"] and p["exit_ts"] >= cutoff]),
        },
    }


def render_journal_html(data: dict) -> str:
    with open(_TEMPLATE_PATH, encoding="utf-8") as f:
        template = f.read()
    return (template
            .replace("__DATA_JSON__", json.dumps(data, ensure_ascii=True, separators=(",", ":")))
            .replace("__RESET_AT__", data["reset_at"]))


def format_summary(data: dict, balance: float, unrealized: float = 0.0, open_count: int = 0) -> str:
    def block(title: str, s: dict, ev: dict) -> str:
        return (
            f"*{title}*\n"
            f"Сделок: {s['count']} (закрыто {s['closed']}, открыто {s['open']})\n"
            f"Прибыльных {s['wins']} / убыточных {s['losses']} — winrate {s['winrate']:.0f}%\n"
            f"Ноги take profit: {ev['tp_all']['n']} ({ev['tp_all']['sum']:+.2f}) · Стопы: {ev['stop']['n']} ({ev['stop']['sum']:+.2f})\n"
            f"PnL: {s['total_pnl']:+.2f} USDT"
        )

    equity = balance + unrealized
    first_day = data["first_day"]
    equity_after = equity - first_day["pnl"]
    return (
        f"📒 *Живой журнал автотрейдинга* — {data['generated_at']}\n\n"
        + f"*Сводный баланс без первых суток: {equity_after:.2f} USDT ({(equity_after / START_BALANCE - 1) * 100:+.1f}% к {START_BALANCE:.0f})*\n"
        + f"(эквити {equity:.2f} минус PnL первых суток {first_day['pnl']:+.2f}; первые сутки — сделки, закрытые до {first_day['end_label']}: {first_day['count']} шт.)\n\n"
        + block("Без первых суток", data["after_first_day"]["summary"], data["after_first_day"]["events"]) + "\n\n"
        + block(f"С обнуления баланса — {data['reset_at']}", data["full"]["summary"], data["full"]["events"]) + "\n\n"
        + block("Последние 24 часа", data["last24h"]["summary"], data["last24h"]["events"]) + "\n\n"
        + f"Баланс (только закрытые части сделок): {balance:.2f} USDT\n"
        + f"Нереализованный PnL по открытым ({open_count}): {unrealized:+.2f} USDT\n"
        + f"*Эквити: {equity:.2f} USDT ({(equity / START_BALANCE - 1) * 100:+.1f}% к {START_BALANCE:.0f})*\n"
        + "Таблица со всеми сделками — файлом ниже."
    )


def parse_seed_lines(lines) -> list[tuple]:
    rows = []
    for line in lines:
        parts = line.split()
        if len(parts) == 5:
            rows.append((f"{parts[0]} {parts[1]}", parts[2], parts[3], float(parts[4])))
    return rows


def load_seed_events() -> list[tuple]:
    with open(_SEED_PATH, encoding="utf-8") as f:
        return parse_seed_lines(f)


def seconds_until_next_report(now_utc: datetime | None = None) -> float:
    now = (now_utc or datetime.now(timezone.utc)).astimezone(KYIV_TZ)
    candidates = []
    for day_offset in (0, 1):
        day = (now + timedelta(days=day_offset)).date()
        for hour in REPORT_HOURS_KYIV:
            candidates.append(datetime(day.year, day.month, day.day, hour, tzinfo=KYIV_TZ))
    return min((c - now).total_seconds() for c in candidates if c > now)


async def build_and_send_journal(chat_id: int, now: datetime | None = None):
    now = now or datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
    events = trading_storage.get_trade_events(chat_id)
    balance = trading_storage.get_paper_balance(chat_id) or 0.0
    unrealized, open_count = live_trading.get_unrealized_pnl(chat_id)
    data = build_journal_data(events, now, RESET_AT_LABEL)

    async with aiohttp.ClientSession() as session:
        await send_text(session, chat_id, format_summary(data, balance, unrealized, open_count))
        filename = f"journal_{now.strftime('%Y%m%d_%H%M')}.html"
        await send_document(session, chat_id, filename, render_journal_html(data).encode("utf-8"))

    s = data["full"]["summary"]
    logger.info(f"Журнал автотрейдинга отправлен chat_id={chat_id}: сделок={s['count']}, PnL={s['total_pnl']:.2f}")


async def trading_journal_report_loop(chat_id: int):
    """Бесконечный цикл: ждёт 09:00/21:00 Киев, шлёт сводку и HTML-журнал."""
    while True:
        await asyncio.sleep(seconds_until_next_report())
        try:
            await build_and_send_journal(chat_id)
        except Exception as e:
            logger.exception(f"Ошибка формирования журнала автотрейдинга: {e}")
        await asyncio.sleep(60)  # защита от повторного срабатывания при дрожании таймера
