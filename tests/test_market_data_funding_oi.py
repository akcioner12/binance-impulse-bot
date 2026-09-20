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


@pytest.mark.asyncio
async def test_fetch_funding_rate_binance_parses_last_funding_rate():
    session = _FakeSession({"symbol": "BTCUSDT", "lastFundingRate": "0.00015000", "time": 1000})
    rate = await market_data.fetch_funding_rate(session, "Binance", "BTCUSDT")

    assert rate == pytest.approx(0.00015)
    assert "premiumIndex" in session.last_url
    assert session.last_params["symbol"] == "BTCUSDT"


@pytest.mark.asyncio
async def test_fetch_funding_rate_bybit_parses_ticker_funding_rate():
    session = _FakeSession({
        "retCode": 0,
        "result": {"list": [{"symbol": "BTCUSDT", "fundingRate": "0.0002"}]},
    })
    rate = await market_data.fetch_funding_rate(session, "Bybit", "BTCUSDT")

    assert rate == pytest.approx(0.0002)
    assert "v5/market/tickers" in session.last_url
    assert session.last_params["category"] == "linear"


@pytest.mark.asyncio
async def test_fetch_funding_rate_bybit_returns_zero_on_error():
    session = _FakeSession({"retCode": 10001, "retMsg": "bad symbol", "result": {"list": []}})
    rate = await market_data.fetch_funding_rate(session, "Bybit", "BADSYMBOL")
    assert rate == 0.0


@pytest.mark.asyncio
async def test_fetch_funding_rate_bybit_returns_zero_when_list_empty():
    session = _FakeSession({"retCode": 0, "result": {"list": []}})
    rate = await market_data.fetch_funding_rate(session, "Bybit", "BTCUSDT")
    assert rate == 0.0


@pytest.mark.asyncio
async def test_fetch_funding_rate_unknown_exchange_raises():
    session = _FakeSession({})
    with pytest.raises(ValueError):
        await market_data.fetch_funding_rate(session, "Kraken", "BTCUSDT")


BINANCE_OI_HISTORY = [
    {"symbol": "BTCUSDT", "sumOpenInterest": "1000.0", "sumOpenInterestValue": "50000000", "timestamp": 1000},
    {"symbol": "BTCUSDT", "sumOpenInterest": "950.0", "sumOpenInterestValue": "48000000", "timestamp": 2000},
]

BYBIT_OI_HISTORY = {
    "retCode": 0,
    "result": {
        "category": "linear",
        "symbol": "BTCUSDT",
        "list": [
            {"openInterest": "950.0", "timestamp": "2000"},
            {"openInterest": "1000.0", "timestamp": "1000"},
        ],
    },
}


@pytest.mark.asyncio
async def test_fetch_open_interest_history_binance_parses_ascending():
    session = _FakeSession(BINANCE_OI_HISTORY)
    history = await market_data.fetch_open_interest_history(session, "Binance", "BTCUSDT", period="5m", limit=2)

    assert len(history) == 2
    assert history[0] == {"timestamp": 1000, "open_interest": 1000.0}
    assert history[1] == {"timestamp": 2000, "open_interest": 950.0}
    assert "openInterestHist" in session.last_url
    assert session.last_params["period"] == "5m"


@pytest.mark.asyncio
async def test_fetch_open_interest_history_bybit_parses_and_reorders_ascending():
    session = _FakeSession(BYBIT_OI_HISTORY)
    history = await market_data.fetch_open_interest_history(session, "Bybit", "BTCUSDT", period="5m", limit=2)

    assert len(history) == 2
    assert history[0] == {"timestamp": 1000, "open_interest": 1000.0}
    assert history[1] == {"timestamp": 2000, "open_interest": 950.0}
    assert "open-interest" in session.last_url
    assert session.last_params["intervalTime"] == "5min"


@pytest.mark.asyncio
async def test_fetch_open_interest_history_bybit_returns_empty_on_error():
    session = _FakeSession({"retCode": 10001, "retMsg": "bad symbol", "result": {"list": []}})
    history = await market_data.fetch_open_interest_history(session, "Bybit", "BADSYMBOL")
    assert history == []


@pytest.mark.asyncio
async def test_fetch_funding_rate_binance_settled_uses_funding_history_not_premium_index():
    """
    premiumIndex.lastFundingRate -- ТЕКУЩИЙ расчётный funding, он скачет во время
    пампа (у GUSDT 20.09.2026 даже другой знак); фильтр пампов откалиброван на
    ПОСЛЕДНЕМ рассчитанном (история /fundingRate), поэтому для него берём его.
    """
    session = _FakeSession([{"symbol": "GUSDT", "fundingRate": "0.00006216", "fundingTime": 1}])
    rate = await market_data.fetch_funding_rate(session, "Binance", "GUSDT", settled=True)

    assert rate == pytest.approx(0.00006216)
    assert session.last_url.endswith("/fapi/v1/fundingRate")
    assert session.last_params == {"symbol": "GUSDT", "limit": 1}


@pytest.mark.asyncio
async def test_fetch_funding_rate_binance_settled_returns_zero_when_history_empty():
    session = _FakeSession([])
    assert await market_data.fetch_funding_rate(session, "Binance", "NEWUSDT", settled=True) == 0.0


@pytest.mark.asyncio
async def test_fetch_funding_rate_bybit_settled_uses_funding_history():
    session = _FakeSession({
        "retCode": 0,
        "result": {"list": [{"symbol": "BTCUSDT", "fundingRate": "0.00031", "fundingRateTimestamp": "1"}]},
    })
    rate = await market_data.fetch_funding_rate(session, "Bybit", "BTCUSDT", settled=True)

    assert rate == pytest.approx(0.00031)
    assert "v5/market/funding/history" in session.last_url
    assert session.last_params["limit"] == 1


@pytest.mark.asyncio
async def test_fetch_funding_rate_bybit_settled_returns_zero_on_error_or_empty():
    assert await market_data.fetch_funding_rate(_FakeSession({"retCode": 10001, "retMsg": "bad", "result": {"list": []}}), "Bybit", "X", settled=True) == 0.0
    assert await market_data.fetch_funding_rate(_FakeSession({"retCode": 0, "result": {"list": []}}), "Bybit", "X", settled=True) == 0.0
