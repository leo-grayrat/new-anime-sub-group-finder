from datetime import date, datetime, timedelta, timezone

from .rules import group_key, quarter_bounds, scope_for


class QueryService:
    def __init__(self, monitor):
        self.monitor = monitor
        self.store = monitor.store

    def status(self):
        statuses = {}
        for source in ["mikan", "garden", "anibt", "bgm"]:
            status = self.store.get_state(f"status:{source}", {"phase": "pending", "last_success": None})
            last = status.get("last_success")
            age = (
                (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds() if last else None
            )
            status["stale"] = age is None or age > self.monitor.config.poll_minutes * 60 * 3
            if source == "bgm" and age is not None:
                status["stale"] = age > self.monitor.config.catalog_hours * 3600 * 2
            status["baseline_complete"] = (
                bool(last) if source == "bgm" else self.store.get_state(f"baseline:{source}", False)
            )
            status["details"] = self.store.get_state(f"details:{source}", {})
            status["error"] = status.get("error") or status["details"].get("error")
            statuses[source] = status
        return {
            "sources": statuses,
            "progress": self.monitor.progress,
            "last_scan": self.store.get_state("last_scan"),
            "season": self.monitor.config.season,
            "data_time": self.store.get_state("last_scan"),
            "proxy": self.monitor.config.proxy or "直连",
        }

    def envelope(self, items):
        return {"items": items, "status": self.status()}

    def groups_for(self, anime_id, season=None):
        season = season or self.monitor.config.season
        start, end = quarter_bounds(season)
        a = self.store.anime(anime_id)
        groups = self.store.groups(anime_id)
        if not a or scope_for(a, season) != "continuing":
            return groups
        since = (date.fromisoformat(start) - timedelta(days=14)).isoformat()
        active = {
            group_key(o["group"])
            for r in self.store.releases(anime_id)
            for o in r["origins"]
            if o["published_at"] and since <= o["published_at"][:10] < end
        }
        return [g for g in groups if g["id"] in active]

    def list_anime(self, season=None, include_continuing=True, keyword="", scope="active", has_groups=False):
        season = season or self.monitor.config.season
        result = []
        for a in self.store.animes():
            category = scope_for(a, season)
            if scope == "active" and category not in (
                ["current", "continuing"] if include_continuing else ["current"]
            ):
                continue
            if scope not in ["active", "all"] and category != scope:
                continue
            if keyword and not any(keyword.casefold() in name.casefold() for name in [a.title, *a.aliases]):
                continue
            groups = self.groups_for(a.id, season)
            if has_groups and not groups:
                continue
            result.append(
                {
                    **a.model_dump(),
                    "scope": category,
                    "group_count": len(groups),
                    "groups": [{"name": g["name"], "episodes": g["episodes"]} for g in groups],
                }
            )
        result.sort(key=lambda a: (a["scope"] != "current", -a["group_count"], a["title"]))
        return self.envelope(result)

    def list_groups(self, anime_id, season=None):
        return self.envelope(self.groups_for(anime_id, season))

    def list_releases(self, anime_id, group=None, season=None):
        quarter_bounds(season or self.monitor.config.season)
        releases = self.store.releases(anime_id, group)
        if not group:
            active = {g["id"] for g in self.groups_for(anime_id, season)}
            releases = [r for r in releases if any(group_key(o["group"]) in active for o in r["origins"])]
        return self.envelope(releases)

    def list_changes(self, after=0, since=None, season=None):
        result = []
        season = season or self.monitor.config.season
        page = self.store.changes(after, since)
        for change in page:
            a = self.store.anime(change["anime_id"])
            if a and scope_for(a, season) in ["current", "continuing"]:
                g = next((g for g in self.groups_for(a.id, season) if g["id"] == change["group_id"]), None)
                if g:
                    result.append({**change, "anime_title": a.title, "episodes": g["episodes"]})
        cursor = page[-1]["id"] if page else after
        has_more = (
            self.store.db.execute(
                "SELECT 1 FROM changes WHERE id>? AND (? IS NULL OR discovered_at>?) LIMIT 1",
                (cursor, since, since),
            ).fetchone()
            is not None
        )
        return {**self.envelope(result), "cursor": cursor, "has_more": has_more}

    def list_updates(self, season=None):
        season = season or self.monitor.config.season
        quarter_bounds(season)
        end = datetime.now(timezone.utc)
        start = end - timedelta(hours=24)
        anime = {a.id: a for a in self.store.animes() if scope_for(a, season) in ["current", "continuing"]}
        result = {}
        for release in self.store.releases():
            a = anime.get(release["anime_id"])
            if not a:
                continue
            # Deduplicated resources may carry several sites' publication dates.
            published = {}
            for origin in release["origins"]:
                try:
                    timestamp = datetime.fromisoformat(origin["published_at"].replace("Z", "+00:00"))
                except ValueError:
                    continue
                if timestamp.tzinfo is None:
                    timestamp = timestamp.replace(tzinfo=timezone.utc)
                timestamp = timestamp.astimezone(timezone.utc)
                if not start <= timestamp <= end:
                    continue
                group_id = group_key(origin["group"])
                if group_id not in published or timestamp > published[group_id][0]:
                    published[group_id] = (timestamp, origin["group"])
            for group_id, (timestamp, name) in published.items():
                item = result.setdefault(
                    (a.id, group_id),
                    {
                        "anime_id": a.id,
                        "anime_title": a.title,
                        "bgm_id": a.bgm_id,
                        "cover_url": a.cover_url,
                        "group_id": group_id,
                        "group_name": name,
                        "updated_at": timestamp.isoformat(),
                        "episodes": set(),
                        "releases": [],
                    },
                )
                item["updated_at"] = max(item["updated_at"], timestamp.isoformat())
                item["episodes"].update(release["episodes"])
                item["releases"].append({**release, "published_at": timestamp.isoformat()})
        items = list(result.values())
        for item in items:
            item["episodes"] = sorted(item["episodes"], key=float)
            item["release_count"] = len(item["releases"])
            item["releases"].sort(key=lambda release: release["published_at"], reverse=True)
        items.sort(
            key=lambda item: (item["updated_at"], item["anime_title"], item["group_name"]), reverse=True
        )
        return {**self.envelope(items), "window_start": start.isoformat(), "window_end": end.isoformat()}

    def list_blocked(self, season=None):
        season = season or self.monitor.config.season
        start, end = quarter_bounds(season)
        local_tz = timezone(timedelta(hours=8))
        start = datetime.fromisoformat(start).replace(tzinfo=local_tz)
        end = datetime.fromisoformat(end).replace(tzinfo=local_tz)
        anime = {a.id: a for a in self.store.animes() if scope_for(a, season) in ["current", "continuing"]}
        grouped = {}
        display_names = {
            group_key(name): name
            for name in [*self.monitor.config.groups, *self.monitor.config.review_groups]
        }
        resource_ids = set()
        for release in self.store.releases(blocked=True):
            a = anime.get(release["anime_id"])
            if not a:
                continue
            names = {}
            for origin in release["origins"]:
                try:
                    published = datetime.fromisoformat(origin["published_at"].replace("Z", "+00:00"))
                except ValueError:
                    continue
                if published.tzinfo is None:
                    published = published.replace(tzinfo=timezone.utc)
                if start <= published < end:
                    key = group_key(origin["group"])
                    names.setdefault(key, origin["group"])
            for key, name in names.items():
                name = display_names.get(key, name)
                group = grouped.setdefault(key, {"group_id": key, "group_name": name, "animes": {}})
                item = group["animes"].setdefault(
                    a.id,
                    {
                        "id": a.id,
                        "title": a.title,
                        "bgm_id": a.bgm_id,
                        "cover_url": a.cover_url,
                        "episodes": set(),
                        "reasons": set(),
                        "releases": [],
                    },
                )
                item["episodes"].update(release["episodes"])
                item["reasons"].update(release["reasons"])
                item["releases"].append(release)
                resource_ids.add(release["id"])
        items = list(grouped.values())
        for group in items:
            group["animes"] = sorted(group["animes"].values(), key=lambda a: a["title"])
            group["anime_count"] = len(group["animes"])
            group["release_count"] = sum(len(a["releases"]) for a in group["animes"])
            for a in group["animes"]:
                a["episodes"] = sorted(a["episodes"], key=float)
                a["reasons"] = sorted(a["reasons"])
        items.sort(key=lambda g: (-g["anime_count"], -g["release_count"], g["group_id"]))
        return {**self.envelope(items), "total": len(resource_ids), "season": season}
