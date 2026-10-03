import json
from pathlib import Path

from fansub_finder.adapters import (
    parse_anibt_catalog,
    parse_anibt_groups,
    parse_feed,
    parse_garden_catalog,
    parse_garden_resources,
    parse_mikan_catalog,
    parse_mikan_detail,
)

FIXTURES = Path(__file__).parent / "fixtures"


def read(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_live_mikan_shapes():
    catalog = parse_mikan_catalog(read("mikan-season.html"), "2026-10", "https://mikanani.me")
    assert len(catalog) > 5
    a, releases = parse_mikan_detail(read("mikan-detail.html"), catalog[0], "https://mikanani.me")
    assert a.title
    assert all(r.source == "mikan" and r.group and r.source_id for r in releases)
    assert releases and releases[0].published_at
    assert parse_feed(read("mikan-rss.xml"), "mikan")


def test_garden_missing_fansub_falls_back_to_signature():
    data = {
        "resources": [
            {
                "id": 1,
                "title": "[新字幕组] 测试番 [01][WEB-DL]",
                "publisher": {"name": "搬运账号"},
                "href": "https://example.com/1",
            }
        ]
    }
    resources = parse_garden_resources(data, "bgm:123")
    assert resources[0].group == "新字幕组"
    assert resources[0].publisher == "搬运账号"


def test_live_garden_and_anibt_shapes():
    assert len(parse_garden_catalog(json.loads(read("garden-subjects.json")))) > 5
    garden = parse_garden_resources(json.loads(read("garden-resources.json")))
    assert len(garden) == 5
    assert garden[0].source_id
    anime = parse_anibt_catalog(json.loads(read("anibt-season.json")), "2026-10")
    assert len(anime) > 5
    groups = parse_anibt_groups(json.loads(read("anibt-groups.json")))
    assert groups and groups[0].anime_id.startswith("bgm:")
    assert parse_feed(read("anibt-rss.xml"), "anibt")


def test_anibt_feed_infohash_supports_cross_site_dedup():
    r = parse_feed(read("anibt-rss.xml"), "anibt")[0]
    assert r.magnet.startswith("magnet:?xt=urn:btih:")


def test_empty_challenge_page_is_not_empty_catalog():
    import pytest

    with pytest.raises(ValueError):
        parse_mikan_catalog("<html>Access denied</html>", "2026-10", "https://mikanani.me")
