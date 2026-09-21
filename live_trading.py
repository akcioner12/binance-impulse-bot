"""
Живая оркестрация автотрейдинга: от найденного импульса до открытой/закрытой
paper-позиции. Состояние (ожидающие сетапы, открытые позиции) хранится в
памяти процесса, keyed по символу.

НЕ подключён к живому потоку цен main.py -- см. отдельный план подключения.
"""

import logging
from datetime import datetime, timedelta, timezone

import trading_storage
import impulse_analysis
import magnet_levels as magnet_levels_module
import entry_engine
import position_manager
import order_executor
import market_data
import indicators
import trade_signal_ux
from notifier import send_text
from analyzer import build_exchange_link

logger = logging.getLogger(__name__)

_pending_setups: dict[str, dict] = {}
_open_positions: dict[str, dict] = {}
_last_prices: dict[str, float] = {}  # последний тик по символам с открытой позицией -- для нереализованного PnL в отчёте

# Бронь слота на время анализа импульса (между проверкой лимита и постановкой
# сетапа в _pending_setups в execute_setup) -- прод-инцидент 14.09.2026:
# DailyHighTracker при холодном старте выстрелил 41 сигналом почти одновременно,
# и каждый вызов handle_new_impulse читал len(get_open_positions()) НЕЗАВИСИМО,
# до того как хоть один успел что-то забронировать -- max_concurrent_trades
# был массово превышен (22 позиции вместо заданного лимита). Добавление в это
# множество происходит синхронно, ДО первого await, поэтому конкурентные вызовы
# для других символов видят актуальную занятость немедленно.
_reserved_symbols: set[str] = set()

# Шаг, с которым обновляется ATR у долго ждущего сетапа. Триггеры считают
# дистанцию отката от ATR на момент старта мониторинга -- если цена уходит
# далеко без отката, эта величина устаревает относительно текущей волатильности
# (которая обычно растёт вместе с ценой), и триггер рискует сработать на
# обычном шуме нового масштаба вместо настоящего разворота.
ATR_REFRESH_STEP_PCT = 50.0

# Очередь уведомлений о действиях бота по открытым позициям (TP, безубыток+,
# включение трейлинга, закрытие) -- копится синхронно внутри _process_open_
# position_tick (там нет доступа к event loop для отправки в Telegram) и
# вычитывается main.py на каждом тике через pop_notifications().
_notification_queue: list[dict] = []

DEFAULT_ATR_MULTIPLIER = 1.5  # continuation-входы (не менялся)

# 20.09.2026 (622 исторических + 80 живых сигналов, движок бота): стоп 2.0 ATR1ч вместо 1.5
# для входов на разворот -- доля "стоп без единого TP" 45% -> 36%, avgR +1.00 -> +1.05
# (живые +0.04 -> +0.21); при постоянном риске позиция чуть меньше. 2.5 -- 31%, но R не
# выше; 3.0 хуже. Ожидание более глубокого отката/подтверждения входа НЕ помогло.
REVERSAL_ATR_MULTIPLIER = 2.0

# Защита от многоволновых манипуляций (прод-инцидент 12-13.09: LSKUSDT/POWRUSDT/
# ARKUSDT/VTHOUSDT -- все 5 убыточных сделок за ночь оказались РАННИМИ волнами
# продолжающегося пампа, а не его финальным разворотом: первый откат выглядел
# как истощение, бот заходил в шорт на реальном (не рыночном) трейлинг-откате,
# но манипуляция возобновлялась новой волной и выбивала стоп). Чем больше раз
# подряд символ уже сигналил за последние WAVE_LOOKBACK_HOURS часов, тем меньше
# доверия к тому, что именно ЭТА волна -- последняя.
WAVE_LOOKBACK_HOURS = 4
WAVE_SIZE_MULTIPLIERS = {0: 1.0, 1: 0.5}  # wave_count >= 2 -> сетап пропускается

# Ретроспектива 13-14.09.2026 (2833 эпизода за июль-сентябрь): фейд импульса-пампа
# сам по себе даёт эдж около нуля (avgR +0.13 на всех, но климакс/RSI-дивергенция
# из classify_impulse() на пампах скорее ВРЕДЯТ, а не помогают). Единственный
# сигнал, который монотонно и статистически значимо разделяет прибыльные и
# убыточные пампы -- экстремальность funding rate по модулю (топ-20% -> avgR
# +0.46, t=4.94): либо перегретые лонги на плече (long squeeze), либо шорты,
# продолжающие платить несмотря на рост (короткий сквиз без топлива). Дампов
# это не касается -- там эдж сильный и без дополнительных фильтров.
PUMP_FUNDING_EXTREME_THRESHOLD = 0.00012

# Находка 16.09.2026 (бэктест 2,5 мес., 257 сделок, "зависшие" сделки):
# пампы (шорт), простоявшие 24ч+ взяв МАКСИМУМ 1 тейк и не закрывшись,
# в среднем едут дальше ПРОТИВ нас (принудительный выход на 24ч дал бы
# +$2894 за период вместо естественного досиживания, n=25). Для дампов
# (лонг) эффект ОБРАТНЫЙ -- досиживание выгоднее (+$1554, n=43) -- поэтому
# правило применяется ТОЛЬКО к пампам.
PUMP_STUCK_TIMEOUT_HOURS = 24

# Аналогичная находка 14.09.2026 (сессия 4, dump_signals_and_outcomes.py) для
# МЕДЛЕННЫХ (многодневных) дампов, которые ловит новый DailyHighTracker:
# эпизоды, где входная 15м-свеча -- объёмный climax, дают avgR +0.06 (t=0.40,
# статистически неотличимо от нуля) на 125 из 791 проверенных эпизодов, тогда
# как остальные 666 дают +1.09 (t=8.52) -- почти весь эдж сохраняется, если
# такие climax-эпизоды просто не торговать.

# Находка 16-17.09.2026 (бэктест 140 дамп-сделок, 2,5 мес., живой пример
# POWRUSDT 17.09): DailyHighTracker сравнивает цену со СКОЛЬЗЯЩИМ 10-дневным
# максимумом, который не сбрасывается, пока не пробит заново -- если сильное
# движение было несколько дней назад, а с тех пор цена просто колеблется в
# консолидации, детектор может сработать на СТАРЫЙ пик, а не на свежий обвал.
# Бэктест подтвердил: "свежие" якори (пик <1.5 дня назад, без отскока >=15%)
# дают avgR +1.168, "устаревшие" -- всего +0.471 (тоже в плюс, но вдвое
# слабее). Вместо полного отказа от устаревших сигналов -- уменьшаем размер,
# чтобы сохранить часть эджа, а не терять его целиком.
DUMP_ANCHOR_STALE_DAYS_THRESHOLD = 1.5
DUMP_ANCHOR_STALE_BOUNCE_THRESHOLD_PCT = 15.0
DUMP_ANCHOR_STALE_SIZE_MULTIPLIER = 0.5


# Находка 17.09.2026 (257 сделок, 2,5 мес.): эдж у дампов стабильно сильнее
# (avgR ~0.7-0.9), чем у пампов (~0.1-0.5 даже после фильтра funding).
# Асимметричный риск 2%/4% вместо равномерных 3%/3% (при том же среднем
# риске на портфель) даёт +$8019 (+22%) за период. Заменяет единый
# profile["risk_percent"] ТОЛЬКО для сайзинга автотрейдинг-позиций.
# 20.09.2026: живые пампы за 5 дней -0.45R (n=41) против +0.46R в ретроспективе
# (часть -- баг funding, исправлен там же); риск пампов снижен 2% -> 1% до
# накопления данных. Бэктест 74 дн.: пампы дают +10% и сглаживают просадки дампов,
# поэтому не отключены совсем.
PUMP_RISK_PERCENT = 1.0
DUMP_RISK_PERCENT = 4.0


def _risk_percent_for_direction(direction: str) -> float:
    return PUMP_RISK_PERCENT if direction == "up" else DUMP_RISK_PERCENT


# Находка 17.09.2026 (257 сделок, 2,5 мес.): раздвинутая сетка TP1-3 на
# дампах (R=1.5/3/5 вместо 1/2/3, тот же сплит долей 15/20/25%) даёт +21%
# PnL по дампам ($36792 против $30357 за период) -- эдж у дампов сильнее,
# есть смысл давать прибыли бежать дальше. На пампах наоборот текущая
# сетка (R=1/2/3) лучше. Применяется только к reversal-сетапам (fade).
PUMP_TP_R_MULTIPLES = (1.0, 2.0, 3.0)
DUMP_TP_R_MULTIPLES = (1.0, 3.0, 5.0)  # 20.09.2026: TP1 1.5R -> 1.0R (до TP1 53% -> ~57% при той же R; 3R/5R оставлены); до 20.09 было (1.5, 3.0, 5.0), до 17.09 (1.0, 2.0, 3.0)


def _tp_r_multiples_for_direction(direction: str) -> tuple[float, float, float]:
    return PUMP_TP_R_MULTIPLES if direction == "up" else DUMP_TP_R_MULTIPLES


# Чёрный список монет (18.09.2026, расширен с топ-10 до топ-20 худших по
# итоговому PnL): на бэктесте 2,5 мес. (725 сделок) эти 7 символов стабильно
# убыточны в ОБЕИХ половинах периода (01.07-10.08 и 10.08-12.09) -- не
# разовая серия стопов, а устойчивый паттерн. Исключение из торговли даёт
# +$5554.29 (+2.46%) к итоговому PnL за период (было +$3760.15/+1.7% на
# первых 4). Остальные кандидаты не включены -- либо недостаточно сделок в
# одной из половин периода, либо знак результата меняется между половинами
# (например HANAUSDT, VVVUSDT, POWERUSDT), то есть убыток был разовым.
SYMBOL_BLACKLIST = {
    "CLOUSDT", "IDOLUSDT", "ZEREBROUSDT", "NIGHTUSDT",
    "ARXUSDT", "BBUSDT", "KAITOUSDT",
}

# 20.09.2026: живые повторные входы по пампам сразу после стопа по той же монете --
# -0.53R (n=17, -$985 за 5 дней; серии AKE x4, LSK x3): если памп продолжает идти
# и выбил стоп, тезис на разворот опровергнут. Для дампов повторы после стопа в
# плюсе (+0.09R) -- правило только для пампов. История по эпизодам (2,5 мес.) этого
# эффекта НЕ показывает (повторные эпизоды пампов +0.48R против +0.49R первых) --
# вывод неубедительный, пересмотреть через 1-2 недели данных.
PUMP_STOP_COOLDOWN_HOURS = 24


def _is_dump_anchor_stale(daily_candles: list[dict]) -> bool:
    """
    Смотрит на последние ~12 дневных свечей: где был максимум (пик) и был ли
    после него заметный отскок вверх (>=DUMP_ANCHOR_STALE_BOUNCE_THRESHOLD_PCT
    от локального дна) прежде, чем цена снова просела. Если пик достаточно
    старый (>=DUMP_ANCHOR_STALE_DAYS_THRESHOLD дней) И был такой отскок --
    это не свежий обвал, а старая консолидация.
    """
    recent = daily_candles[-12:]
    if len(recent) < 3:
        return False

    peak_idx = max(range(len(recent)), key=lambda i: recent[i]["high"])
    peak_value = recent[peak_idx]["high"]
    days_ago = len(recent) - 1 - peak_idx
    if days_ago < DUMP_ANCHOR_STALE_DAYS_THRESHOLD:
        return False

    max_bounce_pct = 0.0
    local_low = peak_value
    for c in recent[peak_idx + 1:]:
        local_low = min(local_low, c["low"])
        if local_low > 0:
            bounce = (c["high"] - local_low) / local_low * 100
            max_bounce_pct = max(max_bounce_pct, bounce)

    return max_bounce_pct >= DUMP_ANCHOR_STALE_BOUNCE_THRESHOLD_PCT


# Ретроспектива 14-15.09.2026 (сессия 4, continuation_backtest.py): ветка
# continuation (ставка "импульс продолжится", вход ПО тренду) ни разу не
# проверялась на исторических данных до этого. Continuation на дампах (шорт
# по тренду падения) даёт avgR -0.339 (t=-2.72, статистически значимый
# убыток на 197 эпизодах) -- не торгуется вовсе. Continuation на пампах
# статистически нейтрален (avgR -0.005, t=-0.08, чистый шум) -- не трогаем,
# по решению пользователя (не вредит, хоть и не помогает).


async def handle_new_impulse(
    session, chat_id: int, symbol: str, exchange: str, direction: str,
    current_price: float, window_start_price: float,
) -> dict | None:
    """
    Вызывается один раз на новый импульс (первый уровень ImpulseSignal).
    Возвращает None, если автотрейдинг неприменим для этого символа сейчас.
    """
    profile = trading_storage.get_profile(chat_id)
    if profile is None or not profile["is_active"]:
        return None
    if symbol in SYMBOL_BLACKLIST:
        return None
    if direction == "up" and trading_storage.had_recent_stop_out(
        chat_id, symbol, "short",
        (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=PUMP_STOP_COOLDOWN_HOURS)).strftime("%Y-%m-%d %H:%M:%S"),
    ):
        logger.info(f"Автотрейдинг [{symbol}]: памп пропущен -- по монете был стоп за последние {PUMP_STOP_COOLDOWN_HOURS}ч")
        return None
    if (
        symbol in _pending_setups or symbol in _open_positions
        or symbol in _reserved_symbols
    ):
        return None
    # Бронируем слот СИНХРОННО, до первого await -- иначе конкурентные вызовы
    # для других символов (см. _reserved_symbols выше) читают тот же счётчик
    # открытых позиций и все проходят проверку, пока ни один ещё не забронировал.
    if len(trading_storage.get_open_positions(chat_id)) + len(_reserved_symbols) >= profile["max_concurrent_trades"]:
        return None
    _reserved_symbols.add(symbol)

    try:
        analysis = await impulse_analysis.analyze_impulse(session, symbol, exchange, direction, current_price)
        classification = analysis["classification"]

        if direction == "up" and classification == "reversal":
            if abs(analysis["funding_rate"]) < PUMP_FUNDING_EXTREME_THRESHOLD:
                return None

        if direction == "down" and classification == "reversal":
            if analysis["is_climax"]:
                return None

        if direction == "down" and classification == "continuation":
            return None

        magnet_levels_list = []
        if classification == "reversal":
            # Считаем ЗАРАНЕЕ (не в execute_setup после подтверждения), чтобы
            # сообщение "Найден сетап" показывало реальные уровни, а не всегда
            # "—" (прод-баг 14.09.2026: magnet_levels считался только постфактум).
            daily_candles = await market_data.fetch_klines(session, exchange, symbol, "1d", limit=90)
            weekly_candles = await market_data.fetch_klines(session, exchange, symbol, "1w", limit=52)
            magnet_levels_list = magnet_levels_module.find_magnet_levels(daily_candles, weekly_candles, current_price, direction)
            analysis["magnet_levels"] = magnet_levels_list
            if direction == "down":
                analysis["stale_anchor"] = _is_dump_anchor_stale(daily_candles)

        signal_id = trading_storage.create_trade_signal(
            chat_id=chat_id, symbol=symbol, exchange=exchange,
            impulse_direction=direction, classification=classification,
        )

        await trade_signal_ux.announce_and_execute(
            session, chat_id, symbol, exchange, direction, classification,
            current_price, window_start_price, profile, analysis, signal_id,
            magnet_levels=magnet_levels_list, execute_fn=execute_setup,
        )
        return {"classification": classification, "signal_id": signal_id}
    finally:
        _reserved_symbols.discard(symbol)


def _compute_wave_size_multiplier(chat_id: int, symbol: str, signal_id: int) -> float | None:
    """
    Считает, сколько раз символ уже сигналил за последние WAVE_LOOKBACK_HOURS
    часов (включая текущий сигнал), и возвращает множитель размера позиции.
    None означает "не входить вообще" -- третья и более поздняя волна подряд.
    """
    signal = trading_storage.get_trade_signal(signal_id)
    signal_time = datetime.strptime(signal["created_at"], "%Y-%m-%d %H:%M:%S")
    since = (signal_time - timedelta(hours=WAVE_LOOKBACK_HOURS)).strftime("%Y-%m-%d %H:%M:%S")
    wave_count = trading_storage.count_recent_signals(chat_id, symbol, since) - 1  # без текущего
    return WAVE_SIZE_MULTIPLIERS.get(wave_count)


async def execute_setup(
    session, chat_id: int, symbol: str, exchange: str, direction: str, classification: str,
    current_price: float, window_start_price: float, profile: dict, analysis: dict, signal_id: int,
) -> dict:
    """
    Реально исполняет сетап -- вызывается из trade_signal_ux.announce_and_execute()
    сразу после создания сигнала (подтверждение и 5-минутное ожидание убраны 20.09.2026).
    """
    size_multiplier = _compute_wave_size_multiplier(chat_id, symbol, signal_id)
    if size_multiplier is None:
        trading_storage.update_trade_signal_status(signal_id, "expired")
        logger.info(f"Автотрейдинг [{symbol}]: сетап пропущен -- уже 2+ волны за последние {WAVE_LOOKBACK_HOURS}ч")
        return {"classification": classification, "signal_id": signal_id, "skipped": "multiwave_protection"}

    if analysis.get("stale_anchor"):
        size_multiplier *= DUMP_ANCHOR_STALE_SIZE_MULTIPLIER

    if classification == "continuation":
        return await _open_continuation_position(
            session, chat_id, symbol, exchange, direction, current_price, profile, analysis, signal_id, size_multiplier,
        )
    return await _create_pending_reversal_setup(
        session, chat_id, symbol, exchange, direction, current_price,
        window_start_price, profile, analysis, signal_id, size_multiplier,
    )


_FILL_STAGE_LABELS = {
    "part1": "🔹 Часть 1 из 2\n\n",
    "part2_merged": "🔹 Часть 2 из 2 (объединена с частью 1 — показан итоговый объём)\n\n",
    "part2_independent": "🔹 Часть 2 из 2 (часть 1 уже закрыта — это отдельная позиция)\n\n",
}


def format_entry_report(symbol: str, exchange: str, snapshot: dict, also_on_bybit: bool = False) -> str:
    """Отчёт пользователю о факте входа в сделку -- цена, объём, SL, сетка TP."""
    direction_word = "🟢 LONG" if snapshot["direction"] == "long" else "🔴 SHORT"
    fill_stage_line = _FILL_STAGE_LABELS.get(snapshot.get("fill_stage"), "")
    tp_lines = "\n".join(
        f"TP{idx}: `{tp['level']:.6g}` ({tp['size_pct']}%)"
        for idx, tp in enumerate(snapshot["take_profits"], start=1)
    )
    link_line = f"[Открыть на {exchange}]({build_exchange_link(exchange, symbol)})"
    if also_on_bybit and exchange == "Binance":
        link_line += f" | [Открыть на Bybit]({build_exchange_link('Bybit', symbol)})"
    return (
        f"✅ *Вход в сделку: {symbol}* [{exchange}]\n\n"
        f"{fill_stage_line}"
        f"Направление: {direction_word}\n"
        f"Цена входа: `{snapshot['avg_entry_price']:.6g}`\n"
        f"Объём: `{snapshot['quantity']:.6g}`\n"
        f"SL: `{snapshot['stop_loss']:.6g}`\n"
        f"{tp_lines}\n"
        f"TP4: трейлинг (Chandelier), {snapshot['tp4_size_pct']}% объёма\n\n"
        f"Риск на сделку: `{snapshot['risk_amount']:.2f}`\n\n"
        f"{link_line}"
    )


async def _open_continuation_position(
    session, chat_id: int, symbol: str, exchange: str, direction: str, current_price: float,
    profile: dict, analysis: dict, signal_id: int, size_multiplier: float = 1.0,
) -> dict:
    trade_direction = position_manager.determine_trade_direction(direction, "continuation")
    stop_loss = position_manager.calculate_stop_loss(
        current_price, trade_direction, profile["sl_method"],
        analysis["atr_1h"], DEFAULT_ATR_MULTIPLIER, profile["sl_fixed_percent"],
    )
    balance = trading_storage.get_paper_balance(chat_id) or 0.0
    size = position_manager.calculate_position_size(
        balance, _risk_percent_for_direction(direction), current_price, stop_loss
    ) * size_multiplier

    result = order_executor.open_paper_position(
        chat_id=chat_id, symbol=symbol, exchange=exchange, direction=trade_direction,
        fills=[(current_price, size)], sl_method=profile["sl_method"],
        atr_1h=analysis["atr_1h"], atr_multiplier=DEFAULT_ATR_MULTIPLIER,
        fixed_percent=profile["sl_fixed_percent"], tp_split_preset=profile["tp_split_preset"],
        breakeven_after_tp=profile["breakeven_after_tp"],
    )
    state = order_executor.OpenPositionState(
        position_id=result["position_id"], direction=trade_direction,
        avg_entry_price=result["avg_entry_price"], quantity=result["quantity"],
        stop_loss=result["stop_loss"], take_profits=result["take_profits"],
        breakeven_after_tp=profile["breakeven_after_tp"],
    )
    _open_positions[symbol] = {
        "chat_id": chat_id, "state": state, "atr_1h": analysis["atr_1h"],
        "opened_at": datetime.now(timezone.utc).replace(tzinfo=None),
    }
    trading_storage.update_trade_signal_status(signal_id, "executed")

    snapshot = get_position_snapshot(symbol)
    if snapshot is not None:
        await send_text(session, chat_id, format_entry_report(symbol, exchange, snapshot))

    return {"classification": "continuation", "signal_id": signal_id, "position_id": result["position_id"]}


async def _create_pending_reversal_setup(
    session, chat_id: int, symbol: str, exchange: str, direction: str, current_price: float,
    window_start_price: float, profile: dict, analysis: dict, signal_id: int, size_multiplier: float = 1.0,
) -> dict:
    # magnet_levels обычно уже посчитан заранее в handle_new_impulse (до отправки
    # сообщения с подтверждением) -- переиспользуем, чтобы не дублировать сетевые
    # запросы; считаем заново только если сюда попали в обход этого пути.
    levels = analysis.get("magnet_levels")
    if levels is None:
        daily_candles = await market_data.fetch_klines(session, exchange, symbol, "1d", limit=90)
        weekly_candles = await market_data.fetch_klines(session, exchange, symbol, "1w", limit=52)
        levels = magnet_levels_module.find_magnet_levels(daily_candles, weekly_candles, current_price, direction)

    trade_direction = position_manager.determine_trade_direction(direction, "reversal")
    estimated_stop_loss = position_manager.calculate_stop_loss(
        current_price, trade_direction, profile["sl_method"],
        analysis["atr_1h"], REVERSAL_ATR_MULTIPLIER, profile["sl_fixed_percent"],
    )
    balance = trading_storage.get_paper_balance(chat_id) or 0.0
    total_size = position_manager.calculate_position_size(
        balance, _risk_percent_for_direction(direction), current_price, estimated_stop_loss
    ) * size_multiplier

    _pending_setups[symbol] = {
        "chat_id": chat_id, "exchange": exchange, "signal_id": signal_id,
        "impulse_direction": direction, "window_start_price": window_start_price,
        # Точка отсчёта потолка ожидания -- НЕ window_start_price детектора (он может
        # быть сильно устаревшим, например "цена ~24ч назад"), а цена на момент, когда
        # этот конкретный сетап реально начал мониториться. Ставится лениво на первом
        # тике в _process_pending_setup_tick, аналогично extreme_price у триггеров.
        "cap_reference_price": None, "last_atr_refresh_price": None,
        "trigger_part1": entry_engine.create_part1_trigger(direction, analysis["atr_15m"]),
        "trigger_part2": entry_engine.create_part2_trigger(direction, analysis["atr_15m"]),
        "part_size": total_size / 2,
        "atr_1h": analysis["atr_1h"], "magnet_levels": levels, "profile": profile,
    }
    return {"classification": "reversal", "signal_id": signal_id, "magnet_levels": levels}


def get_position_snapshot(symbol: str) -> dict | None:
    """
    Снимок открытой позиции для отчёта пользователю о факте входа в сделку --
    цена, объём, SL, сетка TP1-3 (TP4 не фиксирован -- трейлинг, только его доля).
    """
    entry = _open_positions.get(symbol)
    if entry is None:
        return None
    state = entry["state"]
    tp3_total_pct = sum(tp["size_pct"] for tp in state.take_profits)
    return {
        "chat_id": entry["chat_id"],
        "direction": state.direction,
        "avg_entry_price": state.avg_entry_price,
        "quantity": state.quantity,
        "stop_loss": state.stop_loss,
        "take_profits": [{"level": tp["level"], "size_pct": tp["size_pct"]} for tp in state.take_profits],
        "tp4_size_pct": 100 - tp3_total_pct,
        "risk_amount": state.quantity * abs(state.avg_entry_price - state.stop_loss),
        "fill_stage": entry.get("fill_stage"),
    }


def get_unrealized_pnl(chat_id: int) -> tuple[float, int]:
    """Нереализованный PnL открытых позиций chat_id по последним тикам и число этих позиций."""
    total, count = 0.0, 0
    for symbol, entry in _open_positions.items():
        if entry["chat_id"] != chat_id:
            continue
        state = entry["state"]
        count += 1
        price = _last_prices.get(symbol)
        if price is not None:
            total += order_executor.calculate_position_pnl(state.direction, state.avg_entry_price, price, state.remaining_quantity)
    return total, count


def handle_price_tick(symbol: str, price: float) -> list[str] | None:
    """
    Вызывается на каждый тик цены символа. Возвращает список произошедших
    событий или None, если по символу нет ни ожидающего сетапа, ни открытой
    позиции.

    Символ может одновременно быть и в _pending_setups, и в _open_positions
    (часть 1 уже открыла позицию, часть 2 ещё ждёт свой триггер независимо) --
    поэтому обе ветки проверяются на каждом тике, а не взаимоисключающе.
    Сначала проверяется ожидающий сетап (часть 2 может слить в позицию на
    этом же тике), затем состояние (возможно, уже обновлённой) открытой позиции.
    """
    events = []

    if symbol in _open_positions:
        _last_prices[symbol] = price

    if symbol in _pending_setups:
        pending_events = _process_pending_setup_tick(symbol, price)
        if pending_events:
            events.extend(pending_events)

    if symbol in _open_positions:
        open_events = _process_open_position_tick(symbol, price)
        if open_events:
            events.extend(open_events)

    return events or None


def restore_open_positions() -> int:
    """
    Восстанавливает открытые позиции из БД в _open_positions при старте бота.
    Состояние сделки (SL/TP/Chandelier) живёт только в памяти процесса и не
    переживает рестарт иначе -- без этого любой редеплой во время открытой
    сделки "осиротит" её навсегда (см. прод-инцидент 12-13.09: VTHOUSDT/
    POWRUSDT остались висеть status='open' без какого-либо мониторинга).
    Возвращает число восстановленных позиций.
    """
    restored = 0
    for row in trading_storage.get_all_open_positions():
        tp_r_multiples_raw = row["tp_r_multiples"]
        r_multiples = (
            tuple(float(x) for x in tp_r_multiples_raw.split(","))
            if tp_r_multiples_raw else (1.0, 2.0, 3.0)
        )
        take_profits = position_manager.calculate_take_profits(
            row["avg_entry_price"], row["original_stop_loss"], row["direction"], row["tp_split_preset"],
            r_multiples=r_multiples,
        )
        state = order_executor.OpenPositionState(
            position_id=row["id"], direction=row["direction"],
            avg_entry_price=row["avg_entry_price"], quantity=row["quantity"],
            stop_loss=row["stop_loss"], take_profits=take_profits,
            breakeven_after_tp=row["breakeven_after_tp"],
        )
        for idx, filled_key in enumerate(("tp1_filled", "tp2_filled", "tp3_filled")):
            if idx < len(state.take_profits):
                state.take_profits[idx]["filled"] = bool(row[filled_key])
        state.remaining_quantity = row["remaining_quantity"]
        state.tp_hit_count = int(row["tp1_filled"]) + int(row["tp2_filled"]) + int(row["tp3_filled"])

        if row["chandelier_active"]:
            chandelier = position_manager.ChandelierTrailingStop(direction=row["direction"])
            chandelier.extreme_price = row["chandelier_extreme_price"]
            chandelier.stop_price = row["chandelier_stop_price"]
            state.chandelier = chandelier

        opened_at = None
        if row["opened_at"]:
            try:
                opened_at = datetime.strptime(row["opened_at"], "%Y-%m-%d %H:%M:%S")
            except ValueError:
                opened_at = None

        _open_positions[row["symbol"]] = {
            "chat_id": row["chat_id"], "state": state, "atr_1h": row["atr_1h"], "opened_at": opened_at,
        }
        restored += 1
    return restored


def _persist_position_progress(state: order_executor.OpenPositionState) -> None:
    chandelier = state.chandelier
    trading_storage.update_position_progress(
        state.position_id,
        tp1_filled=state.take_profits[0]["filled"] if len(state.take_profits) > 0 else False,
        tp2_filled=state.take_profits[1]["filled"] if len(state.take_profits) > 1 else False,
        tp3_filled=state.take_profits[2]["filled"] if len(state.take_profits) > 2 else False,
        remaining_quantity=state.remaining_quantity,
        chandelier_active=chandelier is not None,
        chandelier_extreme_price=chandelier.extreme_price if chandelier else None,
        chandelier_stop_price=chandelier.stop_price if chandelier else None,
    )


def _queue_notification(chat_id: int, text: str) -> None:
    _notification_queue.append({"chat_id": chat_id, "text": text})


def pop_notifications() -> list[dict]:
    """Вычитывает и очищает накопленные уведомления -- вызывается из main.py на каждом тике."""
    items = list(_notification_queue)
    _notification_queue.clear()
    return items


def _format_tp_report(symbol: str, event: dict, state: order_executor.OpenPositionState) -> str:
    tp_number = event["event"][2]  # "tp1_hit" -> "1"
    pct_of_total = event["size_closed"] / state.quantity * 100
    remaining_pct = state.remaining_quantity / state.quantity * 100
    return (
        f"🎯 *TP{tp_number} исполнен: {symbol}*\n\n"
        f"Цена: `{event['exit_price']:.6g}`\n"
        f"Зафиксировано: {pct_of_total:.0f}% объёма\n"
        f"PnL: `{event['pnl_delta']:+.2f}`\n"
        f"Остаток в позиции: {remaining_pct:.0f}%"
    )


def _format_breakeven_report(symbol: str, event: dict) -> str:
    return (
        f"🛡 *SL перенесён в безубыток+: {symbol}*\n\n"
        f"Новый стоп: `{event['new_stop_loss']:.6g}`\n"
        f"Комиссии обеих ног сделки покрыты — риск на этой сделке закрыт"
    )


def _format_chandelier_activated_report(symbol: str, state: order_executor.OpenPositionState) -> str:
    remaining_pct = state.remaining_quantity / state.quantity * 100
    return (
        f"🔄 *Включён трейлинг-стоп TP4: {symbol}*\n\n"
        f"Оставшиеся {remaining_pct:.0f}% объёма теперь едут за ценой (Chandelier), "
        f"фиксированной цели больше нет"
    )


def _realized_pnl_so_far(state: order_executor.OpenPositionState) -> float:
    """
    Сумма PnL уже зафиксированных тейков (TP1-3) этой позиции, БЕЗ учёта
    текущего закрытия. Нужна, чтобы в уведомлении о закрытии (стоп/трейлинг/
    таймаут) показать итог по ВСЕЙ сделке, а не только по последней ноге --
    прод-вопрос 19.09.2026: после TP1 позиция остаётся на исходном стопе
    (перенос в безубыток+ только после TP2), поэтому закрытие остатка может
    показывать убыток на своей ноге, хотя сделка целиком в плюсе.
    """
    total = 0.0
    for tp in state.take_profits:
        if tp["filled"]:
            size = state.quantity * (tp["size_pct"] / 100)
            total += order_executor.calculate_position_pnl(state.direction, state.avg_entry_price, tp["level"], size)
    return total


def _format_close_report(symbol: str, event: dict, total_pnl: float) -> str:
    is_chandelier = event["event"] == "closed_chandelier"
    header = "Сделка закрыта трейлингом TP4" if is_chandelier else "Стоп сработал"
    icon = "🏁" if is_chandelier else "🛑"
    return (
        f"{icon} *{header}: {symbol}*\n\n"
        f"Цена закрытия: `{event['exit_price']:.6g}`\n"
        f"PnL: `{event['pnl_delta']:+.2f}`\n"
        f"PnL по сделке целиком: `{total_pnl:+.2f}`\n"
        f"Позиция полностью закрыта"
    )


def _format_timeout_report(symbol: str, event: dict, total_pnl: float) -> str:
    return (
        f"⏱ *Закрыто по таймауту {PUMP_STUCK_TIMEOUT_HOURS}ч: {symbol}*\n\n"
        f"Цена закрытия: `{event['exit_price']:.6g}`\n"
        f"PnL: `{event['pnl_delta']:+.2f}`\n"
        f"PnL по сделке целиком: `{total_pnl:+.2f}`\n"
        f"Памп простоял {PUMP_STUCK_TIMEOUT_HOURS}ч без реального прогресса "
        f"(максимум 1 тейк) — закрыто принудительно по рынку"
    )


def _format_stuck_stop_report(symbol: str, event: dict, state: order_executor.OpenPositionState) -> str:
    target = "безубыток+" if state.tp_hit_count == 0 else "уровень TP1"
    return (
        f"⏱ *Памп {PUMP_STUCK_TIMEOUT_HOURS}ч в плюсе: стоп подтянут: {symbol}*\n\n"
        f"Новый стоп: `{event['new_stop_loss']:.6g}` ({target})\n"
        f"Позиция не закрыта — держим дальше, прибыль защищена"
    )


def _check_pump_stuck_timeout(entry: dict, price: float) -> dict | None:
    """
    См. PUMP_STUCK_TIMEOUT_HOURS выше -- только пампы (short), максимум 1
    взятый тейк, не закрыта, и с момента входа прошло >= порога. В убытке --
    закрытие по рынку; в плюсе -- подтяжка стопа (см. ниже).
    """
    state = entry["state"]
    opened_at = entry.get("opened_at")
    if opened_at is None or state.closed:
        return None
    if state.direction != "short" or state.tp_hit_count > 1:
        return None
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if now - opened_at < timedelta(hours=PUMP_STUCK_TIMEOUT_HOURS):
        return None

    if entry.get("stuck_stop_moved"):
        return None

    pnl = order_executor.calculate_position_pnl(state.direction, state.avg_entry_price, price, state.remaining_quantity)
    if pnl > 0:
        # 21.09.2026: в плюсе не закрываем по рынку, а подтягиваем стоп -- в безубыток+ (TP не
        # взят) либо на уровень TP1 (взят один TP). Один раз на позицию.
        if state.tp_hit_count == 0:
            new_stop = position_manager.calculate_breakeven_plus_price(state.avg_entry_price, state.direction)
        else:
            new_stop = state.take_profits[0]["level"]
        entry["stuck_stop_moved"] = True
        if new_stop < state.stop_loss:
            state.stop_loss = new_stop
            return {"event": "stuck_stop_tightened", "new_stop_loss": new_stop}
        return None

    state.closed = True
    return {"event": "closed_timeout_24h", "pnl_delta": pnl, "exit_price": price}


def _record_trade_event(chat_id: int, symbol: str, event: str, pnl: float):
    """Пишет событие в БД для журнала сделок; сбой записи не должен ломать торговлю."""
    try:
        trading_storage.record_trade_event(chat_id, symbol, event, pnl)
    except Exception:
        logger.exception(f"Автотрейдинг [{symbol}]: не удалось записать событие {event} в trade_events")


def _process_open_position_tick(symbol: str, price: float) -> list[str] | None:
    entry = _open_positions[symbol]
    state = entry["state"]
    chat_id = entry["chat_id"]
    events = []

    timeout_event = _check_pump_stuck_timeout(entry, price)
    if timeout_event is not None and timeout_event["event"] == "stuck_stop_tightened":
        trading_storage.update_position_stop_loss(state.position_id, timeout_event["new_stop_loss"])
        _queue_notification(chat_id, _format_stuck_stop_report(symbol, timeout_event, state))
        logger.info(f"Автотрейдинг [{symbol}]: stuck_stop_tightened, new_sl={timeout_event['new_stop_loss']:.6g}")
        events.append("stuck_stop_tightened")
        timeout_event = None
    if timeout_event is not None:
        total_pnl = _realized_pnl_so_far(state) + timeout_event["pnl_delta"]
        trading_storage.adjust_paper_balance(chat_id, timeout_event["pnl_delta"])
        trading_storage.close_position(state.position_id, realized_pnl=timeout_event["pnl_delta"])
        _queue_notification(chat_id, _format_timeout_report(symbol, timeout_event, total_pnl))
        logger.info(
            f"Автотрейдинг [{symbol}]: {timeout_event['event']}, "
            f"цена={timeout_event['exit_price']:.6g}, pnl={timeout_event['pnl_delta']:+.2f}"
        )
        _record_trade_event(chat_id, symbol, timeout_event["event"], timeout_event["pnl_delta"])
        if state.tp_hit_count == 0:
            pending = _pending_setups.get(symbol)
            if pending is not None:
                pending["invalidated"] = True
        del _open_positions[symbol]
        return [timeout_event["event"]]

    stop_event = order_executor.check_stop_hit(state, price, entry["atr_1h"])
    if stop_event is not None:
        total_pnl = _realized_pnl_so_far(state) + stop_event["pnl_delta"]
        trading_storage.adjust_paper_balance(chat_id, stop_event["pnl_delta"])
        trading_storage.close_position(state.position_id, realized_pnl=stop_event["pnl_delta"])
        _queue_notification(chat_id, _format_close_report(symbol, stop_event, total_pnl))
        logger.info(
            f"Автотрейдинг [{symbol}]: {stop_event['event']}, "
            f"цена={stop_event['exit_price']:.6g}, pnl={stop_event['pnl_delta']:+.2f}"
        )
        _record_trade_event(chat_id, symbol, stop_event["event"], stop_event["pnl_delta"])
        if state.tp_hit_count == 0:
            # Тезис на разворот опровергнут рынком (ни один TP не взят до стопа) --
            # если вторая часть входа ещё не сработала, отменяем её (см.
            # _handle_part_fill), а не даём открыть вторую независимую позицию
            # вслепую (прод-находка 14-16.09.2026, см. докстринг _handle_part_fill).
            pending = _pending_setups.get(symbol)
            if pending is not None:
                pending["invalidated"] = True
        del _open_positions[symbol]
        return events + [stop_event["event"]]

    tp_events = order_executor.check_take_profit_hits(state, price)
    for event in tp_events:
        if event["event"].startswith("tp"):
            trading_storage.adjust_paper_balance(chat_id, event["pnl_delta"])
            _queue_notification(chat_id, _format_tp_report(symbol, event, state))
            logger.info(
                f"Автотрейдинг [{symbol}]: {event['event']}, "
                f"цена={event['exit_price']:.6g}, pnl={event['pnl_delta']:+.2f}"
            )
            _record_trade_event(chat_id, symbol, event["event"], event["pnl_delta"])
        elif event["event"] == "moved_to_breakeven":
            trading_storage.update_position_stop_loss(state.position_id, event["new_stop_loss"])
            _queue_notification(chat_id, _format_breakeven_report(symbol, event))
            logger.info(f"Автотрейдинг [{symbol}]: moved_to_breakeven, new_sl={event['new_stop_loss']:.6g}")
        elif event["event"] == "chandelier_activated":
            _queue_notification(chat_id, _format_chandelier_activated_report(symbol, state))
            logger.info(f"Автотрейдинг [{symbol}]: chandelier_activated")
        events.append(event["event"])

    if tp_events or state.chandelier is not None:
        _persist_position_progress(state)

    return events or None


def _process_pending_setup_tick(symbol: str, price: float) -> list[str] | None:
    setup = _pending_setups[symbol]
    events = []

    if setup["cap_reference_price"] is None:
        setup["cap_reference_price"] = price
        setup["last_atr_refresh_price"] = price

    if not setup["trigger_part1"].fired and setup["trigger_part1"].update(price):
        _handle_part_fill(setup, symbol, price)
        events.append("part1_filled")

    if not setup["trigger_part2"].fired and setup["trigger_part2"].update(price):
        _handle_part_fill(setup, symbol, price)
        events.append("part2_filled")

    if setup["trigger_part1"].fired and setup["trigger_part2"].fired:
        del _pending_setups[symbol]
        events.append("setup_complete")
    elif not events and not setup["trigger_part1"].fired and not setup["trigger_part2"].fired:
        cap_pct = (
            magnet_levels_module.PUMP_EXTENSION_CAP_PCT if setup["impulse_direction"] == "up"
            else magnet_levels_module.DUMP_EXTENSION_CAP_PCT
        )
        if magnet_levels_module.is_beyond_extension_cap(setup["cap_reference_price"], price, cap_pct=cap_pct):
            trading_storage.update_trade_signal_status(setup["signal_id"], "expired")
            del _pending_setups[symbol]
            events.append("setup_expired")
        elif magnet_levels_module.is_beyond_extension_cap(
            setup["last_atr_refresh_price"], price, cap_pct=ATR_REFRESH_STEP_PCT
        ):
            setup["last_atr_refresh_price"] = price
            events.append("atr_refresh_needed")

    return events or None


def reset_all_state(chat_id: int, starting_balance: float = 10000.0) -> None:
    """Полный сброс paper-trading: чистит БД (баланс/позиции/сигналы) и in-memory состояние."""
    _pending_setups.clear()
    _open_positions.clear()
    trading_storage.reset_paper_trading(chat_id, starting_balance=starting_balance)


async def refresh_pending_setup_atr(session, symbol: str) -> None:
    """
    Пересчитывает ATR15м/ATR1ч для ожидающего сетапа и обновляет дистанции
    трейлинг-триггеров -- вызывается фоновой задачей в ответ на событие
    "atr_refresh_needed" из handle_price_tick (цена ушла далеко от точки
    старта мониторинга без отката, исходная ATR устарела относительно
    текущей волатильности). Экстремум триггера (extreme_price) не трогаем --
    только дистанцию срабатывания.
    """
    setup = _pending_setups.get(symbol)
    if setup is None:
        return

    exchange = setup["exchange"]
    candles_15m = await market_data.fetch_klines(session, exchange, symbol, "15m", limit=50)
    candles_1h = await market_data.fetch_klines(session, exchange, symbol, "1h", limit=24)
    atr_15m_values = indicators.atr(candles_15m, period=14)
    atr_1h_values = indicators.atr(candles_1h, period=14)
    atr_15m = atr_15m_values[-1] if atr_15m_values else None
    atr_1h = atr_1h_values[-1] if atr_1h_values else None
    if atr_15m is None or atr_1h is None or atr_15m <= 0 or atr_1h <= 0:
        return

    setup = _pending_setups.get(symbol)  # сетап мог исчезнуть/слиться, пока шёл запрос
    if setup is None:
        return

    setup["trigger_part1"].trigger_distance = atr_15m * entry_engine.PART1_ATR_MULTIPLIER
    setup["trigger_part2"].trigger_distance = atr_15m * entry_engine.PART2_ATR_MULTIPLIER
    setup["atr_1h"] = atr_1h


def _handle_part_fill(setup: dict, symbol: str, price: float) -> None:
    """
    Открывает новую позицию по первой сработавшей части, либо объединяет
    со второй частью, если позиция первой ещё открыта и ни один TP не сработал.
    Если позиция первой части уже закрыта (SL) или частично зафиксирована
    (сработал TP) -- часть открывает отдельную независимую позицию, чтобы не
    "расфиливать" уже зафиксированные тейки при пересборке сетки.

    Исключение (прод-находка 14-16.09.2026): если позиция первой части
    стопилась с НУЛЁМ взятых TP -- тезис на разворот уже опровергнут рынком,
    setup помечается invalidated в _process_open_position_tick, и эта часть
    просто ничего не открывает. Живые данные показали, что без этого исключения
    треть сигналов в сутки давала ДВА независимых стопа подряд от одного и
    того же сигнала (AKEUSDT/PUFFERUSDT/CVCUSDT, 15-16.09.2026); бэктест на
    2,5 мес. подтвердил +$1713 (+4.9%) итогового PnL при этом исключении.
    """
    if setup.get("invalidated"):
        return

    profile = setup["profile"]
    direction = position_manager.determine_trade_direction(setup["impulse_direction"], "reversal")
    existing = _open_positions.get(symbol)
    is_merge = existing is not None and not existing["state"].closed and existing["state"].tp_hit_count == 0
    fill_stage = "part1" if existing is None else ("part2_merged" if is_merge else "part2_independent")

    if is_merge:
        old_state = existing["state"]
        fills = [(old_state.avg_entry_price, old_state.quantity), (price, setup["part_size"])]
        trading_storage.close_position(old_state.position_id, realized_pnl=0.0)
    else:
        fills = [(price, setup["part_size"])]

    # При слиянии части 2 в ещё открытую позицию части 1 сохраняем ИСХОДНОЕ
    # время входа (не сбрасываем на "сейчас") -- иначе таймаут "зависшего
    # пампа" (PUMP_STUCK_TIMEOUT_HOURS) отсчитывался бы заново от каждого
    # слияния, а не от реального момента первого входа в сделку.
    opened_at = (
        existing["opened_at"] if is_merge and existing.get("opened_at")
        else datetime.now(timezone.utc).replace(tzinfo=None)
    )

    result = order_executor.open_paper_position(
        chat_id=setup["chat_id"], symbol=symbol, exchange=setup["exchange"], direction=direction,
        fills=fills, sl_method=profile["sl_method"], atr_1h=setup["atr_1h"],
        atr_multiplier=REVERSAL_ATR_MULTIPLIER, fixed_percent=profile["sl_fixed_percent"],
        tp_split_preset=profile["tp_split_preset"], breakeven_after_tp=profile["breakeven_after_tp"],
        r_multiples=_tp_r_multiples_for_direction(setup["impulse_direction"]),
    )
    new_state = order_executor.OpenPositionState(
        position_id=result["position_id"], direction=direction,
        avg_entry_price=result["avg_entry_price"], quantity=result["quantity"],
        stop_loss=result["stop_loss"], take_profits=result["take_profits"],
        breakeven_after_tp=profile["breakeven_after_tp"],
    )
    _open_positions[symbol] = {
        "chat_id": setup["chat_id"], "state": new_state, "atr_1h": setup["atr_1h"], "opened_at": opened_at,
        "fill_stage": fill_stage,
    }
    trading_storage.update_trade_signal_status(setup["signal_id"], "executed")
