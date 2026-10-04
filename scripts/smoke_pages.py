"""Verify the exported site under a project subpath without a backend."""

import asyncio
import json
import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.async_api import async_playwright


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


async def main():
    directory = Path(sys.argv[1] if len(sys.argv) > 1 else "dist/pages").resolve()
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(directory.parent)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}/{directory.name}/"
    output = Path(".cache/pages-verification")
    output.mkdir(parents=True, exist_ok=True)
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(channel="msedge", headless=True)
            page = await browser.new_page(viewport={"width": 1440, "height": 1000})
            errors, requests = [], []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on("request", lambda request: requests.append(request.url))
            await page.goto(url)
            await page.locator("details.anime[data-anime]").first.wait_for()
            await page.wait_for_function(
                "[...document.querySelectorAll('.finder-cover img')].some(e => e.complete && e.naturalWidth > 0)",
                timeout=60000,
            )
            assert await page.locator(".finder-cover img").evaluate_all(
                "els => els.every(e => e.src.startsWith('https://lain.bgm.tv/pic/cover/'))"
            )
            assert not any("/covers/" in request for request in requests)
            assert not await page.locator('[data-page="settings"]').is_visible()
            assert await page.locator("#scan").get_attribute("aria-disabled") == "true"
            await page.locator("#scan").click(force=True)
            await page.locator("details.anime[data-anime] summary").first.click()
            await page.locator("details.group").first.wait_for()
            await page.locator("details.group summary").first.click()
            await page.locator(".resources .resource").first.wait_for()
            await page.locator("#search_text").fill("冰之城墙")
            await page.locator("#search_text").press("Enter")
            await page.wait_for_function("document.querySelectorAll('[data-anime]').length === 1")
            await page.locator("#search_text").fill("")
            await page.locator("#search_text").press("Enter")
            await page.wait_for_function("document.querySelectorAll('[data-anime]').length > 1")
            await page.locator('[data-page="changes"]').click()
            await page.get_by_role("heading", name="近 24h 更新", exact=True).wait_for()
            await page.locator('[data-page="blocked"]').click()
            await page.locator("details.blocked-group").first.wait_for()
            await page.locator("details.blocked-group summary").first.click()
            await page.locator("[data-blocked-anime]").first.wait_for()
            await page.locator("[data-blocked-anime] summary").first.click()
            await page.locator(".resources .resource").first.wait_for()
            assert await page.locator(".blocked-reasons").count() == 1
            assert await page.locator(".blocked-animes .reason").count() == 0
            await page.screenshot(path=str(output / "blocked.png"), full_page=False)
            for width in [320, 375, 414, 768]:
                await page.set_viewport_size({"width": width, "height": 844})
                assert await page.locator("#content").evaluate(
                    "e => e.getBoundingClientRect().right <= innerWidth"
                )
                await page.screenshot(
                    path=str(output / f"blocked-{width}.png"), full_page=False, animations="disabled"
                )
            assert not any("/api/" in request for request in requests), requests
            assert not errors, errors
            print(
                json.dumps(
                    {
                        "mode": "static project subpath",
                        "backend_requests": 0,
                        "page_errors": errors,
                        "widths": [320, 375, 414, 768],
                    }
                )
            )
            await browser.close()
    finally:
        server.shutdown()
        server.server_close()


asyncio.run(main())
