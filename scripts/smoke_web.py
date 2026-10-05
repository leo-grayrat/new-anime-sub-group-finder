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
        errors, requests = [], []
        page.on("request", lambda request: requests.append(request.url))
        page.on("pageerror", lambda e: errors.append(str(e)))
        await page.goto(url)
        await page.locator("details.anime[data-anime]").first.wait_for()
        assert await page.locator('link[href="/static/vendor/bangumi-r771.css"]').count() == 1
        await page.wait_for_function(
            "[...document.querySelectorAll('.finder-cover img')].some(e => e.complete && e.naturalWidth > 0)",
            timeout=60000,
        )
        await page.wait_for_function(
            "[...document.querySelectorAll('.finder-cover img')].every(e => "
            "e.getBoundingClientRect().top >= innerHeight || e.complete)",
            timeout=60000,
        )
        assert (
            await page.locator("#browserItemList .finder-cover").count()
            == await page.locator("details.anime[data-anime]").count()
        )
        await page.screenshot(path=str(output / "anime-list.png"), full_page=False)
        async with page.expect_popup() as preview:
            await page.locator(".finder-cover:not(.unavailable)").first.click()
        popup = await preview.value
        await popup.wait_for_load_state()
        assert popup.url.startswith("https://lain.bgm.tv/pic/cover/")
        await popup.wait_for_function("document.querySelector('img')?.naturalWidth > 0")
        assert await page.locator(".finder-cover img").evaluate_all(
            "els => els.every(e => e.src.startsWith('https://lain.bgm.tv/pic/cover/'))"
        )
        assert not any("/api/anime/" in request and request.endswith("/cover") for request in requests)
        await popup.close()
        anime_count = await page.locator("details.anime[data-anime]").count()
        await page.locator("details.anime[data-anime] summary").first.click()
        await page.locator("details.group").first.wait_for()
        await page.locator("details.group summary").first.click()
        await page.locator(".resources .resource").first.wait_for()
        assert "集数：" in await page.locator(".episodes").first.inner_text()
        links = await page.locator(".resources a").evaluate_all("els => els.map(e => e.href)")
        assert any(link.startswith("magnet:") for link in links)
        assert any(link.startswith("https:") for link in links)
        await page.screenshot(path=str(output / "anime.png"), full_page=False)
        headings = {
            "changes": "近 24h 更新",
            "blocked": "已屏蔽记录",
            "unmatched": "未匹配资源",
            "settings": "设置",
        }
        for name, heading in headings.items():
            await page.locator(f'nav [data-page="{name}"]').click()
            await page.get_by_role("heading", name=heading, exact=True).wait_for()
            if name == "blocked":
                blocked = await (await page.request.get(url + "/api/blocked")).json()
                assert await page.locator("details.blocked-group").count() == len(blocked["items"])
                if blocked["items"]:
                    await page.locator("details.blocked-group summary").first.click()
                    await page.locator("[data-blocked-anime]").first.wait_for()
                    await page.locator("[data-blocked-anime] summary").first.click()
                    await page.locator(".resources .resource").first.wait_for()
                    assert await page.locator(".blocked-reasons").count() == 1
                    assert await page.locator(".blocked-animes .reason").count() == 0
                await page.screenshot(path=str(output / "blocked.png"), full_page=False)
            if name == "changes":
                updates = await (await page.request.get(url + "/api/updates")).json()
                assert await page.locator("details.recent-update").count() == len(
                    {x["anime_id"] for x in updates["items"]}
                )
                assert await page.locator("details.recent-update").evaluate_all(
                    "els => new Set(els.map(e => e.dataset.updateAnime)).size === els.length"
                )
                if updates["items"]:
                    assert await page.locator("#change-items .finder-cover").count() == len(
                        {x["anime_id"] for x in updates["items"]}
                    )
                    await page.wait_for_function(
                        "[...document.querySelectorAll('#change-items .finder-cover img')].some(e => e.complete && e.naturalWidth > 0)",
                        timeout=60000,
                    )
                    await page.locator("details.recent-update > summary").first.click()
                    expected_groups = sum(
                        x["anime_id"] == updates["items"][0]["anime_id"] for x in updates["items"]
                    )
                    await page.locator("details.recent-group").first.wait_for()
                    assert await page.locator("details.recent-group").count() == expected_groups
                    await page.locator("details.recent-group > summary").first.click()
                    await page.locator(".resources .resource").first.wait_for()
                    assert (
                        await page.locator(".resources .resource").count()
                        == updates["items"][0]["release_count"]
                    )
                await page.screenshot(path=str(output / "updates.png"), full_page=False)
            if name == "settings":
                await page.locator("#platforms").wait_for()
                assert "CATCHPLAY" in await page.locator("#platforms").input_value()
                assert "7897" in await page.locator("#proxy").input_value()
                assert "NEST" in await page.locator("#review-groups").input_value()
                await page.screenshot(path=str(output / "settings.png"), full_page=True)
        saved = []

        async def inspect_save(route):
            if route.request.method == "PUT":
                saved.append(route.request.post_data_json)
                await route.fulfill(json={"ok": True})
            else:
                await route.continue_()

        original_config = await (await page.request.get(url + "/api/config")).json()
        await page.route("**/api/config", inspect_save)
        await page.locator("#review-groups").fill("NEST\n生肉/不明字幕\n待核实测试组")
        await page.locator("#save-settings").click()
        await page.wait_for_function("document.querySelector('#notice').textContent === '已保存'")
        assert len(saved) == 1 and saved[0]["review_groups"][-1] == "待核实测试组"
        assert set(saved[0]) == set(original_config)
        assert saved[0]["groups"] == original_config["groups"]
        assert saved[0]["data_dir"] == original_config["data_dir"]
        await page.unroute("**/api/config", inspect_save)
        await page.locator("#notice").evaluate("e => e.hidden = true")
        await page.locator('nav [data-page="anime"]').click()
        await page.locator("details.anime[data-anime]").first.wait_for()
        await page.locator("#search_text").fill("冰之城墙")
        await page.locator("#search_text").press("Enter")
        await page.wait_for_function("document.querySelectorAll('details.anime[data-anime]').length === 1")
        assert "冰之城墙" in await page.locator(".anime-title").inner_text()
        await page.locator("#search_text").fill("")
        await page.locator("#search_text").press("Enter")
        await page.wait_for_function("document.querySelectorAll('details.anime[data-anime]').length > 1")
        await page.locator('[data-scope="continuing"]').click()
        await page.wait_for_function(
            "document.querySelector('#browserTools').textContent.includes('跨季续播')"
        )
        await page.locator('[data-scope="active"]').click()
        await page.wait_for_function(
            "document.querySelector('#browserTools').textContent.includes('当季与续播')"
        )
        for width in [320, 375, 414, 768]:
            await page.set_viewport_size({"width": width, "height": 844})
            await page.evaluate("window.scrollTo(0, 0)")
            await page.wait_for_function(
                "[...document.querySelectorAll('#navMenuNeue a')].every(e => "
                "parseFloat(getComputedStyle(e).paddingLeft) >= 7)",
                timeout=2000,
            )
            assert await page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), (
                f"{width}px布局超出视口"
            )
            assert await page.locator("#content").evaluate(
                "e => e.getBoundingClientRect().right <= window.innerWidth"
            ), f"{width}px内容被裁切"
            assert await page.locator("#columnSubjectBrowserA").evaluate(
                "e => e.getBoundingClientRect().height > 100"
            ), f"{width}px列表容器高度坍塌"
            assert await page.locator(".group-count").first.evaluate(
                "e => e.getBoundingClientRect().right <= window.innerWidth"
            ), f"{width}px组数被裁切"
            assert await page.locator(".finder-cover").first.evaluate(
                "e => e.getBoundingClientRect().right < e.closest('li').querySelector('.inner').getBoundingClientRect().left"
            ), f"{width}px封面与文字重叠"
            assert await page.locator('nav [data-page="settings"]').is_visible()
            assert await page.locator("#navMenuNeue a").evaluate_all(
                "els => els.every(e => parseFloat(getComputedStyle(e).paddingLeft) >= 7)"
            ), f"{width}px导航间距不足"
            await page.screenshot(
                path=str(output / f"mobile-{width}.png"), full_page=False, animations="disabled"
            )
            await page.locator("details.anime[data-anime] summary").first.click()
            await page.locator("details.group").first.wait_for()
            await page.locator("details.group summary").first.click()
            await page.locator(".resources .resource").first.wait_for()
            assert await page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), (
                f"{width}px展开资源超出视口"
            )
            await page.locator('nav [data-page="settings"]').click()
            await page.locator("#review-groups").wait_for()
            assert await page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), (
                f"{width}px设置超出视口"
            )
            await page.locator('nav [data-page="changes"]').click()
            await page.get_by_role("heading", name="近 24h 更新", exact=True).wait_for()
            if await page.locator("details.recent-update").count():
                await page.locator("details.recent-update > summary").first.click()
                await page.locator("details.recent-group > summary").first.click()
                await page.locator(".resources .resource").first.wait_for()
                assert await page.locator(".group-count").first.evaluate(
                    "e => e.getBoundingClientRect().right <= window.innerWidth"
                ), f"{width}px更新条数被裁切"
            assert await page.locator("#content").evaluate(
                "e => e.getBoundingClientRect().right <= window.innerWidth"
            ), f"{width}px更新列表被裁切"
            await page.screenshot(
                path=str(output / f"updates-mobile-{width}.png"), full_page=False, animations="disabled"
            )
            await page.locator('nav [data-page="anime"]').click()
            await page.locator("details.anime[data-anime]").first.wait_for()
        await page.set_viewport_size({"width": 1440, "height": 1000})
        await page.evaluate("window.scrollTo(0, 0)")
        failure_status = await (await page.request.get(url + "/api/status")).json()
        failure_status["sources"]["garden"]["error"] = "模拟来源超时"
        failure_status["sources"]["garden"]["stale"] = True

        async def mock_failure(route):
            await route.fulfill(json=failure_status)

        await page.route("**/api/status", mock_failure)
        await page.goto(url)
        await page.locator("details.anime[data-anime]").first.wait_for()
        assert await page.locator("details.anime[data-anime]").count() == anime_count
        assert "模拟来源超时" in await page.locator(".source-error").inner_text()
        await page.screenshot(path=str(output / "source-failure.png"), full_page=False)
        await page.unroute("**/api/status", mock_failure)

        async def missing_cover(route):
            await route.fulfill(status=404, json={"detail": "封面暂不可用"})

        await page.route("https://lain.bgm.tv/**", missing_cover)
        await page.goto(url)
        await page.locator(".finder-cover.unavailable").first.wait_for()
        assert await page.locator("details.anime[data-anime]").count() > 0
        assert not await page.locator(".finder-cover.unavailable").first.get_attribute("href")
        await page.unroute("https://lain.bgm.tv/**", missing_cover)
        assert not errors, errors
        print(
            json.dumps(
                {
                    "browser": "Edge headless",
                    "anime": anime_count,
                    "resource_links": len(links),
                    "page_errors": errors,
                    "responsive_widths": [320, 375, 414, 768],
                    "settings_payload": "verified without changing user settings",
                    "source_failure": "error visible and existing list retained",
                    "covers": "real images, preview and missing-image fallback verified",
                },
                ensure_ascii=False,
            )
        )
        await browser.close()


asyncio.run(main())
