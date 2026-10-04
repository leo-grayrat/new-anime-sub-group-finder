"""Public site contracts, independently implemented from observed responses."""

import re
from datetime import datetime, timezone
from urllib.parse import urlencode, urljoin

import feedparser
from bs4 import BeautifulSoup

from .models import Anime, Release
from .rules import title_group


def iso(value):
    if isinstance(value, (float, int)):
        return datetime.fromtimestamp(value / 1000 if value > 10**11 else value, timezone.utc).isoformat()
    if not value:
        return ""
    value = str(value).strip()
    if "," in value:
        from email.utils import parsedate_to_datetime

        try:
            return parsedate_to_datetime(value).astimezone(timezone.utc).isoformat()
        except (ValueError, TypeError):
            pass
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", value):
        return value + "+08:00"
    for fmt in ["%m/%d/%Y %H:%M", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y", "%Y/%m/%d %H:%M"]:
        try:
            return datetime.strptime(value, fmt).isoformat() + "+08:00"
        except ValueError:
            pass
    return value


def enrich(r):
    if not r.group:
        r.group = title_group(r.title) or r.publisher or "未署名"
    if not r.resolution:
        m = re.search(r"\b(\d{3,4}[pP])\b", r.title)
        r.resolution = m.group(1).lower() if m else ""
    for label, pattern in [("CHS", r"简|簡|\bCHS\b|\bSC\b"), ("CHT", r"繁|\bCHT\b|\bTC\b")]:
        if re.search(pattern, r.title, re.I) and label not in r.languages:
            r.languages.append(label)
    return r


def parse_release_description(html, source, r):
    soup = BeautifulSoup(html, "html.parser")
    selector = {"mikan": ".episode-desc", "anibt": ".prose", "garden": ".topic-nfo"}[source]
    body = soup.select_one(selector)
    if body is None:
        raise ValueError(f"{source} 详情页缺少发布说明，不能视为已核实")
    for tag in body.select("script,style"):
        tag.decompose()
    r.description = body.get_text("\n", strip=True)[:50000]
    # Only inspect the subtitle track block; Chinese audio and credits are not subtitle evidence.
    match = re.search(
        r"(?:subtitles?(?:\s*\(\d+\))?|字幕(?:语言|語言|轨道|軌道)?)\s*[:：\n](.*?)(?=\n(?:chapters?|duration|checksums?|audio|video|notes?|comments?|credits?|source|音频|视频|音軌|章節|备注|備註|说明|說明)(?:\b|[:：])|$)",
        r.description,
        re.I | re.S,
    )
    if match:
        block = re.sub(
            r"\b(?:no|without|not(?:\s+available)?|none(?:\s+in)?)\s+[^,;\n|│]*|(?:无|無|没有|沒有|不含)[^，,；;\n|│]*",
            "",
            match.group(1),
            flags=re.I,
        )
        patterns = {
            "CHS": r"Chinese\s*\(Simplified\)|简体|簡體|\bCHS\b|zh[-_]Hans",
            "CHT": r"Chinese\s*\(Traditional\)|繁体|繁體|\bCHT\b|zh[-_]Hant",
            "ZH": r"中文|\bChinese\b",
            "EN": r"\bEnglish\b|英语|英語",
            "ID": r"\bIndonesian\b|印尼",
            "JA": r"\bJapanese\b|日语|日語",
            "KO": r"\bKorean\b|韩语|韓語",
            "FR": r"\bFrench\b",
        }
        found = [lang for lang, pattern in patterns.items() if re.search(pattern, block, re.I)]
        if found:
            r.languages = sorted(set(r.languages + found))
    r.description_url = r.url
    from .store import now

    r.description_checked_at = now()
    return r


def parse_mikan_catalog(html, season, host):
    soup = BeautifulSoup(html, "html.parser")
    result = {}
    for a in soup.select('a[href^="/Home/Bangumi/"]'):
        source_id = re.search(r"/Home/Bangumi/(\d+)", a["href"]).group(1)
        title = a.get_text(" ", strip=True)
        if title:
            result[source_id] = Anime(
                id=f"mikan:{source_id}",
                title=title,
                aliases=[title],
                sources={"mikan": source_id},
                season_hint=season,
                evidence=[f"蜜柑 {season} 放送列表"],
            )
    if not result:
        raise ValueError("蜜柑番剧列表结构缺失或被拦截，不能视为空列表")
    return list(result.values())


def parse_mikan_detail(html, anime, host):
    soup = BeautifulSoup(html, "html.parser")
    title = soup.select_one(".bangumi-title")
    if not title:
        raise ValueError("蜜柑详情页缺少番剧标题")
    anime = anime.model_copy(deep=True)
    anime.title = title.get_text(" ", strip=True)
    anime.aliases = list(set(anime.aliases + [anime.title]))
    for a in soup.select('a[href*="/subject/"]'):
        match = re.search(r"(?:bgm\.tv|bangumi\.tv|chii\.in)/subject/(\d+)", a.get("href", ""))
        if match:
            anime.bgm_id = int(match.group(1))
            anime.id = f"bgm:{anime.bgm_id}"
            break
    for p in soup.select(".bangumi-info"):
        text = p.get_text(" ", strip=True)
        if "放送开始" in text or "放送開始" in text:
            value = re.search(r"\d{1,2}/\d{1,2}/\d{4}|\d{4}-\d{2}-\d{2}", text)
            if value:
                anime.premiere = iso(value.group(0))[:10]
    result = []
    for label in soup.select("a.subgroup-name[data-anchor]"):
        anchor = soup.find(id=label["data-anchor"].lstrip("#"))
        if not anchor:
            raise ValueError("蜜柑发布组锚点结构变化")
        table = anchor.find_next("table")
        rss = anchor.select_one("a.mikan-rss")
        if table is None:
            continue
        for row in table.select("tbody tr"):
            link = row.select_one('a[href*="/Home/Episode/"]')
            if not link:
                continue
            magnet = row.select_one("[data-clipboard-text]") or row.select_one("[data-magnet]")
            torrent = row.select_one('a[href*=".torrent"]')
            cells = row.select("td")
            r = Release(
                source="mikan",
                source_id=link["href"].rstrip("/").split("/")[-1],
                title=link.get_text(" ", strip=True),
                anime_id=anime.id,
                group=title_group(link.get_text()) or label.get_text(strip=True),
                publisher=label.get_text(strip=True),
                url=urljoin(host, link["href"]),
                magnet=magnet.get("data-clipboard-text", magnet.get("data-magnet", "")) if magnet else "",
                torrent=urljoin(host, torrent["href"]) if torrent else "",
                rss=urljoin(host, rss["href"]) if rss else "",
                published_at=iso(
                    next(
                        (
                            c.get_text(strip=True)
                            for c in cells
                            if re.search(r"\d{4}/\d{2}/\d{2} \d{2}:\d{2}", c.get_text(strip=True))
                        ),
                        "",
                    )
                ),
                raw={"row_text": row.get_text(" ", strip=True), "site_group": label.get_text(strip=True)},
            )
            result.append(enrich(r))
    return anime, result


def parse_garden_catalog(data):
    if data.get("status") != "OK" or "subjects" not in data:
        raise ValueError("AnimeGarden 番剧目录返回异常")
    return [
        Anime(
            id=f"bgm:{s['id']}",
            bgm_id=int(s["id"]),
            title=s["name"],
            aliases=list(set([s["name"], *s.get("search", {}).get("include", [])])),
            premiere=s.get("activedAt", "")[:10] or None,
            sources={"garden": str(s["id"])},
            evidence=["AnimeGarden 目录 activedAt，待 Bangumi 校验"],
        )
        for s in data["subjects"]
    ]


def parse_garden_resources(data, anime_id=None):
    if "resources" not in data or data.get("status", "OK") != "OK":
        raise ValueError("AnimeGarden 资源返回异常")
    result = []
    for item in data["resources"]:
        if item.get("type", "动画") != "动画":
            continue
        fansub = item.get("fansub") or {}
        publisher = item.get("publisher") or {}
        bgm_id = item.get("subjectId")
        group = title_group(item["title"]) or fansub.get("name", "")
        r = Release(
            source="garden",
            source_id=str(item["id"]),
            title=item["title"],
            anime_id=anime_id or (f"bgm:{bgm_id}" if bgm_id else None),
            group=group,
            publisher=publisher.get("name", ""),
            magnet=item.get("magnet") or "",
            url=item.get("href") or "",
            published_at=iso(item.get("createdAt")),
            raw=item,
            rss="https://api.animes.garden/feed.xml?"
            + urlencode(
                {"subject": bgm_id or (anime_id or "").removeprefix("bgm:"), "fansub": fansub["name"]}
            )
            if fansub.get("name") and (bgm_id or anime_id)
            else "",
        )
        result.append(enrich(r))
    return result


def parse_anibt_catalog(data, season):
    if not data.get("ok") or "byWeekday" not in data.get("data", {}):
        raise ValueError("AniBT 季度目录返回异常")
    return [
        Anime(
            id=f"bgm:{a['bgmId']}",
            bgm_id=int(a["bgmId"]),
            title=a["title"].get("chinese") or a["title"]["primary"],
            aliases=list(set(v for v in a["title"].values() if isinstance(v, str) and v)),
            premiere=a.get("premiereDate"),
            season_hint=season,
            total_episodes=a.get("episodes"),
            sources={"anibt": str(a["bgmId"])},
            evidence=[f"AniBT {season} 季度目录"],
        )
        for weekday in data["data"]["byWeekday"]
        for a in weekday["animes"]
        if a.get("format", "TV") in ["TV", "ONA", "WEB", "TV_SHORT"]
    ]


def parse_anibt_groups(data):
    if not data.get("ok") or "groups" not in data.get("data", {}):
        raise ValueError("AniBT 发布组返回异常")
    result = []
    bgm_id = data["data"]["bgmId"]
    for g in data["data"]["groups"]:
        for item in g.get("items", []):
            r = Release(
                source="anibt",
                source_id=item["releaseId"],
                title=item["title"],
                anime_id=f"bgm:{bgm_id}",
                group=title_group(item["title"]) or g["name"],
                publisher=g["name"],
                url=f"https://anibt.net/release/{item['releaseId']}",
                magnet=item.get("magnet") or "",
                torrent=f"https://anibt.net/api/torrent/{item['releaseId']}.torrent",
                rss="https://anibt.net/rss/anime.xml?" + urlencode({"bgmId": bgm_id, "groupSlug": g["slug"]}),
                published_at=iso(item.get("publishedAt")),
                episode_key=item.get("episodeKey") or "",
                resolution=item.get("resolution") or "",
                languages=item.get("language") or [],
                subtitle=item.get("subtitle") or "",
                tags=item.get("customTags") or [],
                raw={"item": item, "group": g["name"]},
            )
            result.append(enrich(r))
    return result


def parse_feed(content, source, anime_id=None):
    feed = feedparser.parse(content)
    if feed.bozo and not feed.entries:
        raise ValueError(f"{source} RSS 解析失败")
    if not feed.entries and not feed.get("feed", {}).get("title"):
        raise ValueError(f"{source} 返回内容不是有效 RSS")
    result = []
    for entry in feed.entries:
        if source == "anibt" and entry.get("anibt_type", "anime") != "anime":
            continue
        url = entry.get("link", "")
        torrent = next(
            (
                e.get("href", "")
                for e in entry.get("enclosures", [])
                if e.get("type") == "application/x-bittorrent"
            ),
            "",
        )
        source_id = entry.get("anibt_releaseid") if source == "anibt" else url.rstrip("/").split("/")[-1]
        bgm_id = entry.get("anibt_bgmid")
        text = entry.get("summary", "")
        magnets = re.findall(r'magnet:\?[^\s<>"\']+', text)
        # feedparser stores some namespaced magnet fields as plain strings.
        magnet = (
            entry.get("magnet", "") or entry.get("torrent_magneturi", "") or (magnets[0] if magnets else "")
        )
        if not magnet and source == "mikan" and re.fullmatch(r"[0-9a-fA-F]{40}", source_id or ""):
            magnet = "magnet:?xt=urn:btih:" + source_id
        if not magnet and source == "anibt":
            raw_m = entry.get("anibt_magnet", "") or entry.get("anibt_magneturi", "")
            magnet = raw_m
            infohash = entry.get("infohash", "")
            if not magnet and re.fullmatch(r"[0-9a-fA-F]{40}", infohash):
                magnet = "magnet:?xt=urn:btih:" + infohash.lower()
        r = Release(
            source=source,
            source_id=source_id or entry.get("id", url),
            title=entry.get("title", ""),
            anime_id=anime_id or (f"bgm:{bgm_id}" if bgm_id else None),
            group=title_group(entry.get("title", "")) or entry.get("anibt_groupname", ""),
            publisher=entry.get("anibt_groupname", ""),
            url=url,
            torrent=torrent,
            magnet=magnet,
            episode_key=entry.get("anibt_episodekey", ""),
            published_at=iso(entry.get("published", "")),
            resolution=entry.get("anibt_resolution", ""),
            subtitle=entry.get("anibt_subtitle", ""),
            description=BeautifulSoup(text, "html.parser").get_text("\n", strip=True),
            raw={
                k: v
                for k, v in entry.items()
                if k not in ["summary_detail", "title_detail", "published_parsed"]
            },
        )
        result.append(enrich(r))
    return result
