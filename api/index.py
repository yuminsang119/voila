"""
Vercel serverless entry point
프로젝트 루트를 sys.path에 추가하고 FastAPI app을 노출합니다.
"""
import sys
from pathlib import Path

# 프로젝트 루트를 모듈 검색 경로에 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

from web_app import app  # noqa: F401 — Vercel이 ASGI app으로 인식
