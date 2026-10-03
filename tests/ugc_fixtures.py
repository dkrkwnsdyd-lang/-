"""UGC Reference Mode 시험용 '합성' 레퍼런스 분석 JSON (analyzer 의 Vision 응답 형태). 실제 크리에이터 영상 분석이 아니라 연출 경향을 사람이 적은 테스트 데이터."""


def _base(**kw):
    d = {"hook": {"first_1s": "불편한 장면 클로즈업", "first_3s": "문제를 말하며 제품을 든다", "first_scene": "손에 쥔 제품", "attention_devices": ["text_overlay", "face_closeup"],
                  "problem_raised": True, "curiosity": False, "twist": False, "result_first": False, "hook_pattern": "problem_first"},
         "ugc_person": {"face_visible": True, "mode": "selfie", "expression": "답답한 표정", "gaze": "camera", "gestures": ["고개 끄덕임"], "product_grip": "한 손으로 들어 보임",
                        "authenticity_cues": ["handheld_shake", "natural_light", "casual_speech"]},
         "product": {"first_appearance": 2.5, "closeup": True, "usage_process": True, "demonstration": True, "before_after": False, "result_screen": False, "usp_emphasis": "text_overlay"},
         "camera": {"shot_sizes": ["close_up", "medium"], "angles": ["eye_level"], "movements": ["handheld", "push_in"]},
         "editing": {"avg_cut": 2.0, "cut_speed": "medium", "text_timing": 0.5, "caption_position": "center", "emphasis_caption": True, "screen_zoom": True, "sfx": "sparse", "bgm_mood": "energetic"},
         "cta": {"style": "soft_recommendation", "position": 22.0},
         "structure": [{"stage": s, "start": i * 3.0, "end": i * 3.0 + 3.0} for i, s in enumerate(["hook", "problem", "agitation", "solution", "demonstration", "benefit", "cta"])],
         "emotional_tone": "공감에서 안도로", "useful_patterns": ["첫 2초 문제 제기", "손으로 직접 조작"], "scores": {"hook_strength": 72, "ugc_authenticity": 70, "demonstration_clarity": 68, "editing_quality": 70, "sales_connection": 66},
         "video_duration": 22.0, "language": "ko", "_transcript": "", "_captions": ""}
    for k, v in kw.items():
        if isinstance(v, dict) and isinstance(d.get(k), dict):
            d[k] = {**d[k], **v}
        else:
            d[k] = v
    return d


REFS = {
    "A_hook": _base(hook={"hook_pattern": "problem_first", "attention_devices": ["text_overlay", "question"]}, scores={"hook_strength": 90, "ugc_authenticity": 62, "demonstration_clarity": 55, "editing_quality": 66, "sales_connection": 60},
                    _transcript="이 가상의 테스트 문장은 실제 영상 대사가 아닙니다 절대 그대로 쓰면 안 돼요"),
    "B_selfie": _base(ugc_person={"mode": "selfie", "authenticity_cues": ["handheld_shake", "natural_light", "casual_room", "imperfect_framing", "direct_address", "casual_speech"]},
                      scores={"hook_strength": 66, "ugc_authenticity": 92, "demonstration_clarity": 60, "editing_quality": 72, "sales_connection": 64}, camera={"movements": ["handheld"], "shot_sizes": ["medium", "close_up"]}),
    "C_hands_demo": _base(ugc_person={"mode": "hands_only", "face_visible": False, "gestures": ["버튼을 누름", "제품을 돌려 보임"], "product_grip": "양손으로 받쳐 든다"},
                          product={"demonstration": True, "usage_process": True, "result_screen": True}, scores={"hook_strength": 64, "ugc_authenticity": 76, "demonstration_clarity": 93, "editing_quality": 70, "sales_connection": 70},
                          camera={"shot_sizes": ["extreme_close_up", "close_up"], "movements": ["push_in", "static"], "angles": ["top_down"]}),
    "D_before_after": _base(product={"before_after": True}, structure=[{"stage": s, "start": i * 3.0, "end": i * 3.0 + 3.0} for i, s in enumerate(["hook", "problem", "solution", "demonstration", "proof", "benefit", "cta"])],
                            scores={"hook_strength": 70, "ugc_authenticity": 68, "demonstration_clarity": 72, "editing_quality": 74, "sales_connection": 74}),
    "E_fast_cta": _base(editing={"avg_cut": 1.2, "cut_speed": "fast", "sfx": "frequent", "bgm_mood": "trending_beat", "caption_position": "bottom"}, cta={"style": "direct_link", "position": 18.0},
                        ugc_person={"mode": "talking_head"}, scores={"hook_strength": 68, "ugc_authenticity": 64, "demonstration_clarity": 58, "editing_quality": 91, "sales_connection": 88}),
}
