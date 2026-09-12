import pytest

import market_data


class _FakeResponse:
    def __init__(self, json_data, status=200):
        self._json_data = json_data
        self.status = status

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def json(self):
        return self._json_data

    def raise_for_status(self):
        if self.status >= 400:
            raise Exception(f"HTTP {self.status}")


class _FakeSession:
    def __init__(self, json_data):
        self._json_data = json_data
        self.last_url = None
        self.last_params = None

    def get(self, url, params=None):
        self.last_url = url
        self.last_params = params
        return _FakeResponse(self._json_data)


BINANCE_RAW_KLINES = [
    [1000, "10.0", "11.0", "9.5", "10.5", "100.0", 1059, "1050.0", 10, "50.0", "525.0", "0"],
    [2000, "10.5", "12.0", "10.0", "11.5", "150.0", 2059, "1725.0", 15, "80.0", "920.0", "0"],
]

BYBIT_RAW_KLINES = {
    "retCode": 0,
    "retMsg": "OK",
    "result": {
        "category": "linear",
        "symbol": "BTCUSDT",
        "list": [
            ["2000", "10.5", "12.0", "10.0", "11.5", "150.0", "1725.0"],
            ["1000", "10.0", "11.0", "9.5", "10.5", "100.0", "1050.0"],
        ],
    },
}


@pytest.mark.asyncio
async def test_fetch_klines_binance_parses_and_orders_ascending():
    session = _FakeSession(BINANCE_RAW_KLINES)
    candles = await market_data.fetch_klines(session, "Binance", "BTCUSDT", "15m", limit=2)

    assert len(candles) == 2
    assert candles[0]["open_time"] == 1000
    assert candles[0]["open"] == 10.0
    assert candles[0]["high"] == 11.0
    assert candles[0]["low"] == 9.5
    assert candles[0]["close"] == 10.5
    assert candles[0]["volume"] == 100.0
    assert candles[1]["open_time"] == 2000
    assert "fapi/v1/klines" in session.last_url
    assert session.last_params["symbol"] == "BTCUSDT"
    assert session.last_params["interval"] == "15m"
    assert session.last_params["limit"] == 2


@pytest.mark.asyncio
async def test_fetch_klines_bybit_parses_and_reorders_ascending():
    session = _FakeSession(BYBIT_RAW_KLINES)
    candles = await market_data.fetch_klines(session, "Bybit", "BTCUSDT", "15m", limit=2)

    assert len(candles) == 2
    # Bybit отдаёт свечи в обратном порядке (новые первые) — должны быть переупорядочены
    assert candles[0]["open_time"] == 1000
    assert candles[0]["close"] == 10.5
    assert candles[1]["open_time"] == 2000
    assert candles[1]["close"] == 11.5
    assert "v5/market/kline" in session.last_url
    assert session.last_params["category"] == "linear"
    assert session.last_params["interval"] == "15"  # Bybit использует минуты, не "15m"


@pytest.mark.asyncio
async def test_fetch_klines_bybit_interval_mapping_for_daily_and_weekly():
    session = _FakeSession(BYBIT_RAW_KLINES)
    await market_data.fetch_klines(session, "Bybit", "BTCUSDT", "1d", limit=2)
    assert session.last_params["interval"] == "D"

    await market_data.fetch_klines(session, "Bybit", "BTCUSDT", "1w", limit=2)
    assert session.last_params["interval"] == "W"


@pytest.mark.asyncio
async def test_fetch_klines_bybit_interval_mapping_for_hours():
    session = _FakeSession(BYBIT_RAW_KLINES)
    await market_data.fetch_klines(session, "Bybit", "BTCUSDT", "1h", limit=2)
    assert session.last_params["interval"] == "60"

    await market_data.fetch_klines(session, "Bybit", "BTCUSDT", "4h", limit=2)
    assert session.last_params["interval"] == "240"


@pytest.mark.asyncio
async def test_fetch_klines_bybit_returns_empty_on_error_code():
    session = _FakeSession({"retCode": 10001, "retMsg": "invalid symbol", "result": {"list": []}})
    candles = await market_data.fetch_klines(session, "Bybit", "BADSYMBOL", "15m")
    assert candles == []


@pytest.mark.asyncio
async def test_fetch_klines_unknown_exchange_raises():
    session = _FakeSession([])
    with pytest.raises(ValueError):
        await market_data.fetch_klines(session, "Kraken", "BTCUSDT", "15m")
