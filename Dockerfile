# SHOP SHORTS AI - 서버용 이미지 (폰/앱에서 접속하는 웹 서버)
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

# 한글 자막 폰트 (영상 렌더링에 필요)
RUN apt-get update && apt-get install -y --no-install-recommends fonts-nanum ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt pillow-heif

COPY shortsmaker ./shortsmaker
COPY config.example.yaml ./config.example.yaml

# 결과물/DB/업로드는 볼륨에 저장 (컨테이너를 지워도 유지)
VOLUME ["/app/output", "/app/data", "/app/uploads"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4)" || exit 1

# 외부에서 접속하므로 반드시 SHORTSMAKER_ACCESS_CODE 를 지정하세요 (없으면 시작할 때 자동 생성되어 로그에 표시됨)
CMD ["python", "-m", "shortsmaker", "web", "--host", "0.0.0.0", "--port", "8000"]
