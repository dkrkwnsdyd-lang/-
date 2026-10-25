from types import SimpleNamespace

from shortsmaker.studio.korean_style import KO_STYLE_RULES
from shortsmaker.studio.strategy import common


class CaptureRouter:
    """실제 LLM 대신 지시문만 받아 두는 가짜 라우터."""

    def __init__(self):
        self.systems = []

    def has_real(self, task):
        return True

    def run(self, task, fmt, system="", **kw):
        self.systems.append(system)
        return SimpleNamespace(provider="fake", value={"ok": True})


def test_style_rules_reach_strategy_llm_calls():
    r = CaptureRouter()
    assert common.ask(r, "대본을 쓴다.", {"x": 1}) == {"ok": True}
    sent = r.systems[0]
    assert KO_STYLE_RULES in sent
    # 사실 규칙이 먼저 오고 말투 규칙은 그 뒤에 붙는다 (사실 규칙 우선)
    assert sent.index(common.SAFETY_RULES) < sent.index(KO_STYLE_RULES)


def test_style_rules_cover_core_ai_tells():
    for tell in ("~를 통해", "~에 있어서", "되어진다", "결론적으로", "시사하는 바가 크다", "~다는 것이다"):
        assert tell in KO_STYLE_RULES
    assert "상품명·숫자·단위·인용은 그대로" in KO_STYLE_RULES
