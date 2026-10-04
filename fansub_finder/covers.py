import asyncio
import hashlib
import time
from pathlib import Path
from urllib.parse import urlsplit


def image_type(data):
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:6] in [b"GIF87a", b"GIF89a"]:
        return "image/gif"
    return None


class Covers:
    def __init__(self, monitor):
        self.monitor = monitor
        self.directory = Path(monitor.config.data_dir) / "covers"
        self.locks = {}
        self.failed_at = {}

    async def get(self, anime_id):
        anime = self.monitor.store.anime(anime_id)
        if not anime:
            raise ValueError("番剧不存在")
        filename = self.directory / (hashlib.sha256(anime_id.encode()).hexdigest() + ".image")
        async with self.locks.setdefault(anime_id, asyncio.Lock()):
            if filename.exists():
                data = filename.read_bytes()
                if media_type := image_type(data):
                    return data, media_type
            if time.monotonic() - self.failed_at.get(anime_id, -60) < 60:
                raise ValueError("封面暂不可用")
            try:
                if not anime.cover_url and anime.bgm_id:
                    subject = await self.monitor.net.json(f"https://api.bgm.tv/v0/subjects/{anime.bgm_id}")
                    images = subject.get("images") or {}
                    anime.cover_url = images.get("common") or images.get("medium") or ""
                    if anime.cover_url:
                        self.monitor.store.upsert_anime(anime)
                url = urlsplit(anime.cover_url)
                if url.scheme != "https" or url.hostname not in ["lain.bgm.tv", "r2.anibt.net"]:
                    raise ValueError("暂无可用封面")
                response = await self.monitor.net.get(anime.cover_url)
                data = response.content
                media_type = image_type(data)
                if not media_type or len(data) > 4 * 1024 * 1024:
                    raise ValueError("封面响应不是有效图片")
                self.directory.mkdir(parents=True, exist_ok=True)
                temporary = filename.with_suffix(".tmp")
                temporary.write_bytes(data)
                temporary.replace(filename)
                self.failed_at.pop(anime_id, None)
                return data, media_type
            except Exception:
                self.failed_at[anime_id] = time.monotonic()
                raise
