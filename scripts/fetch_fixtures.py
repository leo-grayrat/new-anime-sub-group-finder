"""Refresh small public response fixtures through the explicitly configured proxy."""

import json
import sys
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

sys.stdout.reconfigure(encoding="utf-8")
dest = Path("tests/fixtures")
dest.mkdir(parents=True, exist_ok=True)
with httpx.Client(
    proxy="http://127.0.0.1:7897", trust_env=False, timeout=30, follow_redirects=True
) as client:

    def fetch(name, url):
        r = client.get(url)
        r.raise_for_status()
        (dest / name).write_text(r.text, encoding="utf-8")
        print(name, r.status_code, len(r.content))
        return r

    r = fetch(
        "mikan-season.html", "https://mikanani.me/Home/BangumiCoverFlowByDayOfWeek?year=2026&seasonStr=秋"
    )
    soup = BeautifulSoup(r.text, "html.parser")
    link = soup.select_one('a[href^="/Home/Bangumi/"]')
    fetch("mikan-detail.html", "https://mikanani.me" + link["href"])
    fetch("mikan-rss.xml", "https://mikanani.me/RSS/Classic")
    r = fetch("anibt-season.json", "https://anibt.net/api/seasons/anime?season=2026-FALL")
    animes = [a for w in r.json()["data"]["byWeekday"] for a in w["animes"]]
    released = next(a for a in animes if a.get("hasRelease"))
    fetch("anibt-groups.json", f"https://anibt.net/api/anime/groups?bgmId={released['bgmId']}")
    fetch("anibt-rss.xml", "https://anibt.net/rss/magnets.xml")
    r = fetch("garden-subjects.json", "https://api.animes.garden/subjects")
    fetch("garden-resources.json", "https://api.animes.garden/resources?pageSize=5")
    fetch("bgm-calendar.json", "https://api.bgm.tv/calendar")
    fetch("bgm-subject.json", f"https://api.bgm.tv/v0/subjects/{released['bgmId']}")
    fetch(
        "bgm-episodes.json", f"https://api.bgm.tv/v0/episodes?subject_id={released['bgmId']}&type=0&limit=100"
    )
    print("sample bgm", released["bgmId"], json.dumps(released["title"], ensure_ascii=False))
