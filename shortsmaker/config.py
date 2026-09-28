"""설정 파일(config.yaml) 로딩.

환경변수로도 토큰을 넣을 수 있다 (예: INSTAGRAM_ACCESS_TOKEN).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = Path("config.yaml")

# (섹션, 키) -> 환경변수 이름
ENV_OVERRIDES = {
    ("youtube", "client_secrets_file"): "YOUTUBE_CLIENT_SECRETS",
    ("youtube", "token_file"): "YOUTUBE_TOKEN_FILE",
    ("instagram", "access_token"): "INSTAGRAM_ACCESS_TOKEN",
    ("instagram", "user_id"): "INSTAGRAM_USER_ID",
    ("threads", "access_token"): "THREADS_ACCESS_TOKEN",
    ("threads", "user_id"): "THREADS_USER_ID",
    ("tiktok", "access_token"): "TIKTOK_ACCESS_TOKEN",
    ("general", "public_base_url"): "PUBLIC_BASE_URL",
}


def load_dotenv(path: str | os.PathLike = ".env") -> None:
    """.env 파일의 KEY=VALUE 를 환경변수로 (이미 설정된 값은 유지)."""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        if v.strip() and k.strip() not in os.environ:
            os.environ[k.strip()] = v.strip().strip('"').strip("'")


def load_config(path: str | os.PathLike | None = None) -> dict[str, Any]:
    load_dotenv()
    cfg_path = Path(path) if path else Path(os.environ.get("SHORTSMAKER_CONFIG", DEFAULT_CONFIG_PATH))
    cfg: dict[str, Any] = {}
    if cfg_path.exists():
        with open(cfg_path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    for (section, key), env in ENV_OVERRIDES.items():
        value = os.environ.get(env)
        if value:
            cfg.setdefault(section, {})[key] = value
    return cfg
