import base64

from fansub_finder.models import Anime, Release
from fansub_finder.rules import Rules, episodes, normalize_infohash, scope_for
from fansub_finder.store import Store


def release(**kw):
    return Release(
        source="mikan",
        source_id="r1",
        title="[北宇治字幕组] 测试番 [01][WEB-DL][简繁内封]",
        group="北宇治字幕组",
        anime_id="bgm:123",
        **kw,
    )


def test_explicit_blocking_and_name_boundaries():
    rules = Rules()
    for label in ["ANi", "Nix-Raw", "nix-raws", "黒ネズミたち", "沸班亚马"]:
        assert rules.check(release(publisher=label))
    for tag in ["CR", "baha", "CATCHPLAY", "catchplay+", "官方字幕"]:
        r = release()
        r.title = f"[好组] 测试番 [01][{tag}]"
        assert rules.check(r)
    for title in [
        "[Anima] Crimson [01][WEB-DL][简体]",
        "[北宇治字幕组] 测试番 [01][WEB-DL]",
        "[好组] 测试番 [01][CHT]",
        "[好组] 测试番 [01][MultiSub]",
    ]:
        r = release()
        r.title = title
        assert rules.check(r) == []


def test_infohash_base32_and_hex_are_identical():
    hex_hash = "0123456789abcdef0123456789abcdef01234567"
    b32 = base64.b32encode(bytes.fromhex(hex_hash)).decode()
    assert normalize_infohash(f"magnet:?xt=urn:btih:{b32}") == hex_hash
    assert normalize_infohash(f"magnet:?xt=urn:btih:{hex_hash.upper()}") == hex_hash
    assert normalize_infohash("magnet:?xt=urn:btih:invalid") is None


def test_episode_ranges_and_versions():
    assert episodes("[好组] 测试番 [01-03][1080p]") == ["1", "2", "3"]
    assert episodes("[好组] 测试番 - 04v2 [WEB-DL]") == ["4"]
    assert episodes("[好组] 测试番 S02E05 [1080p]") == ["5"]
    assert episodes("[好组] 测试番 [1080p][2026]") == []


def test_airing_scope_ignores_upload_recency():
    assert scope_for(Anime(id="bgm:1", title="新番", premiere="2026-10-01"), "2026-10") == "current"
    assert (
        scope_for(
            Anime(
                id="bgm:2",
                title="续播",
                premiere="2026-07-01",
                episode_dates=["2026-10-05", "2026-10-12", "2026-10-19"],
            ),
            "2026-10",
        )
        == "continuing"
    )
    assert (
        scope_for(Anime(id="bgm:3", title="收尾", premiere="2026-07-01", end_date="2026-09-30"), "2026-10")
        == "excluded"
    )
    assert scope_for(Anime(id="bgm:4", title="资料不足", premiere="2026-07-01"), "2026-10") == "uncertain"


def test_store_baseline_dedup_changes_and_reclassification(tmp_path):
    store = Store(tmp_path / "test.sqlite")
    store.upsert_anime(Anime(id="bgm:123", title="测试番", premiere="2026-10-01"))
    a = release(magnet="magnet:?xt=urn:btih:" + "a" * 40)
    store.ingest(a, Rules(), baseline=True)
    store.ingest(a, Rules(), baseline=False)
    assert store.changes() == []
    b = a.model_copy(update={"source": "garden", "source_id": "r2"})
    store.ingest(b, Rules(), baseline=False)
    assert len(store.releases("bgm:123")) == 1
    assert len(store.releases("bgm:123")[0]["origins"]) == 2
    new = a.model_copy(
        update={"group": "新组", "source_id": "r3", "magnet": "magnet:?xt=urn:btih:" + "b" * 40}
    )
    store.ingest(new, Rules(), baseline=False)
    assert len(store.changes()) == 1
    ep2 = new.model_copy(
        update={"source_id": "r4", "title": "[新组] 测试番 [02]", "magnet": "magnet:?xt=urn:btih:" + "c" * 40}
    )
    store.ingest(ep2, Rules(), baseline=False)
    assert len(store.changes()) == 1
    store.reclassify(Rules(groups=["新组"]))
    assert all(r["group"] != "新组" for r in store.releases("bgm:123"))
    store.reclassify(Rules(groups=[]))
    assert len(store.changes()) == 1
    store.close()
    store = Store(tmp_path / "test.sqlite")
    store.ingest(ep2, Rules(), baseline=False)
    assert len(store.changes()) == 1


def test_sparse_feed_does_not_erase_publisher_or_rss(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    a = release(
        publisher="Kirara Fantasia", rss="https://example.com/feed", magnet="magnet:?xt=urn:btih:" + "d" * 40
    )
    store.ingest(a, Rules(), baseline=True)
    store.ingest(a.model_copy(update={"publisher": "", "rss": "", "magnet": ""}), Rules(), baseline=False)
    rows = store.releases(blocked=True)
    assert len(rows) == 1
    assert rows[0]["publisher"] == "Kirara Fantasia"
    assert rows[0]["rss"] == "https://example.com/feed"


def test_identical_torrent_combines_blocking_evidence_across_sources(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    a = release(magnet="magnet:?xt=urn:btih:" + "e" * 40)
    store.ingest(a.model_copy(update={"tags": ["CR"]}), Rules(), baseline=True)
    store.ingest(a.model_copy(update={"source": "garden"}), Rules(), baseline=True)
    assert store.releases() == []
    blocked = store.releases(blocked=True)
    assert len(blocked) == 1 and len(blocked[0]["origins"]) == 2


def test_sparse_feed_without_signature_keeps_existing_group(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    store.upsert_anime(Anime(id="bgm:123", title="测试", premiere="2026-10-01"))
    a = release(publisher="好组")
    a.title = "测试 - 01 1080p"
    a.group = "好组"
    store.ingest(a, Rules(), baseline=True)
    store.ingest(a.model_copy(update={"group": "未署名", "publisher": ""}), Rules(), baseline=False)
    assert store.groups("bgm:123")[0]["name"] == "好组"
    assert store.changes() == []


def test_site_fansub_and_additional_title_signature_cannot_bypass_blacklist():
    assert Rules().check(release(publisher="搬运", raw={"fansub": {"name": "ANi"}}))
    assert Rules().check(release().model_copy(update={"title": "[好组][ANi] 测试番 - 01"}))
