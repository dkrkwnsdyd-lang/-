"""하이브리드 출연 방식(실제 사람 영상 / AI 아바타 / AI 제품사용 UGC) + 비용 제어. 기존 전략/Storyboard/렌더러에 얹는 독립 모듈."""
from .modes import ACTOR_KO, ACTOR_MODES, SOURCE_BADGE, plan_production, uses_real_clips
from .cost import COST_MODES

__all__ = ["ACTOR_MODES", "ACTOR_KO", "COST_MODES", "SOURCE_BADGE", "plan_production", "uses_real_clips"]
