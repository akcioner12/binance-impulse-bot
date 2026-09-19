import pytest
import aiohttp

import notifier


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    async def json(self):
        return self._payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeSession:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return _FakeResponse(self.payload)


@pytest.mark.asyncio
async def test_send_document_posts_multipart_to_send_document_endpoint():
    session = _FakeSession({"ok": True, "result": {}})

    ok = await notifier.send_document(session, 111, "journal.html", b"<html></html>", caption="cap")

    assert ok is True
    url, kwargs = session.calls[0]
    assert url.endswith("/sendDocument")
    assert isinstance(kwargs["data"], aiohttp.FormData)


@pytest.mark.asyncio
async def test_send_document_returns_false_when_telegram_rejects():
    session = _FakeSession({"ok": False, "description": "bad"})

    assert await notifier.send_document(session, 111, "journal.html", b"x") is False
