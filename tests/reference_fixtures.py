"""REFERENCE_VIDEO_ENGINE 시험용 '합성' 참고 영상 분석 결과 10개 (analyzer 가 돌려줄 raw 형태).

주의: 실제 플랫폼 영상을 분석한 값이 아니다. 이 환경은 YouTube/Instagram/샤오홍슈에 접속할 수 없어서, 각 플랫폼의 일반적 연출 경향을 사람이 추상 패턴으로 적은
테스트 데이터다 (실제 크리에이터의 영상/문장 아님). _transcript 는 복제 방지 해시 시험용 가짜 문장이다.
"""


def _d(**kw):
    base = {"hook_pattern": "question", "hook_duration": 2.0, "video_duration": 20.0, "scene_count": 9, "story_stages": ["hook", "product_reveal", "demo", "benefit", "cta"],
            "product_reveal_time": 3.0, "caption_density": "medium", "caption_position": "center", "caption_pattern": "short_center", "caption_change_frequency": "fast",
            "camera_motion": ["punch_in"], "image_motion": ["fast_cut"], "transition_pattern": ["hard_cut"], "sfx_pattern": "sparse", "bgm_mood": "energetic",
            "cta_pattern": "soft_recommendation", "cta_position": 17.0, "content_style": "fast_commerce", "emotion_curve": "rise", "selling_structure": "빠른 공개형",
            "story_roles": {"situation": "", "problem": "", "emotion": "", "turning_point": "", "product_role": "해결책", "result": "", "cta": "부드러운 권유"},
            "scores": {"hook_strength": 70, "story_strength": 55, "editing_quality": 70, "visual_quality": 65, "shortform_fit": 75, "sales_connection": 65},
            "language": "ko", "_transcript": "", "_captions": ""}
    base.update(kw)
    return base


REFS = {
    "yt1_problem_fast": ("youtube_shorts", _d(hook_pattern="problem_first", hook_duration=1.6, product_reveal_time=3.5, content_style="fast_commerce",
                                              story_stages=["hook", "problem", "product_reveal", "demo", "cta"], cta_pattern="direct_link",
                                              scores={"hook_strength": 88, "story_strength": 60, "editing_quality": 72, "visual_quality": 70, "shortform_fit": 85, "sales_connection": 80},
                                              _transcript="이 가상의 테스트 문장은 실제 영상이 아닙니다 절대 복사하면 안 되는 문장")),
    "yt2_curiosity_demo": ("youtube_shorts", _d(hook_pattern="curiosity_gap", hook_duration=2.4, content_style="demo", story_stages=["hook", "demo", "product_reveal", "benefit", "cta"],
                                                product_reveal_time=6.0, cta_pattern="question",
                                                scores={"hook_strength": 82, "story_strength": 58, "editing_quality": 66, "visual_quality": 68, "shortform_fit": 80, "sales_connection": 76})),
    "yt3_number_compare": ("youtube_shorts", _d(hook_pattern="number_list", content_style="comparison", story_stages=["hook", "problem", "demo", "product_reveal", "cta"],
                                                product_reveal_time=7.5, cta_pattern="scarcity",
                                                scores={"hook_strength": 74, "story_strength": 62, "editing_quality": 64, "visual_quality": 62, "shortform_fit": 70, "sales_connection": 78})),
    "ig1_ugc_fast": ("instagram_reels", _d(hook_pattern="pov", hook_duration=1.2, content_style="ugc", average_scene_duration=1.4, scene_count=14,
                                           camera_motion=["handheld"], image_motion=["fast_cut", "punch_in"], transition_pattern=["whip", "hard_cut"], caption_pattern="karaoke_word",
                                           caption_density="high", sfx_pattern="frequent", bgm_mood="trending_beat", story_stages=["hook", "demo", "product_reveal", "benefit", "cta"],
                                           scores={"hook_strength": 72, "story_strength": 55, "editing_quality": 90, "visual_quality": 74, "shortform_fit": 88, "sales_connection": 62})),
    "ig2_lifestyle": ("instagram_reels", _d(hook_pattern="empathy", content_style="lifestyle", average_scene_duration=2.0, camera_motion=["ken_burns"], image_motion=["slow_zoom"],
                                            transition_pattern=["soft_dissolve"], caption_pattern="short_bottom", caption_position="bottom", sfx_pattern="none", bgm_mood="acoustic",
                                            story_stages=["hook", "situation", "product_reveal", "benefit", "cta"], product_reveal_time=5.0, cta_pattern="soft_recommendation",
                                            scores={"hook_strength": 66, "story_strength": 68, "editing_quality": 78, "visual_quality": 82, "shortform_fit": 74, "sales_connection": 60})),
    "ig3_before_after": ("instagram_reels", _d(hook_pattern="shock_visual", content_style="before_after", average_scene_duration=1.8, story_stages=["hook", "problem", "product_reveal", "benefit", "cta"],
                                               product_reveal_time=4.5, transition_pattern=["flash", "whip"],
                                               scores={"hook_strength": 80, "story_strength": 66, "editing_quality": 82, "visual_quality": 76, "shortform_fit": 80, "sales_connection": 72})),
    "xhs1_story": ("xiaohongshu", _d(hook_pattern="empathy", hook_duration=2.8, content_style="story", language="zh", video_duration=24.0, scene_count=10, average_scene_duration=2.4,
                                      story_stages=["hook", "situation", "problem", "emotion", "turning_point", "product_reveal", "benefit", "proof", "cta"], product_reveal_time=9.5,
                                      emotion_curve="dip_then_rise", camera_motion=["slow_zoom"], image_motion=["slow_zoom", "parallax"], transition_pattern=["soft_dissolve"],
                                      caption_pattern="short_center", caption_density="low", sfx_pattern="sparse", bgm_mood="calm", cta_pattern="soft_recommendation",
                                      story_roles={"situation": "하루의 일상 상황", "problem": "작은 불편의 반복", "emotion": "답답함", "turning_point": "분위기 전환", "product_role": "자연스러운 해결책", "result": "편안해진 일상", "cta": "부드러운 마무리"},
                                      scores={"hook_strength": 68, "story_strength": 90, "editing_quality": 74, "visual_quality": 86, "shortform_fit": 72, "sales_connection": 70},
                                      _transcript="가상의 중국어 번역 테스트 문장입니다 실제 샤오홍슈 영상이 아니에요")),
    "xhs2_emotional": ("xiaohongshu", _d(hook_pattern="empathy", content_style="lifestyle", language="zh", story_stages=["hook", "situation", "emotion", "turning_point", "product_reveal", "benefit", "cta"],
                                         product_reveal_time=8.0, emotion_curve="dip_then_rise", average_scene_duration=2.6, camera_motion=["ken_burns"], transition_pattern=["match_cut"],
                                         scores={"hook_strength": 64, "story_strength": 84, "editing_quality": 70, "visual_quality": 84, "shortform_fit": 68, "sales_connection": 64})),
    "xhs3_beforeafter_story": ("xiaohongshu", _d(hook_pattern="problem_first", content_style="before_after", language="zh", story_stages=["hook", "problem", "emotion", "product_reveal", "benefit", "cta"],
                                                product_reveal_time=7.0, emotion_curve="dip_then_rise", average_scene_duration=2.2,
                                                scores={"hook_strength": 72, "story_strength": 80, "editing_quality": 72, "visual_quality": 80, "shortform_fit": 70, "sales_connection": 74})),
    "xhs4_natural_unbox": ("xiaohongshu", _d(hook_pattern="pov", content_style="unboxing", language="zh", story_stages=["hook", "product_reveal", "demo", "benefit", "cta"],
                                             product_reveal_time=2.5, average_scene_duration=2.1, camera_motion=["pan"], image_motion=["slow_zoom"], bgm_mood="calm",
                                             scores={"hook_strength": 66, "story_strength": 70, "editing_quality": 68, "visual_quality": 82, "shortform_fit": 70, "sales_connection": 66})),
}


def analysis(key: str) -> dict:
    platform, data = REFS[key]
    return {"platform": platform, "source_ref": f"synthetic:{key}", "method": "synthetic_fixture", "status": "VERIFIED", "data": dict(data), "local": {}, "note": ""}
