import httpx
import pytest

from fansub_finder.network import Network


async def test_retry_and_304_preserve_valid_payload():
    calls = []
    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        if len(calls) == 2:
            return httpx.Response(200, text='{"ok":true}', headers={"ETag": '"one"'})
        assert request.headers.get("if-none-match") == '"one"'
        return httpx.Response(304)
    async with Network(proxy="", transport=httpx.MockTransport(handler), interval=0) as net:
        assert await net.json("https://anibt.net/test") == {"ok": True}
        assert await net.json("https://anibt.net/test") == {"ok": True}


async def test_unavailable_proxy_is_an_error_not_empty_data():
    async with Network(proxy="http://127.0.0.1:1", retries=0, interval=0) as net:
        with pytest.raises(httpx.HTTPError):
            await net.json("https://anibt.net/test")
