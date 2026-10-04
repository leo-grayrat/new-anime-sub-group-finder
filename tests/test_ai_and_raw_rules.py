import pytest

from fansub_finder.adapters import parse_release_description
from fansub_finder.models import Anime, Release
from fansub_finder.rules import Rules
from fansub_finder.store import Store


def release(**kwargs):
    values = dict(
        source="mikan",
        source_id="1",
        group="北宇治字幕组",
        title="[北宇治字幕组] FX战士久留美 [01][WebRip][HEVC_AAC][简日内嵌]",
        languages=["CHS", "JP"],
        subtitle="EMBEDDED",
    )
    return Release(**(values | kwargs))


@pytest.mark.parametrize(
    "source,selector", [("mikan", "episode-desc"), ("anibt", "prose"), ("garden", "topic-nfo")]
)
def test_recruiting_raw_translation_skills_is_not_an_unsubtitled_release(source, selector):
    r = release(source=source)
    parse_release_description(
        f'<div class="{selector}">本组字幕作品基于 CC BY-NC-ND 4.0 协议进行共享。'
        "北宇治字幕组*招募\n翻译\n| 日语参考等级n2以上或能够听懂生肉内容并保证正确率，有经验者优先"
        "\n美工\n| 熟练使用PS/AI等软件，能进行图片设计</div>",
        source,
        r,
    )
    assert Rules().check(r) == []


@pytest.mark.parametrize("label", ["AI翻译简中", "AI翻譯繁中", "ai 翻译", "AI-Translated"])
def test_ai_translation_title_is_blocked_without_a_platform_tag(label):
    r = release(title=f"[测试组] 测试番 - 01 [1080p WEB-DL][{label}]")
    assert Rules(groups=[], platforms=[]).check(r) == ["明确标注AI翻译"]


def test_ai_translation_tag_and_credit_are_blocked_but_design_tools_are_not():
    assert "明确标注AI翻译" in Rules().check(release(tags=["AI翻译简中"]))
    assert "明确标注AI翻译" in Rules().check(release(description="翻译：AI翻译\n压制：测试组"))
    assert Rules().check(release(description="美工招募：熟练使用PS/AI。\n禁止使用AI翻译。")) == []
    assert Rules().check(release(title="[测试组] AI no Utagoe - 01 [CHS]")) == []


@pytest.mark.parametrize(
    "update", [{"subtitle": "NONE"}, {"title": "[测试组] 测试番 - 01 [生肉]"}, {"tags": ["NO_SUBS"]}]
)
def test_explicit_unsubtitled_releases_remain_blocked(update):
    assert "明确无字幕" in Rules().check(release(**update))


def test_reclassification_restores_all_origins_without_new_group_notification(tmp_path):
    class OldRules:
        def check(self, r):
            return ["明确无字幕"]

    store = Store(tmp_path / "test.sqlite")
    try:
        store.upsert_anime(Anime(id="bgm:1", title="FX战士久留美", premiere="2026-10-01"))
        for source in ["mikan", "garden", "anibt"]:
            for index, language in enumerate(["CHS", "CHT"]):
                store.ingest(
                    release(
                        source=source,
                        source_id=str(index),
                        anime_id="bgm:1",
                        magnet="magnet:?xt=urn:btih:" + str(index) * 40,
                        languages=[language, "JP"],
                        description="招募：能够听懂生肉内容",
                    ),
                    OldRules(),
                    baseline=True,
                )
        before = [tuple(r) for r in store.db.execute("SELECT source,source_id,first_seen FROM origins")]
        assert len(store.releases(blocked=True)) == 2
        store.reclassify(Rules())
        assert not store.releases(blocked=True)
        assert len(store.releases("bgm:1")) == 2
        assert all(len(r["origins"]) == 3 for r in store.releases("bgm:1"))
        assert store.groups("bgm:1")[0]["name"] == "北宇治字幕组"
        assert before == [
            tuple(r) for r in store.db.execute("SELECT source,source_id,first_seen FROM origins")
        ]
        assert not store.changes()
    finally:
        store.close()
