"""Build a read-only Pages site from a consistent SQLite snapshot."""

import argparse
import asyncio
import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from .config import load_config
from .covers import Covers
from .monitor import Monitor
from .rules import group_key
from .service import QueryService
from .store import Store


async def export_site(monitor, output, fetch_covers=True):
    output = Path(output).resolve()
    static = Path(__file__).parent / "static"
    if (
        output == Path.cwd().resolve()
        or output.is_relative_to(static.parent.resolve())
        or output.is_relative_to(Path(monitor.config.data_dir).resolve())
    ):
        raise ValueError("请选择独立的静态网站输出目录")
    snapshot = Store(":memory:")
    monitor.store.db.backup(snapshot.db)
    reader = SimpleNamespace(
        config=monitor.config, store=snapshot, net=monitor.net, progress=monitor.progress
    )
    query = QueryService(reader)
    try:
        status = query.status()
        status.pop("proxy", None)
        status["progress"] = {"running": False, "message": "只读快照"}
        for source in status["sources"].values():
            source.pop("details", None)
            if source.get("error"):
                for private in [monitor.config.data_dir, monitor.config.proxy]:
                    if private:
                        source["error"] = source["error"].replace(private, "[本机配置]")
        for name, source in status["sources"].items():
            source["stale_after_seconds"] = (
                monitor.config.catalog_hours * 7200 if name == "bgm" else monitor.config.poll_minutes * 180
            )
        anime = query.list_anime(scope="all")["items"]
        groups, releases = {}, {}
        for a in anime:
            groups[a["id"]] = query.list_groups(a["id"])["items"]
            available = snapshot.releases(a["id"])
            releases[a["id"]] = {
                g["id"]: [r for r in available if any(group_key(o["group"]) == g["id"] for o in r["origins"])]
                for g in groups[a["id"]]
            }
        blocked = query.list_blocked()
        blocked.pop("status", None)
        updates = query.list_updates()
        updates.pop("status", None)
        unmatched = snapshot.releases(unmatched=True)
        data = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "status": status,
            "anime": anime,
            "groups": groups,
            "releases": releases,
            "updates": updates,
            "blocked": blocked,
            "unmatched": {"items": unmatched[:500], "total": len(unmatched)},
            "covers": {},
        }
        output.mkdir(parents=True, exist_ok=True)
        shutil.copytree(static, output / "static", dirs_exist_ok=True)
        html = (static / "index.html").read_text(encoding="utf-8")
        html = html.replace("<head>", '<head>\n<meta name="finder-mode" content="static">')
        html = html.replace('href="/static/', 'href="static/').replace('src="/static/', 'src="static/')
        (output / "index.html").write_text(html, encoding="utf-8")
        (output / ".nojekyll").touch()
        if fetch_covers:
            covers = Covers(reader)
            needed = {a["id"] for a in anime if a["group_count"] and a["scope"] in ["current", "continuing"]}
            needed.update(a["id"] for g in blocked["items"] for a in g["animes"])
            for anime_id in sorted(needed):
                try:
                    image, media_type = await covers.get(anime_id)
                    suffix = {
                        "image/jpeg": "jpg",
                        "image/png": "png",
                        "image/webp": "webp",
                        "image/gif": "gif",
                    }[media_type]
                    import hashlib

                    relative = "covers/" + hashlib.sha256(anime_id.encode()).hexdigest() + "." + suffix
                    target = output / relative
                    target.parent.mkdir(exist_ok=True)
                    target.write_bytes(image)
                    data["covers"][anime_id] = relative
                except Exception as error:
                    logging.warning("封面未导出 %s: %s", anime_id, type(error).__name__)
        temporary = output / "data.tmp"
        temporary.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        temporary.replace(output / "data.json")
        return data
    finally:
        snapshot.close()


def main():
    parser = argparse.ArgumentParser(description="导出 GitHub Pages 只读网站")
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--output", default="dist/pages")
    parser.add_argument("--scan", action="store_true", help="导出前扫描；只用于未运行常驻服务的环境")
    parser.add_argument("--no-covers", action="store_true")
    args = parser.parse_args()

    async def build():
        config = load_config(args.config)
        store = Store(Path(config.data_dir) / "finder.sqlite")
        monitor = Monitor(config, store)
        try:
            if args.scan:
                store.reclassify(monitor.rules)
                await monitor.scan()
            data = await export_site(monitor, args.output, fetch_covers=not args.no_covers)
            print(
                json.dumps(
                    {
                        "output": str(Path(args.output).resolve()),
                        "anime": len(data["anime"]),
                        "generated_at": data["generated_at"],
                    }
                )
            )
        finally:
            await monitor.close()
            store.close()

    asyncio.run(build())


if __name__ == "__main__":
    main()
