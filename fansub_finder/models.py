from pydantic import BaseModel, Field, field_validator

from .covers import original_cover_url


class Anime(BaseModel):
    id: str
    title: str
    bgm_id: int | None = None
    cover_url: str = ""
    aliases: list[str] = Field(default_factory=list)
    premiere: str | None = None
    end_date: str | None = None
    episode_dates: list[str] = Field(default_factory=list)
    schedule_checked_at: str | None = None
    on_air: bool = False
    season_hint: str | None = None
    total_episodes: int | None = None
    sources: dict[str, str] = Field(default_factory=dict)
    evidence: list[str] = Field(default_factory=list)
    override: str | None = None

    @field_validator("cover_url")
    @classmethod
    def direct_cover_url(cls, value):
        return original_cover_url(value)


class Release(BaseModel):
    source: str
    source_id: str
    title: str
    anime_id: str | None = None
    group: str = ""
    publisher: str = ""
    url: str = ""
    magnet: str = ""
    torrent: str = ""
    rss: str = ""
    published_at: str = ""
    episode_key: str = ""
    languages: list[str] = Field(default_factory=list)
    resolution: str = ""
    subtitle: str = ""
    tags: list[str] = Field(default_factory=list)
    site_groups: list[str] = Field(default_factory=list)
    description: str = ""
    description_url: str = ""
    description_checked_at: str | None = None
    raw: dict = Field(default_factory=dict)
