"""预算校验单元测试"""
from __future__ import annotations

from app.services.budget_service import BudgetService

service = BudgetService()


def test_within_budget_passes():
    report = service.validate(300.0, 350.0)
    assert report.passed is True
    assert report.over_amount == 0.0


def test_exact_budget_passes():
    assert service.validate(350.0, 350.0).passed is True


def test_tolerance_boundary_still_passes():
    """允许 5% 浮动: 367.5 恰好等于上限"""
    assert service.validate(367.5, 350.0).passed is True
    assert service.validate(368.0, 350.0).passed is False


def test_over_budget_reports_amount_and_suggestion():
    report = service.validate(400.0, 350.0)
    assert report.passed is False
    assert report.over_amount == 50.0
    assert any("超出预算" in text for text in report.suggestions)


def test_no_budget_limit_always_passes():
    report = service.validate(999.0, None)
    assert report.passed is True
    assert report.budget_limit == 0.0


def test_daily_overrun_is_reported_even_without_weekly_cap():
    report = service.validate(
        100.0,
        None,
        daily=[
            {"date": "2026-03-02", "estimated": 50.0, "limit": 35.0},
            {"date": "2026-03-03", "estimated": 20.0, "limit": 35.0},
        ],
    )
    assert len(report.suggestions) == 1
    assert "2026-03-02" in report.suggestions[0]
