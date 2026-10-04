"""Cover URL helpers. Images are loaded by the browser, never downloaded here."""

import re
from urllib.parse import urlsplit, urlunsplit


def original_cover_url(value):
    try:
        url = urlsplit(value)
        if url.scheme != "https" or url.netloc not in ["lain.bgm.tv", "r2.anibt.net"]:
            return ""
        path = url.path
        if url.hostname == "lain.bgm.tv":
            path = re.sub(r"^/r/\d+(?:x\d+)?(?=/pic/cover/)", "", path)
        return urlunsplit((url.scheme, url.netloc, path, url.query, ""))
    except ValueError:
        return ""


def subject_cover_url(images):
    return original_cover_url(images.get("large") or images.get("common") or images.get("medium") or "")
