"""Headless real-browser checks; uses installed Edge without opening user windows."""

import asyncio
import json
import sys
from pathlib import Path

from playwright.async_api import async_playwright

sys.stdout.reconfigure(encoding="utf-8")
url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:18765"


async def main():
    output = Path(".cache/web-verification")
    output.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="msedge", headless=True)
        context = await browser.new_context(viewport={"width": 1440, "height": 1000})
        page = await context.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        await page.goto(url)
        await page.locator("details.anime").first.wait_for()
        anime_count = await page.locator("details.anime").count()
        await page.locator("details.anime summary").first.click()
        await page.locator("details.group").first.wait_for()
        await page.locator("details.group summary").first.click()
        await page.locator(".resources .resource").first.wait_for()
        assert "已采集集数" in await page.locator(".episodes").first.inner_text()
        links = await page.locator(".resources a").evaluate_all("els => els.map(e => e.href)")
        assert any(link.startswith("magnet:") for link in links)
        assert any(link.startswith("https:") for link in links)
        await page.screenshot(path=str(output / "anime.png"), full_page=True)
        for name in ["changes", "blocked", "unmatched", "settings"]:
            await page.locator(f'nav button[data-page="{name}"]').click()
            await page.locator("#content h2").wait_for()
            if name == "settings":
                await page.locator("#platforms").wait_for()
                assert "CATCHPLAY" in await page.locator("#platforms").input_value()
                assert "7897" in await page.locator("#proxy").input_value()
                await page.screenshot(path=str(output / "settings.png"), full_page=True)
        assert not errors, errors
        print(
            json.dumps(
                {
                    "browser": "Edge headless",
                    "anime": anime_count,
                    "resource_links": len(links),
                    "page_errors": errors,
                },
                ensure_ascii=False,
            )
        )
        await browser.close()


asyncio.run(main())
