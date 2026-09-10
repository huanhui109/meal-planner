"""多样性校验单元测试"""
from __future__ import annotations

from app.services.diversity_service import DiversityService

service = DiversityService()


def test_no_history_always_passes():
    report = service.validate(["宫保鸡丁", "番茄炒蛋"], [])
    assert report.passed is True
    assert report.score == 1.0


def test_identical_menu_is_flagged():
    names = ["宫保鸡丁", "番茄炒蛋", "清蒸鱼"]
    report = service.validate(names, names)
    assert report.passed is False
    assert report.score == 0.0
    assert len(report.overlaps) == 3


def test_partial_overlap_lowers_score():
    report = service.validate(["A", "B", "C", "D"], ["A", "B", "X", "Y"])
    # 交集 2, 并集 6 -> 1 - 2/6
    assert report.score == 0.6667
    assert report.passed is False


def test_completely_new_menu_scores_one():
    report = service.validate(["A", "B"], ["C", "D"])
    assert report.score == 1.0
    assert report.passed is True


def test_blank_names_are_ignored():
    report = service.validate(["A", "", "  "], [])
    assert report.score == 1.0


def test_pick_better_prefers_passing_report():
    bad = service.validate(["A", "B"], ["A", "B"])
    good = service.validate(["C", "D"], ["A", "B"])
    assert service.pick_better(bad, good) is good
    assert service.pick_better(good, bad) is good
    assert service.pick_better(bad, None) is bad
