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
