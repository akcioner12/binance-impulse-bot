"""
Парсер текста сигналов стороннего Telegram-канала (-1002487960768, см. спеку
docs/superpowers/specs/2026-10-04-channel-signal-autotrading-design.md).

Два распознаваемых формата:
- Тип A: заголовок "ЗАХОДИМ В МАНИПУЛЯЦИЮ", на следующей строке "<ТИКЕР> <SHORT|LONG>".
- Тип B (пересланные от другого автора): "заходим в позицию <ТИКЕР> <long|short>"
  ИЛИ "давай <шорт|лонг> на <ТИКЕР>" -- порядок слов варьируется у источника.

Всё остальное (включая тип C -- спотовые рекомендации) возвращает None.
"""
import re
from dataclasses import dataclass

_HEADER_RE = re.compile(r"заходим\s+в\s+манипуляцию", re.IGNORECASE)
_TICKER_DIRECTION_RE = re.compile(r"^([A-Za-z0-9]{2,10})\s+(SHORT|LONG|ШОРТ|ЛОНГ)\b", re.IGNORECASE)
_TYPE_B_TICKER_FIRST_RE = re.compile(
    r"заходим\s+в\s+позицию\s+([A-Za-z0-9]{2,10})\s+(long|short|лонг|шорт)\b", re.IGNORECASE
)
_TYPE_B_DIRECTION_FIRST_RE = re.compile(
    r"давай\s+(шорт|лонг)\s+на\s+([A-Za-z0-9]{2,10})\b", re.IGNORECASE
)

_DIRECTION_NORMALIZE = {
    "short": "short", "шорт": "short",
    "long": "long", "лонг": "long",
}


@dataclass
class ParsedChannelSignal:
    ticker: str
    direction: str  # "long" | "short"


def parse_channel_signal(text: str | None) -> ParsedChannelSignal | None:
    if not text:
        return None

    header_match = _HEADER_RE.search(text)
    if header_match:
        rest = text[header_match.end():].lstrip("\n\r ")
        for line in rest.splitlines():
            line = line.strip()
            if not line:
                continue
            m = _TICKER_DIRECTION_RE.match(line)
            if m:
                return ParsedChannelSignal(
                    ticker=m.group(1).upper(),
                    direction=_DIRECTION_NORMALIZE[m.group(2).lower()],
                )
            break  # первая непустая строка не подошла -- формат неизвестен, в тип B не пробуем

    m = _TYPE_B_TICKER_FIRST_RE.search(text)
    if m:
        return ParsedChannelSignal(ticker=m.group(1).upper(), direction=_DIRECTION_NORMALIZE[m.group(2).lower()])

    m = _TYPE_B_DIRECTION_FIRST_RE.search(text)
    if m:
        return ParsedChannelSignal(ticker=m.group(2).upper(), direction=_DIRECTION_NORMALIZE[m.group(1).lower()])

    return None
