import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .models import Anime, Release
from .rules import episodes, group_key, normalize_infohash, scope_for, title_group


def now():
    return datetime.now(timezone.utc).isoformat()


def dump(value):
    return json.dumps(value, ensure_ascii=False)


class Store:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS anime(id TEXT PRIMARY KEY, data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS origins(source TEXT, source_id TEXT, resource_id TEXT, data TEXT, reasons TEXT,
          first_seen TEXT, PRIMARY KEY(source,source_id));
        CREATE INDEX IF NOT EXISTS origin_resource ON origins(resource_id);
        CREATE TABLE IF NOT EXISTS seen_groups(anime_id TEXT, group_id TEXT, first_seen TEXT,
          PRIMARY KEY(anime_id,group_id));
        CREATE TABLE IF NOT EXISTS changes(id INTEGER PRIMARY KEY AUTOINCREMENT, anime_id TEXT, group_id TEXT,
          group_name TEXT, discovered_at TEXT, UNIQUE(anime_id,group_id));
        CREATE TABLE IF NOT EXISTS state(key TEXT PRIMARY KEY, value TEXT);
        """)
        self.db.commit()

    def close(self):
        self.db.close()

    def get_state(self, key, default=None):
        row = self.db.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_state(self, key, value):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO state VALUES(?,?)", (key, dump(value)))

    def upsert_anime(self, anime: Anime):
        old = self.anime(anime.id)
        if old:
            old.aliases = sorted(set(old.aliases + anime.aliases + [old.title, anime.title]))
            old.sources.update(anime.sources)
            old.evidence = sorted(set(old.evidence + anime.evidence))
            old.episode_dates = sorted(set(old.episode_dates + anime.episode_dates))
            old.on_air = old.on_air or anime.on_air
            for key in ["premiere", "end_date", "bgm_id", "season_hint", "total_episodes"]:
                if getattr(anime, key) is not None:
                    setattr(old, key, getattr(anime, key))
            if not old.title:
                old.title = anime.title
            anime = old
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO anime VALUES(?,?)", (anime.id, anime.model_dump_json()))

    def anime(self, anime_id):
        row = self.db.execute("SELECT data FROM anime WHERE id=?", (anime_id,)).fetchone()
        return Anime.model_validate_json(row[0]) if row else None

    def animes(self):
        return [Anime.model_validate_json(row[0]) for row in self.db.execute("SELECT data FROM anime")]

    def set_override(self, anime_id, value):
        a = self.anime(anime_id)
        if not a:
            raise KeyError(anime_id)
        a.override = value
        with self.db:
            self.db.execute("UPDATE anime SET data=? WHERE id=?", (a.model_dump_json(), anime_id))

    def merge_anime_id(self, old_id, new_id):
        if old_id == new_id:
            return
        with self.db:
            for row in self.db.execute("SELECT source,source_id,data FROM origins").fetchall():
                r = Release.model_validate_json(row["data"])
                if r.anime_id == old_id:
                    r.anime_id = new_id
                    self.db.execute("UPDATE origins SET data=? WHERE source=? AND source_id=?",
                                    (r.model_dump_json(), row["source"], row["source_id"]))
            self.db.execute("INSERT OR IGNORE INTO seen_groups SELECT ?,group_id,first_seen FROM seen_groups WHERE anime_id=?", (new_id, old_id))
            self.db.execute("DELETE FROM seen_groups WHERE anime_id=?", (old_id,))
            self.db.execute("UPDATE OR IGNORE changes SET anime_id=? WHERE anime_id=?", (new_id, old_id))
            self.db.execute("DELETE FROM changes WHERE anime_id=?", (old_id,))
            self.db.execute("DELETE FROM anime WHERE id=?", (old_id,))

    def ingest(self, r: Release, rules, baseline=False, season="2026-10"):
        if not r.group:
            r.group = title_group(r.title) or r.publisher or "未署名"
        reasons = rules.check(r)
        resource_id = normalize_infohash(r.magnet) or f"{r.source}:{r.source_id}"
        ts = now()
        with self.db:
            self.db.execute("""INSERT INTO origins VALUES(?,?,?,?,?,?)
              ON CONFLICT(source,source_id) DO UPDATE SET resource_id=excluded.resource_id,
              data=excluded.data,reasons=excluded.reasons""",
                            (r.source, r.source_id, resource_id, r.model_dump_json(), dump(reasons), ts))
            if r.anime_id:
                key = group_key(r.group)
                inserted = self.db.execute("INSERT OR IGNORE INTO seen_groups VALUES(?,?,?)",
                                           (r.anime_id, key, ts)).rowcount
                a = self.anime(r.anime_id)
                if inserted and not baseline and not reasons and a and scope_for(a, season) in ["current", "continuing"]:
                    self.db.execute("INSERT OR IGNORE INTO changes(anime_id,group_id,group_name,discovered_at) VALUES(?,?,?,?)",
                                    (r.anime_id, key, r.group, ts))

    def reclassify(self, rules):
        with self.db:
            for row in self.db.execute("SELECT source,source_id,data FROM origins").fetchall():
                self.db.execute("UPDATE origins SET reasons=? WHERE source=? AND source_id=?",
                                (dump(rules.check(Release.model_validate_json(row["data"]))), row["source"], row["source_id"]))

    def releases(self, anime_id=None, group=None, blocked=False, unmatched=False):
        result = {}
        for row in self.db.execute("SELECT * FROM origins ORDER BY first_seen DESC"):
            r = Release.model_validate_json(row["data"])
            reasons = json.loads(row["reasons"])
            if (anime_id and r.anime_id != anime_id) or (group and group_key(r.group) != group_key(group)):
                continue
            if unmatched and r.anime_id:
                continue
            if blocked != bool(reasons):
                continue
            origin = {"source": r.source, "source_id": r.source_id, "url": r.url, "torrent": r.torrent,
                      "rss": r.rss, "reasons": reasons}
            key = row["resource_id"]
            if key in result:
                result[key]["origins"].append(origin)
                continue
            result[key] = {**r.model_dump(exclude={"raw"}), "id": key, "episodes": episodes(r.title, r.episode_key),
                           "first_seen": row["first_seen"], "reasons": reasons, "origins": [origin]}
        return list(result.values())

    def groups(self, anime_id):
        groups = {}
        for r in self.releases(anime_id):
            key = group_key(r["group"])
            g = groups.setdefault(key, {"id": key, "name": r["group"], "episodes": set(), "sources": set(),
                                        "rss": set(), "last_published": "", "release_count": 0})
            g["episodes"].update(r["episodes"])
            g["sources"].update(o["source"] for o in r["origins"])
            g["rss"].update(o["rss"] for o in r["origins"] if o["rss"])
            g["last_published"] = max(g["last_published"], r["published_at"])
            g["release_count"] += 1
        for g in groups.values():
            g["episodes"] = sorted(g["episodes"], key=float)
            g["sources"] = sorted(g["sources"])
            g["rss"] = sorted(g["rss"])
        return sorted(groups.values(), key=lambda x: x["last_published"], reverse=True)

    def changes(self, after=0, since=None):
        return [dict(row) for row in self.db.execute("SELECT * FROM changes WHERE id>? AND (? IS NULL OR discovered_at>?) ORDER BY id DESC LIMIT 500",
                                                    (after, since, since))]
