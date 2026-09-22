import inspect

import main


def test_main_source_references_trading_journal_report_loop():
    """
    main() запускает несколько бесконечных циклов через asyncio.gather и
    реально не возвращается, пока процесс жив -- вызывать main() напрямую
    в тесте нельзя (он никогда не завершится). Проверяем подключение через
    исходный код функции: trading_journal_report_loop должен быть в вызове
    asyncio.gather(...) вместе с остальными циклами.
    """
    source = inspect.getsource(main.main)
    assert "trading_journal_report_loop(ADMIN_CHAT_ID)" in source
    assert "collectors_supervisor()" in source  # существующий цикл всё ещё на месте


def test_main_source_restores_open_positions_and_expires_pending_signals():
    """
    Восстановление открытых позиций и истечение "осиротевших" pending-сигналов
    должны происходить на старте main(), до входа в бесконечный asyncio.gather.
    """
    source = inspect.getsource(main.main)
    assert "live_trading.restore_open_positions()" in source
    assert "expire_all_pending_signals()" in source


def test_main_source_seeds_trade_events_history_on_startup():
    """История событий с 15.09 (собрана из логов до появления trade_events) грузится один раз."""
    source = inspect.getsource(main.main)
    assert "seed_trade_events_if_empty(ADMIN_CHAT_ID" in source


def test_main_source_starts_journal_web_server():
    """HTTP-страница живого журнала (journal_web) должна быть в том же asyncio.gather."""
    source = inspect.getsource(main.main)
    assert "run_web_server(" in source
