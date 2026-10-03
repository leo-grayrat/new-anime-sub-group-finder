from datetime import datetime, timezone

from .rules import scope_for


class QueryService:
    def __init__(self, monitor):
        self.monitor = monitor
        self.store = monitor.store

    def status(self):
        statuses = {}
        for source in ["mikan", "garden", "anibt", "bgm"]:
            status = self.store.get_state(f"status:{source}", {"phase": "pending", "last_success": None})
            last = status.get("last_success")
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds() if last else None
            status["stale"] = age is None or age > self.monitor.config.poll_minutes * 60 * 3
            if source == "bgm" and age is not None:
                status["stale"] = age > self.monitor.config.catalog_hours * 3600 * 2
            status["baseline_complete"] = self.store.get_state(f"baseline:{source}", False)
            statuses[source] = status
        return {"sources": statuses, "progress": self.monitor.progress, "last_scan": self.store.get_state("last_scan"),
                "season": self.monitor.config.season, "data_time": self.store.get_state("last_scan"),
                "proxy": self.monitor.config.proxy or "直连"}

    def envelope(self, items):
        return {"items": items, "status": self.status()}

    def list_anime(self, season=None, include_continuing=True, keyword="", scope="active", has_groups=False):
        season = season or self.monitor.config.season
        result = []
        for a in self.store.animes():
            category = scope_for(a, season)
            if scope == "active" and category not in (["current", "continuing"] if include_continuing else ["current"]):
                continue
            if scope not in ["active", "all"] and category != scope:
                continue
            if keyword and not any(keyword.casefold() in name.casefold() for name in [a.title, *a.aliases]):
                continue
            groups = self.store.groups(a.id)
            if has_groups and not groups:
                continue
            result.append({**a.model_dump(), "scope": category, "group_count": len(groups),
                           "groups": [{"name": g["name"], "episodes": g["episodes"]} for g in groups]})
        result.sort(key=lambda a: (-a["group_count"], a["title"]))
        return self.envelope(result)

    def list_groups(self, anime_id):
        return self.envelope(self.store.groups(anime_id))

    def list_releases(self, anime_id, group=None):
        return self.envelope(self.store.releases(anime_id, group))

    def list_changes(self, after=0, since=None, season=None):
        result = []
        season = season or self.monitor.config.season
        for change in self.store.changes(after, since):
            a = self.store.anime(change["anime_id"])
            if a and scope_for(a, season) in ["current", "continuing"]:
                g = next((g for g in self.store.groups(a.id) if g["id"] == change["group_id"]), None)
                if g:
                    result.append({**change, "anime_title": a.title, "episodes": g["episodes"]})
        cursor = self.store.db.execute("SELECT COALESCE(MAX(id),0) FROM changes").fetchone()[0]
        return {**self.envelope(result), "cursor": cursor}
