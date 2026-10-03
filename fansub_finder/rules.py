import base64
import re
import unicodedata
from datetime import date
from urllib.parse import parse_qs, urlsplit

from .models import Anime, Release

DEFAULT_GROUPS = ["ANi", "黒ネズミたち", "Kirara Fantasia", "Nix-Raws", "ToonsHub", "Ansgwrt", "沸班亚马"]
DEFAULT_PLATFORMS = ["CR", "Crunchyroll", "Baha", "Bahamut", "巴哈", "巴哈姆特", "CATCHPLAY", "CATCHPLAY+"]
GROUP_ALIASES = {
    "nix-raw": "nix-raws",
    "nix raws": "nix-raws",
    "nixraws": "nix-raws",
    "nixraw": "nix-raws",
    "kirara-fantasia": "kirara fantasia",
    "kitaujisub": "北宇治字幕组",
    "kitauji sub": "北宇治字幕组",
}


def group_key(text: str) -> str:
    key = unicodedata.normalize("NFKC", text).strip(" []【】").casefold()
    key = re.sub(r"\s+", " ", key)
    return GROUP_ALIASES.get(key, key)


def title_group(title: str) -> str:
    for value in re.findall(r"[\[【]([^\]】]+)[\]】]", title)[:2]:
        if not re.fullmatch(r"[\d.\-\s]+|\d{3,4}p|(?:web|bd|tv).*", value, re.I):
            return value.strip()
    return ""


def normalize_infohash(magnet: str) -> str | None:
    try:
        for xt in parse_qs(urlsplit(magnet).query).get("xt", []):
            if xt.lower().startswith("urn:btih:"):
                value = xt[9:]
                if re.fullmatch(r"[0-9a-fA-F]{40}", value):
                    return value.lower()
                if re.fullmatch(r"[A-Z2-7a-z]{32}", value):
                    return base64.b32decode(value.upper()).hex()
    except (ValueError, TypeError):
        pass
    return None


def episodes(title: str, explicit: str = "") -> list[str]:
    match = None
    if explicit:
        match = re.fullmatch(r"(\d{1,4}(?:\.\d+)?)(?:\s*[-~–]\s*(\d{1,4}))?(?:v\d+)?", explicit.strip(), re.I)
    if not match:
        for pat in [
            r"S\d{1,2}E(\d{1,4})(?:v\d+)?",
            r"[\[【]\s*(\d{1,3}(?:\.\d+)?)\s*(?:[-~–]\s*(\d{1,3}))?(?:v\d+)?(?:\s*(?:END|完))?\s*[\]】]",
            r"\s-\s*(\d{1,3}(?:\.\d+)?)(?:\s*[-~]\s*(\d{1,3}))?(?:v\d+)?(?=\s|[\[.(]|$)",
            r"第\s*(\d{1,3})\s*[话話集]",
        ]:
            match = re.search(pat, title, re.I)
            if match:
                break
    if not match:
        return []
    first = match.group(1)
    if match.lastindex and match.lastindex >= 2 and match.group(2):
        start, end = int(first), int(match.group(2))
        if 0 <= end - start <= 2000:
            return [str(i) for i in range(start, end + 1)]
        return []
    return [str(float(first)).rstrip("0").rstrip(".") if "." in first else str(int(first))]


def quarter_bounds(season: str) -> tuple[str, str]:
    if not re.fullmatch(r"\d{4}-(01|04|07|10)", season):
        raise ValueError("季度格式应为 YYYY-01、YYYY-04、YYYY-07 或 YYYY-10")
    year, month = map(int, season.split("-"))
    return date(year, month, 1).isoformat(), date(
        year + (month == 10), month + 3 if month < 10 else 1, 1
    ).isoformat()


def scope_for(anime: Anime, season: str) -> str:
    if anime.override:
        return anime.override
    start, end = quarter_bounds(season)
    if anime.premiere and start <= anime.premiere[:10] < end:
        return "current"
    if not anime.premiere and anime.season_hint == season:
        return "current"
    if anime.premiere and anime.premiere[:10] >= end:
        return "excluded"
    if anime.end_date and anime.end_date[:10] < start:
        return "excluded"
    in_quarter = [d for d in anime.episode_dates if start <= d[:10] < end]
    if len(in_quarter) >= 3:
        return "continuing"
    if in_quarter and anime.end_date and anime.end_date < end:
        return "excluded"  # one or two remaining scheduled episodes are quarter-tail noise
    if anime.on_air and season == current_quarter():
        return "continuing"
    return "uncertain"


def current_quarter() -> str:
    from datetime import datetime, timedelta, timezone

    today = datetime.now(timezone(timedelta(hours=8)))
    return f"{today.year}-{((today.month - 1) // 3) * 3 + 1:02}"


class Rules:
    def __init__(self, groups=None, platforms=None):
        self.groups = DEFAULT_GROUPS if groups is None else groups
        self.platforms = DEFAULT_PLATFORMS if platforms is None else platforms

    def check(self, r: Release) -> list[str]:
        reasons = []
        labels = [r.group, r.publisher, title_group(r.title)]
        labels += [p.strip() for label in list(labels) for p in re.split(r"[&＆+×]|\s+[xX]\s+", label)]
        for banned in self.groups:
            if group_key(banned) in {group_key(x) for x in labels if x}:
                reasons.append(f"发布组黑名单：{banned}")
        text = " ".join([r.title, *r.tags])
        for tag in self.platforms:
            # ASCII token boundaries protect Crimson/Anima and accept CR_WEB-DL.
            pat = r"(?<![A-Za-z0-9])" + re.escape(tag) + r"(?![A-Za-z0-9])"
            if re.search(pat, text, re.I):
                reasons.append(f"平台标签：{tag}")
        if re.search(r"官方字幕|官方中字|官字|official\s+(?:subtitles?|subs)\b", text, re.I):
            reasons.append("明确标注官方字幕")
        if r.subtitle.upper() == "NONE" or re.search(r"无字幕|無字幕|生肉|\bNO[ ._-]?SUBS?\b", text, re.I):
            reasons.append("明确无字幕")
        return reasons
