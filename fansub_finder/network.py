import asyncio
import time
from collections import OrderedDict
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

import httpx


class Network:
    def __init__(self, proxy, transport=None, retries=2, interval=None):
        self.client = httpx.AsyncClient(
            proxy=proxy or None,
            transport=transport,
            trust_env=False,
            timeout=httpx.Timeout(25, connect=8),
            follow_redirects=True,
            headers={"User-Agent": "new-anime-sub-group-finder/0.1 (public catalog reader)"},
        )
        self.retries = retries
        self.interval = interval
        self.locks = {}
        self.last_request = {}
        self.cache = OrderedDict()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()

    async def close(self):
        await self.client.aclose()

    async def text(self, url, params=None):
        host = urlsplit(url).hostname
        key = str(httpx.URL(url, params=params)) if params else url
        lock = self.locks.setdefault(host, asyncio.Lock())
        interval = self.interval if self.interval is not None else (2.2 if host == "anibt.net" else 0.5)
        async with lock:
            for attempt in range(self.retries + 1):
                await asyncio.sleep(max(0, self.last_request.get(host, 0) + interval - time.monotonic()))
                cached = self.cache.get(key)
                headers = {}
                if cached:
                    if cached[0]:
                        headers["If-None-Match"] = cached[0]
                    if cached[1]:
                        headers["If-Modified-Since"] = cached[1]
                self.last_request[host] = time.monotonic()
                try:
                    r = await self.client.get(url, params=params, headers=headers)
                    if r.status_code == 304:
                        if not cached:
                            raise ValueError("源站返回 304，但没有本地缓存")
                        return cached[2]
                    if r.status_code == 429 or r.status_code >= 500:
                        r.raise_for_status()
                    r.raise_for_status()
                    if r.headers.get("etag") or r.headers.get("last-modified"):
                        self.cache[key] = (r.headers.get("etag"), r.headers.get("last-modified"), r.text)
                        self.cache.move_to_end(key)
                        while len(self.cache) > 512:
                            self.cache.popitem(last=False)
                    return r.text
                except (httpx.TransportError, httpx.HTTPStatusError) as error:
                    retryable = (
                        not isinstance(error, httpx.HTTPStatusError)
                        or error.response.status_code == 429
                        or error.response.status_code >= 500
                    )
                    if attempt >= self.retries or not retryable:
                        raise
                    delay = 2**attempt
                    if isinstance(error, httpx.HTTPStatusError):
                        retry = error.response.headers.get("retry-after", "")
                        if retry.isdigit():
                            delay = int(retry)
                        elif retry:
                            try:
                                retry_at = parsedate_to_datetime(retry)
                                if retry_at.tzinfo is None:
                                    retry_at = retry_at.replace(tzinfo=timezone.utc)
                                delay = max(0, (retry_at - datetime.now(timezone.utc)).total_seconds())
                            except (ValueError, TypeError, OverflowError):
                                pass
                    await asyncio.sleep(delay)

    async def json(self, url, params=None):
        import json

        return json.loads(await self.text(url, params))
