# -*- coding: utf-8 -*-
"""服务端配置与 live 模式边界。

原则（纯 live，无 replay 切换）:
- 服务端必须从环境获得百度 AK/SK,浏览器永远拿不到;
- 缺密钥在启动/首次请求时明确报错,不静默降级。
"""
from __future__ import annotations

import os
import math
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[2]
_ENV_FILE = ROOT / ".env"


class ConfigError(RuntimeError):
    """配置不满足模式要求。"""


def load_env_file(path: Path = _ENV_FILE) -> None:
    """加载根目录 .env,已有环境变量优先;不打印任何值。"""
    if not path.exists():
        return
    with path.open(encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


@dataclass(frozen=True)
class Settings:
    baidu_ak: str = field(repr=False)
    baidu_sk: str = field(repr=False)
    ledger_db: str
    cache_db: str
    request_timeout_s: float
    derived_db: str = ""
    data_dir: str = str(ROOT / "demo-data" / "v1")
    # 浏览器端 AK（百度 JSAPI 底图专用）：经 /api/maps/config 下发，可公开；
    # 与 Server AK/SK 分离，绝不互换。
    maps_browser_ak: str = field(repr=False, default="")

    @property
    def baidu_configured(self) -> bool:
        # F40：百度请求必须带 AK；SK 只是可选签名密钥，不能单独视为已配置。
        return bool(self.baidu_ak.strip())
    @classmethod
    def from_env(cls, env_file: Optional[Path] = None) -> "Settings":
        env_path = _ENV_FILE if env_file is None else env_file
        load_env_file(env_path)
        if os.environ.get('BAIDU_HTTP_TRANSPORT', 'system') not in ('system', 'direct'):
            raise ConfigError('BAIDU_HTTP_TRANSPORT 必须为 system 或 direct')
        ak = os.environ.get("BAIDU_MAP_AK", "").strip()
        sk = os.environ.get("BAIDU_MAP_SK", "").strip()
        # 浏览器端 AK 独立变量；缺失仅影响底图加载，不阻塞服务端启动。
        maps_browser_ak = os.environ.get("VITE_BAIDU_MAP_AK_BROWSER", "").strip()
        if not ak:
            raise ConfigError(
                "服务端未配置 BAIDU_MAP_AK（SK 只是可选签名密钥，不能替代 AK）")

        ledger_db = os.environ.get("LEDGER_DB") or str(ROOT / "api" / "var" / "ledger.db")
        cache_db = os.environ.get("CACHE_DB") or str(ROOT / "api" / "var" / "cache.db")
        derived_db = os.environ.get("DERIVED_DB") or str(ROOT / "api" / "var" / "derived.db")
        data_dir = os.environ.get("DATA_DIR") or str(ROOT / "demo-data" / "v1")
        try:
            timeout = float(os.environ.get("BAIDU_TIMEOUT_S", "10"))
        except ValueError as exc:
            raise ConfigError("BAIDU_TIMEOUT_S 必须是数字") from exc
        if not math.isfinite(timeout) or timeout <= 0:
            raise ConfigError("BAIDU_TIMEOUT_S 必须大于 0")

        return cls(
            baidu_ak=ak,
            baidu_sk=sk,
            ledger_db=ledger_db,
            cache_db=cache_db,
            request_timeout_s=timeout,
            derived_db=derived_db,
            data_dir=data_dir,
            maps_browser_ak=maps_browser_ak,
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.from_env()
