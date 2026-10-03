import asyncio
import logging
import re
import time
import unicodedata
from datetime import datetime, timezone

import httpx

from .adapters import (parse_anibt_catalog, parse_anibt_groups, parse_feed, parse_garden_catalog,
                       parse_garden_resources, parse_mikan_catalog, parse_mikan_detail)
from .models import Anime
from .network import Network
from .rules import Rules, quarter_bounds, scope_for
from .store import now

log = logging.getLogger(__name__)


def normalized_title(value):
    return re.sub(r"[^\w]", "", unicodedata.normalize("NFKC", value).casefold())


def match_anime(title, animes):
    # Compare entire release title segments, not fuzzy prefixes which collapse seasons.
    text = re.sub(r"[\[【][^\]】]*[\]】]|\([^)]*\)", " ", title)
    text = re.sub(r"\s-\s*\d.*$|\sS\d{1,2}E\d.*$", "", text, flags=re.I)
    text = re.sub(r"第\s*\d+\s*[话話集].*$", "", text)
    segments = {normalized_title(t.strip()) for t in re.split(r"\s[/／]\s", text)}
    segments.discard("")
    found = {a.id for a in animes for alias in [a.title, *a.aliases] if normalized_title(alias) in segments}
    return next(iter(found)) if len(found) == 1 else None


def enrich_bgm(a, subject, ep_data):
    if subject.get("date"):
        a.premiere = subject["date"]
    if subject.get("name_cn"):
        a.title = subject["name_cn"]
    aliases = [subject.get("name", ""), subject.get("name_cn", "")]
    for field in subject.get("infobox", []):
        if field.get("key") in ["别名", "別名"]:
            value = field.get("value", [])
            if isinstance(value, list):
                aliases += [x.get("v", "") for x in value if isinstance(x, dict)]
    a.aliases = sorted(set(a.aliases + [x for x in aliases if x]))
    a.total_episodes = subject.get("total_episodes") or a.total_episodes
    dated = [ep for ep in ep_data.get("data", []) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", ep.get("airdate", ""))]
    a.episode_dates = sorted(set(a.episode_dates + [e["airdate"] for e in dated]))
    # Only a known final episode establishes an end date; never estimate by upload dates.
    if a.total_episodes:
        final = [e for e in dated if e.get("sort") == a.total_episodes]
        if final:
            a.end_date = max(e["airdate"] for e in final)
    a.evidence = sorted(set(a.evidence + ["Bangumi 首播日期及正片单集放送日期"]))


class Monitor:
    def __init__(self, config, store):
        self.config = config
        self.store = store
        self.net = Network(config.proxy)
        self.lock = asyncio.Lock()
        self.task = None
        self.progress = {"running": False, "message": "等待首次采集"}

    @property
    def rules(self):
        return Rules(self.config.groups, self.config.platforms)

    async def close(self):
        if self.task and self.task is not asyncio.current_task():
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        await self.net.close()

    async def run_source(self, source, operation, phase="scan"):
        previous = self.store.get_state(f"status:{source}", {})
        self.store.set_state(f"status:{source}", {**previous, "phase": phase, "last_attempt": now(), "error": None})
        try:
            await operation()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self.store.set_state(f"status:{source}", {**previous, "phase": "error", "last_attempt": now(),
                                                     "error": str(e)[:800]})
            log.warning("%s failed: %s", source, e)
            return False
        self.store.set_state(f"status:{source}", {"phase": "ready", "last_success": now(), "last_attempt": now(), "error": None})
        return True

    def ingest(self, releases, source, baseline):
        animes = self.store.animes()
        for r in releases:
            if r.anime_id and not self.store.anime(r.anime_id):
                # Source identity is retained in raw data; unknown works go to unmatched.
                r.anime_id = None
            if not r.anime_id:
                r.anime_id = match_anime(r.title, animes)
            self.store.ingest(r, self.rules, baseline=baseline, season=self.config.season)

    def relevant(self):
        start, _ = quarter_bounds(self.config.season)
        year, month = map(int, start[:7].split("-"))
        previous = f"{year - (month == 1)}-{month - 3 if month > 1 else 10:02}-01"
        return [a for a in self.store.animes() if scope_for(a, self.config.season) in ["current", "continuing"]
                or (scope_for(a, self.config.season) == "uncertain" and (not a.premiere or a.premiere >= previous))]

    async def catalog_mikan(self):
        host = self.config.mikan_host
        year, month = self.config.season.split("-")
        season_name = {"01": "冬", "04": "春", "07": "夏", "10": "秋"}[month]
        text = await self.net.text(host + "/Home/BangumiCoverFlowByDayOfWeek", {"year": year, "seasonStr": season_name})
        candidates = parse_mikan_catalog(text, self.config.season, host)
        errors = []
        baseline = not self.store.get_state("baseline:mikan", False)
        for i, a in enumerate(candidates):
            self.progress["mikan"] = f"番剧详情 {i+1}/{len(candidates)}"
            try:
                html = await self.net.text(host + "/Home/Bangumi/" + a.sources["mikan"])
                resolved, releases = parse_mikan_detail(html, a, host)
                if resolved.id != a.id:
                    self.store.merge_anime_id(a.id, resolved.id)
                self.store.upsert_anime(resolved)
                self.ingest(releases, "mikan", baseline)
            except Exception as e:
                self.store.upsert_anime(a)
                errors.append(f"{a.title}: {e}")
        if errors:
            raise ValueError("部分番剧详情采集失败：" + "; ".join(errors[:3]))

    async def catalog_garden(self):
        data = await self.net.json("https://api.animes.garden/subjects")
        for a in parse_garden_catalog(data):
            self.store.upsert_anime(a)

    async def catalog_anibt(self):
        year, month = self.config.season.split("-")
        label = {"01": "WINTER", "04": "SPRING", "07": "SUMMER", "10": "FALL"}[month]
        data = await self.net.json("https://anibt.net/api/seasons/anime", {"season": f"{year}-{label}"})
        for a in parse_anibt_catalog(data, self.config.season):
            self.store.upsert_anime(a)

    async def catalog_bgm(self):
        calendar = await self.net.json("https://api.bgm.tv/calendar")
        # Reset stale on-air evidence instead of preserving last quarter's calendar forever.
        for a in self.store.animes():
            a.on_air = False
            with self.store.db:
                self.store.db.execute("UPDATE anime SET data=? WHERE id=?", (a.model_dump_json(), a.id))
        for day in calendar:
            for item in day.get("items", []):
                if item.get("type") != 2:
                    continue
                a = Anime(id=f'bgm:{item["id"]}', bgm_id=item["id"], title=item.get("name_cn") or item["name"],
                          aliases=[item["name"], item.get("name_cn") or item["name"]], premiere=item.get("air_date"),
                          on_air=True, evidence=["Bangumi 当前放送日历"])
                self.store.upsert_anime(a)
        candidates = self.relevant()
        errors = []
        for i, a in enumerate(candidates):
            if not a.bgm_id:
                continue
            self.progress["bgm"] = f"放送日期核对 {i+1}/{len(candidates)}"
            try:
                subject = await self.net.json(f"https://api.bgm.tv/v0/subjects/{a.bgm_id}")
                ep_data = await self.net.json("https://api.bgm.tv/v0/episodes", {"subject_id": a.bgm_id, "type": 0, "limit": 100})
                enrich_bgm(a, subject, ep_data)
                self.store.upsert_anime(a)
            except Exception as e:
                errors.append(f"{a.title}: {e}")
        if errors:
            raise ValueError("部分放送资料获取失败：" + "; ".join(errors[:3]))

    async def backfill_garden(self, baseline):
        for i, a in enumerate(self.relevant()):
            if not a.bgm_id:
                continue
            self.progress["garden"] = f"补查 {a.title}"
            page = 1
            while True:
                data = await self.net.json("https://api.animes.garden/resources", {"subject": a.bgm_id, "pageSize": 200, "page": page, "duplicate": "false"})
                self.ingest(parse_garden_resources(data, a.id), "garden", baseline)
                if data.get("pagination", {}).get("complete", len(data["resources"]) < 200) or not data["resources"]:
                    break
                page += 1
                if page > 200:
                    raise ValueError("资源分页超过安全上限，补查未完成")

    async def backfill_anibt(self, baseline):
        for a in self.relevant():
            if not a.bgm_id:
                continue
            self.progress["anibt"] = f"补查 {a.title}"
            try:
                data = await self.net.json("https://anibt.net/api/anime/groups", {"bgmId": a.bgm_id})
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    continue
                raise
            self.ingest(parse_anibt_groups(data), "anibt", baseline)
            # The groups API returns recent items only. Read each group's per-anime RSS too.
            for group in data["data"]["groups"]:
                content = await self.net.text("https://anibt.net/rss/anime.xml", {"bgmId": a.bgm_id, "groupSlug": group["slug"]})
                rs = parse_feed(content, "anibt", a.id)
                for r in rs:
                    r.rss = str(httpx.URL("https://anibt.net/rss/anime.xml", params={"bgmId": a.bgm_id, "groupSlug": group["slug"]}))
                self.ingest(rs, "anibt", baseline)

    async def recent(self, source, baseline):
        if source == "mikan":
            content = await self.net.text(self.config.mikan_host + "/RSS/Classic")
            self.ingest(parse_feed(content, "mikan"), source, baseline)
        elif source == "anibt":
            content = await self.net.text("https://anibt.net/rss/magnets.xml")
            self.ingest(parse_feed(content, "anibt"), source, baseline)
        else:
            page = 1
            checkpoint = self.store.get_state("checkpoint:garden")
            newest = checkpoint
            while True:
                params = {"pageSize": 200, "page": page}
                if checkpoint:
                    params["after"] = checkpoint
                data = await self.net.json("https://api.animes.garden/resources", params)
                self.ingest(parse_garden_resources(data), source, baseline)
                newest = max([newest or "", *[x.get("createdAt", "") for x in data["resources"]]])
                if data.get("pagination", {}).get("complete", True) or not data["resources"]:
                    break
                if baseline and page >= 2:
                    # Per-anime bootstrap covers history; global listing seeds unmatched recent releases.
                    break
                page += 1
                if page > 200:
                    raise ValueError("增量分页超过安全上限，未推进采集游标")
            if newest:
                self.store.set_state("checkpoint:garden", newest)

    async def scan(self, full=False):
        async with self.lock:
            self.progress = {"running": True, "message": "正在采集", "started_at": now()}
            try:
                season = self.config.season
                catalog_key = f"catalog:{season}"
                catalog_due = full or time.time() - self.store.get_state(catalog_key, 0) >= self.config.catalog_hours * 3600
                if catalog_due:
                    self.progress["message"] = "刷新番剧目录与放送资料"
                    ok = await asyncio.gather(self.run_source("mikan", self.catalog_mikan, "catalog"),
                                              self.run_source("garden", self.catalog_garden, "catalog"),
                                              self.run_source("anibt", self.catalog_anibt, "catalog"))
                    bgm_ok = await self.run_source("bgm", self.catalog_bgm, "metadata")
                    if all(ok) and bgm_ok:
                        self.store.set_state(catalog_key, time.time())

                async def collect(source):
                    baseline = not self.store.get_state(f"baseline:{source}", False)
                    daily_key = f"backfill:{season}:{source}"
                    due = full or baseline or time.time() - self.store.get_state(daily_key, 0) >= 86400
                    async def operation():
                        if due:
                            if source == "garden":
                                await self.backfill_garden(baseline)
                            elif source == "anibt":
                                await self.backfill_anibt(baseline)
                            elif not catalog_due:
                                await self.catalog_mikan()
                        await self.recent(source, baseline)
                        if due:
                            self.store.set_state(daily_key, time.time())
                        self.store.set_state(f"baseline:{source}", True)
                    await self.run_source(source, operation, "backfill" if due else "incremental")

                self.progress["message"] = "补齐发布组和集数" if catalog_due else "采集最新资源"
                await asyncio.gather(*(collect(source) for source in ["mikan", "garden", "anibt"]))
                self.store.set_state("last_scan", now())
            finally:
                self.progress.update(running=False, message="本轮采集结束", finished_at=now())

    async def loop(self):
        while True:
            try:
                await self.scan()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("monitor cycle failed")
            await asyncio.sleep(self.config.poll_minutes * 60)
