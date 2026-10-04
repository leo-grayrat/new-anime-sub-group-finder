import json
import os
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

from .rules import DEFAULT_GROUPS, DEFAULT_PLATFORMS, DEFAULT_REVIEW_GROUPS, quarter_bounds


class Config(BaseModel):
    season: str = "2026-10"
    proxy: str = "http://127.0.0.1:7897"
    poll_minutes: int = Field(default=10, ge=5, le=1440)
    catalog_hours: int = Field(default=6, ge=1, le=168)
    groups: list[str] = Field(default_factory=lambda: DEFAULT_GROUPS.copy())
    platforms: list[str] = Field(default_factory=lambda: DEFAULT_PLATFORMS.copy())
    review_groups: list[str] = Field(default_factory=lambda: DEFAULT_REVIEW_GROUPS.copy())
    mikan_host: str = "https://mikanani.me"
    data_dir: str = "data"

    @field_validator("season")
    @classmethod
    def validate_season(cls, value):
        quarter_bounds(value)
        return value

    @field_validator("proxy", "mikan_host")
    @classmethod
    def validate_url(cls, value):
        from urllib.parse import urlsplit

        if not value:
            return value
        u = urlsplit(value)
        if u.scheme not in ["http", "https"] or not u.hostname:
            raise ValueError("请填写完整的 HTTP/HTTPS 地址；代理留空表示直连")
        if u.username or u.password:
            raise ValueError("本版仅支持无需认证的本机代理")
        return value.rstrip("/")


def load_config(path="config.json"):
    values = json.loads(Path(path).read_text(encoding="utf-8")) if Path(path).exists() else {}
    if "FANSUB_PROXY" in os.environ:
        values["proxy"] = os.environ["FANSUB_PROXY"]
    if "FANSUB_DATA_DIR" in os.environ:
        values["data_dir"] = os.environ["FANSUB_DATA_DIR"]
    return Config(**values)


def save_config(config, path="config.json"):
    target = Path(path)
    temp = target.with_suffix(".tmp")
    temp.write_text(config.model_dump_json(indent=2), encoding="utf-8")
    temp.replace(target)
