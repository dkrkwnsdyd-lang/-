import type {ShortsScript} from '../scenes/ShortsFromScript';

// 분석기(남다른AI Shorts 분석기)가 내보내는 대본 형식 그대로의 예시
// title = 고른 아이디어 제목, scenes = 대본 JSON 의 scenes 배열
export const sampleScript: ShortsScript = {
  title: '싱크대 밑, 이것 하나로 끝',
  scenes: [
    {
      sceneNumber: 1,
      time: '0:00 - 0:03',
      narration: '싱크대 밑에서 세제 찾다가 허리 나갈 뻔했어요.',
      visual: '꽉 찬 싱크대 하부장을 극접사로, 손이 물건 사이를 헤집는 장면',
      caption: '허리 나갈 뻔',
      sfx: 'Fast Whoosh + 덜컹 효과음',
    },
    {
      sceneNumber: 2,
      time: '0:03 - 0:07',
      narration: '배수관 때문에 선반도 못 넣는 그 공간, 다들 비슷하죠?',
      visual: '배수관을 중심으로 한 하부장 정면 와이드샷',
      caption: '배수관이 문제',
      sfx: '물음표 Pop',
    },
    {
      sceneNumber: 3,
      time: '0:07 - 0:11',
      narration: '배수관을 피해서 들어가는 2단 슬라이딩 선반을 넣어 봤어요.',
      visual: '선반 두 개를 배수관 양옆에 끼워 넣는 손 클로즈업',
      caption: '2단 슬라이딩 선반',
      sfx: '딸깍 + 경쾌한 BGM 시작',
    },
    {
      sceneNumber: 4,
      time: '0:11 - 0:15',
      narration: '쭉 당기기만 하면 안쪽 물건까지 한 번에 다 보여요.',
      visual: '선반을 앞으로 당기는 슬로모션, 물건이 정렬된 모습',
      caption: '쭉 당기면 끝',
      sfx: '슬라이드 Swoosh',
    },
    {
      sceneNumber: 5,
      time: '0:15 - 0:19',
      narration: '어떤 제품인지 궁금하면 댓글에 정리라고 남겨 주세요.',
      visual: '정리된 하부장 전체 샷, 문을 닫으며 마무리',
      caption: '댓글에 "정리"',
      sfx: 'Bass Drop 후 BGM 페이드아웃',
    },
  ],
};
