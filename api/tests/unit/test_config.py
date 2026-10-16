# -*- coding: utf-8 -*-
import pytest

from api.app.config import ConfigError, Settings


def test_live_without_key_fails_closed(live_settings):
    with pytest.raises(ConfigError, match="BAIDU_MAP_AK"):
        live_settings.Settings.from_env()


def test_live_settings_ignore_unrelated_env(live_settings):
    live_settings.os.environ["BAIDU_MAP_AK"] = "test-ak"
    settings = live_settings.Settings.from_env()
    assert settings.baidu_ak == "test-ak"


def test_timeout_must_be_positive(monkeypatch, tmp_path):
    from api.app import config

    monkeypatch.setattr(config, "_ENV_FILE", tmp_path / "missing.env")
    monkeypatch.setenv("BAIDU_MAP_AK", "test-ak")
    monkeypatch.setenv("BAIDU_TIMEOUT_S", "0")
    with pytest.raises(ConfigError, match="大于 0"):
        Settings.from_env(env_file=tmp_path / "missing.env")


def test_live_requires_ak_not_just_sk(live_settings):
    live_settings.os.environ["BAIDU_MAP_SK"] = "only-sk"
    live_settings.os.environ.pop("BAIDU_MAP_AK", None)
    with __import__("pytest").raises(ConfigError, match="BAIDU_MAP_AK"):
        live_settings.Settings.from_env()


def test_only_ak_counts_as_configured(monkeypatch, tmp_path):
    from api.app.config import Settings

    monkeypatch.setenv("BAIDU_MAP_AK", "ak-only")
    monkeypatch.delenv("BAIDU_MAP_SK", raising=False)
    settings = Settings.from_env(env_file=tmp_path / "missing.env")
    assert settings.baidu_configured is True


def test_only_sk_does_not_count_as_configured(monkeypatch, tmp_path):
    # F40 回归：只有 SK 时 from_env 直接拒绝，不会产生“已配置但 AK 为空”的 Settings。
    from api.app.config import Settings

    monkeypatch.delenv("BAIDU_MAP_AK", raising=False)
    monkeypatch.setenv("BAIDU_MAP_SK", "sk-only")
    with __import__("pytest").raises(ConfigError, match="BAIDU_MAP_AK"):
        Settings.from_env(env_file=tmp_path / "missing.env")
    from api.app.adapters.baidu.client import BaiduAdapter

    assert BaiduAdapter(sign_key="sk-only").configured is False
    assert BaiduAdapter(app_key="ak-only").configured is True
