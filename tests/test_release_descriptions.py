from fansub_finder.adapters import parse_release_description
from fansub_finder.models import Release
from fansub_finder.rules import Rules


def release(**kwargs):
    return Release(source="anibt", source_id="r", title="[测试组] 测试 - 01", group="测试组", **kwargs)


def test_blacklist_aliases_and_user_flagged_groups():
    for group in ["沸班亚马制作组", "沸班亞馬製作組", "Feibanyama", "Skymoon-Raws", "YAYOI"]:
        assert Rules().check(release().model_copy(update={"group": group}))
    assert not Rules().check(release().model_copy(update={"group": "ANimation"}))


def test_foreign_only_resources_do_not_ban_chinese_releases_from_same_publisher():
    assert Rules().check(release(publisher="geckyzz", languages=["EN", "ID", "JA"]))
    assert not Rules().check(release(publisher="geckyzz", languages=["CHT", "EN"]))
    assert not Rules().check(release(languages=[]))


def test_detail_only_platform_tag_is_blocked_and_sidebars_are_ignored():
    r = release()
    parse_release_description(
        '<nav>CR 官字 无字幕</nav><div class="episode-desc">字幕来源：巴哈姆特</div>', "mikan", r
    )
    assert Rules().check(r)
    safe = release()
    parse_release_description(
        '<aside>CR 官字</aside><div class="episode-desc">本组翻译制作</div>', "mikan", safe
    )
    assert not Rules().check(safe)


def test_subtitle_track_language_is_separate_from_audio():
    r = release()
    parse_release_description(
        '<div class="prose">Audio track: Chinese\nSubtitles:\nEnglish (ASS)\nIndonesian (ASS)\nJapanese (ASS)\nChapters: yes</div>',
        "anibt",
        r,
    )
    assert set(r.languages) == {"EN", "ID", "JA"}
    assert Rules().check(r)


def test_multisub_is_not_itself_a_blacklist_rule():
    r = release()
    parse_release_description(
        '<div class="topic-nfo">Subtitles (3): English, SRT | Chinese (Simplified), SRT | Chinese (Traditional), SRT\nChapters: Yes</div>',
        "garden",
        r,
    )
    assert {"CHS", "CHT"} <= set(r.languages)
    assert not Rules().check(r)
