import inspect

import main


def test_main_source_references_trading_daily_report_loop():
    """
    main() запускает несколько бесконечных циклов через asyncio.gather и
    реально не возвращается, пока процесс жив -- вызывать main() напрямую
    в тесте нельзя (он никогда не завершится). Проверяем подключение через
    исходный код функции: trading_daily_report_loop должен быть в вызове
    asyncio.gather(...) вместе с остальными циклами.
    """
    source = inspect.getsource(main.main)
    assert "trading_daily_report_loop(ADMIN_CHAT_ID)" in source
    assert "collectors_supervisor()" in source  # существующий цикл всё ещё на месте
