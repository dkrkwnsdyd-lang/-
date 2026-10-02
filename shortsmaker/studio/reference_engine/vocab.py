"""REFERENCE_VIDEO_ENGINE 어휘: 패턴은 이 어휘의 값과 숫자로만 저장한다 (자유 문장 저장 금지 → 복제 방지)."""
from __future__ import annotations

PLATFORMS = ("youtube_shorts", "instagram_reels", "xiaohongshu", "tiktok", "upload", "other")
PLATFORM_KO = {"youtube_shorts": "YouTube Shorts", "instagram_reels": "Instagram Reels", "xiaohongshu": "샤오홍슈(RedNote)", "tiktok": "TikTok",
               "upload": "사용자 업로드", "other": "기타"}
HOOK_PATTERNS = ("problem_first", "question", "curiosity_gap", "empathy", "shock_visual", "demo_first", "number_list", "direct_address", "pov", "other")
STORY_STAGES = ("hook", "situation", "problem", "emotion", "turning_point", "product_reveal", "demo", "benefit", "proof", "cta")
CAPTION_PATTERNS = ("short_center", "short_bottom", "top_keyword", "dense_bottom", "karaoke_word", "none")
MOTION_PATTERNS = ("fast_cut", "punch_in", "slow_zoom", "ken_burns", "pan", "parallax", "handheld", "static")
TRANSITION_PATTERNS = ("hard_cut", "whip", "flash", "soft_dissolve", "match_cut")
CTA_PATTERNS = ("soft_recommendation", "direct_link", "scarcity", "question", "none")
EMOTION_CURVES = ("flat", "rise", "dip_then_rise", "peak_end", "curiosity_build")
CONTENT_STYLES = ("fast_commerce", "story", "ugc", "lifestyle", "demo", "comparison", "before_after", "unboxing")
BGM_MOODS = ("energetic", "calm", "cinematic", "acoustic", "trending_beat", "none")
SFX_PATTERNS = ("none", "sparse", "frequent")
CAPTION_POSITIONS = ("top", "center", "bottom")
CAPTION_DENSITY = ("low", "medium", "high")
CAPTION_CHANGE = ("slow", "medium", "fast")

LIBRARY_TAGS = ("PROBLEM_STORY", "FAST_REVEAL", "LATE_PRODUCT_REVEAL", "UGC_DISCOVERY", "BEFORE_AFTER", "EMOTIONAL_STORY", "COMPARISON", "DEMO", "LIFESTYLE")
SCORE_KEYS = ("hook_strength", "story_strength", "editing_quality", "visual_quality", "product_fit", "shortform_fit", "sales_connection")

# 플랫폼별 분석 포인트 (프롬프트/가중치에 사용) — 각 플랫폼의 영상을 따라하지 않고 강점만 본다
PLATFORM_FOCUS = {
    "youtube_shorts": "Hook, retention structure, scene tempo, product reveal timing, CTA",
    "instagram_reels": "fast cuts, UGC feel, caption rhythm, lifestyle scene, motion, transition",
    "xiaohongshu": "lifestyle story, problem situation, emotional flow, before/after, natural product placement, story-based reveal, visual composition",
    "tiktok": "hook, pacing, trend-style captions",
    "upload": "overall structure",
    "other": "overall structure",
}
# 자동 조합(AUTO MIX)에서 플랫폼이 우선 기여하는 영역
PLATFORM_STRENGTH = {"youtube_shorts": ("hook", "cta", "reveal"), "instagram_reels": ("tempo", "caption", "motion", "transition"),
                     "xiaohongshu": ("story", "emotion", "reveal")}
