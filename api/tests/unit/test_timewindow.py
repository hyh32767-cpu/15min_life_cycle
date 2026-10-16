# -*- coding: utf-8 -*-
from datetime import datetime

import pytest

from core.timewindow import (OpeningWindow, format_scene_time, meets_deadline,
                             parse_time, schedule_in_window)

SCENE = datetime.fromisoformat("2026-09-21T00:00:00+08:00")


def test_parse_time_accepts_iso_and_scene_seconds():
    assert parse_time("2026-09-21T18:30:00+08:00", scene_start=SCENE) == 66600
    assert parse_time(1234, scene_start=SCENE) == 1234
    assert parse_time(datetime.fromisoformat("2026-09-21T00:00:30+08:00"),
                      scene_start=SCENE) == 30
    assert format_scene_time(66600, scene_start=SCENE).startswith("2026-09-21T18:30:00")


def test_schedule_waits_for_open_and_allows_exact_close():
    window = OpeningWindow(9 * 3600, 18 * 3600)
    early = schedule_in_window(8 * 3600, 600, window)
    assert early.feasible
    assert early.start_seconds == 9 * 3600
    assert early.wait_seconds == 3600
    exact = schedule_in_window(17 * 3600 + 50 * 60, 600, window)
    assert exact.feasible
    assert exact.finish_seconds == 18 * 3600


def test_schedule_rejects_service_past_close_or_after_close():
    window = OpeningWindow(9 * 3600, 18 * 3600)
    too_late = schedule_in_window(17 * 3600 + 55 * 60, 600, window)
    assert not too_late.feasible
    assert too_late.reason == "CLOSED"
    after_close = schedule_in_window(18 * 3600 + 1, 0, window)
    assert not after_close.feasible


def test_cross_midnight_window():
    window = OpeningWindow.from_datetimes(
        datetime.fromisoformat("2026-09-21T22:00:00+08:00"),
        datetime.fromisoformat("2026-09-22T02:00:00+08:00"),
        scene_start=SCENE,
    )
    assert window.crosses_midnight
    result = schedule_in_window(23 * 3600, 2 * 3600, window)
    assert result.feasible
    assert result.finish_seconds == 25 * 3600
    late = schedule_in_window(26 * 3600 + 1, 0, window)
    assert not late.feasible


def test_deadline_boundary_is_inclusive():
    assert meets_deadline(100, 100)
    assert not meets_deadline(101, 100)
    with pytest.raises(ValueError):
        schedule_in_window(0, -1, OpeningWindow(0, 86400))
