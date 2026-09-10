"""F2.4 多样性控制 - 与近 N 周历史菜单比对"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Set

DEFAULT_MIN_SCORE = 0.7


@dataclass
class DiversityReport:
    passed: bool
    score: float
    overlaps: List[str] = field(default_factory=list)
    issues: List[str] = field(default_factory=list)


class DiversityService:
    """菜谱名称集合的 Jaccard 相似度校验"""

    def validate(
        self,
        current_recipe_names: List[str],
        history_recipe_names: List[str],
        min_score: float = DEFAULT_MIN_SCORE,
    ) -> DiversityReport:
        current: Set[str] = {name.strip() for name in current_recipe_names if name and name.strip()}
        history: Set[str] = {name.strip() for name in history_recipe_names if name and name.strip()}

        overlaps = sorted(current & history)
        issues: List[str] = []
        if overlaps:
            issues.append(f"与近期菜单重复 {len(overlaps)} 道: {', '.join(overlaps[:5])}")

        if current and history:
            union = current | history
            score = 1.0 - (len(current & history) / len(union)) if union else 1.0
        else:
            score = 1.0

        if score < min_score:
            issues.append(f"多样性得分 {score:.2f} 低于阈值 {min_score:.2f}")

        return DiversityReport(
            passed=not issues,
            score=round(score, 4),
            overlaps=overlaps,
            issues=issues,
        )

    def pick_better(self, first: DiversityReport, second: Optional[DiversityReport]) -> DiversityReport:
        """两次生成结果取多样性更优的一份"""
        if second is None:
            return first
        if second.passed and not first.passed:
            return second
        return second if second.score > first.score and not first.passed else first
