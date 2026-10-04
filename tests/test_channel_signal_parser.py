from channel_signal_parser import parse_channel_signal, ParsedChannelSignal


def test_type_a_short():
    text = (
        "ЗАХОДИМ В МАНИПУЛЯЦИЮ\n\n"
        "XAI SHORT  - опасный вид манипуляций, когда внутри нисходящего канала формируют такие пампы\n\n"
        "Пришли к сопротивлению\n"
        "И жду быстрый откат, если пойдем выше предыдущего максимума, то лучше стопиться\n\n"
        "Соблюдаем риски и не котлетим позицию!"
    )
    assert parse_channel_signal(text) == ParsedChannelSignal(ticker="XAI", direction="short")


def test_type_a_long():
    text = (
        "ЗАХОДИМ В МАНИПУЛЯЦИЮ\n\n"
        "US LONG  - хочу попробовать локальную позицию в Лонг на откат после снижения\n\n"
        "Если будет четкий закреп выше 0.03$, то возможен полноценный памп на 30-40% чистого\n\n"
        "Соблюдаем риски и не котлетим позицию!"
    )
    assert parse_channel_signal(text) == ParsedChannelSignal(ticker="US", direction="long")


def test_type_a_remaining_four_tickers():
    cases = [
        ("PHA SHORT  - монета часто склонна к подобным манипуляциям", "PHA", "short"),
        ("ARK SHORT  - закрылась 12ч свеча, можно взять откат локальный", "ARK", "short"),
        ("BTW SHORT  - очень волатильная и нестабильная монета", "BTW", "short"),
        ("CAP SHORT  - больше среднесрочная позиция и не стоит ждать", "CAP", "short"),
    ]
    for line, ticker, direction in cases:
        text = f"ЗАХОДИМ В МАНИПУЛЯЦИЮ\n\n{line}\n\nСоблюдаем риски и не котлетим позицию!"
        assert parse_channel_signal(text) == ParsedChannelSignal(ticker=ticker, direction=direction), line


def test_type_b_ticker_then_direction_word():
    text = (
        "Так, заходим в позицию MARSCOIN short\n\n"
        "Плечо: 20.0\nМаржа: 300$\nТейк: 0.1455$\n\n"
        "Я уже в позиции сижу, так что давай в темпе заходи"
    )
    assert parse_channel_signal(text) == ParsedChannelSignal(ticker="MARSCOIN", direction="short")


def test_type_b_ticker_then_direction_word_uppercase_long():
    text = (
        "заходим в позицию NIGHT LONG\n\n"
        "Плечо: 30.0\nМаржа: 1000$\nТейк: 0.375$\n\n"
        "Точно так же риск повышен, но надо умножать депозит дальше"
    )
    assert parse_channel_signal(text) == ParsedChannelSignal(ticker="NIGHT", direction="long")


def test_type_b_direction_word_then_ticker():
    text = (
        "Давай шорт на CELO\n\n"
        "Тейк: 0.102$\nПлечо: 50x\nМаржа: 250$\n\n"
        "Риск берем уже меньше, так как депозит больше стал"
    )
    assert parse_channel_signal(text) == ParsedChannelSignal(ticker="CELO", direction="short")


def test_type_c_spot_not_parsed():
    """
    Критично: "UAI Long беру от текущих..." структурно похож на тип B (тикер сразу
    перед словом направления), но БЕЗ анкерной фразы "заходим в позицию" -- не
    должен распознаваться (спот не входит в область фичи, см. спеку 2026-10-04).
    """
    text = (
        "СДЕЛКА НА СПОТ\n\n"
        "UAI Long беру от текущих, огромный потенциал в короткие сроки достичь цели 100% чистого и более\n\n"
        "И взяла с не большим плечом эту же монету на фьючерсы!"
    )
    assert parse_channel_signal(text) is None


def test_none_for_unrelated_chatter():
    assert parse_channel_signal("Всем привет, как дела?") is None


def test_none_for_empty_or_missing_text():
    assert parse_channel_signal("") is None
    assert parse_channel_signal(None) is None


def test_none_when_header_present_but_next_line_unrecognized():
    text = "ЗАХОДИМ В МАНИПУЛЯЦИЮ\n\nвсё сложно, без тикера тут"
    assert parse_channel_signal(text) is None
