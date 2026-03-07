"""
카카오 i 오픈빌더 스킬 서버 (FastAPI)
로체 봇을 카카오 채널 챗봇과 연동합니다.

실행:
  uvicorn kakao_skill_server:app --host 0.0.0.0 --port 8000

카카오 오픈빌더 스킬 URL 설정:
  https://<your-domain>/skill/chat        ← 텍스트 질의
  https://<your-domain>/skill/location    ← 위치 기반 검색
"""

import math
import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from hospital_agents.main import build_team

# ---------------------------------------------------------------------------
# 초기화
# ---------------------------------------------------------------------------

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="로체 봇 카카오 스킬 서버")

team = build_team(use_dummy=True)
collector = team["collector"]
checker   = team["checker"]
bot       = team["bot"]
store     = team["store"]

# 데이터 없으면 초기 수집
if not store.all_hospitals():
    collector.run()
    checker.run()


# ---------------------------------------------------------------------------
# 거리 계산 (Haversine)
# ---------------------------------------------------------------------------

def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """두 좌표 사이의 거리(km)를 반환합니다."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


def _nearby(items: list[dict], lat: float, lon: float, radius_km: float = 5.0) -> list[dict]:
    """반경 radius_km 이내 시설을 거리순으로 반환합니다."""
    result = []
    for item in items:
        ilat = float(item.get("latitude") or 0)
        ilon = float(item.get("longitude") or 0)
        if ilat == 0 and ilon == 0:
            continue
        dist = _haversine(lat, lon, ilat, ilon)
        if dist <= radius_km:
            result.append({**item, "_dist_km": round(dist, 2)})
    return sorted(result, key=lambda x: x["_dist_km"])


# ---------------------------------------------------------------------------
# 카카오 응답 빌더
# ---------------------------------------------------------------------------

def _simple_text(text: str) -> dict:
    """SimpleText 말풍선"""
    return {
        "version": "2.0",
        "template": {
            "outputs": [{"simpleText": {"text": text}}]
        }
    }


def _list_card(title: str, items: list[dict], buttons: list[dict] | None = None) -> dict:
    """ListCard 말풍선 (최대 5개)"""
    return {
        "version": "2.0",
        "template": {
            "outputs": [{
                "listCard": {
                    "header": {"title": title},
                    "items": items[:5],
                    **({"buttons": buttons} if buttons else {}),
                }
            }]
        }
    }


def _carousel(cards: list[dict]) -> dict:
    """Carousel(BasicCard 묶음) 말풍선"""
    return {
        "version": "2.0",
        "template": {
            "outputs": [{
                "carousel": {
                    "type": "basicCard",
                    "items": cards[:10],
                }
            }]
        }
    }


def _basic_card(title: str, desc: str, buttons: list[dict] | None = None) -> dict:
    """BasicCard 단일 카드 (carousel 내부용)"""
    card: dict = {"title": title, "description": desc}
    if buttons:
        card["buttons"] = buttons
    return card


def _kakao_map_btn(name: str, lat: float, lon: float) -> dict:
    """카카오맵 길찾기 버튼"""
    return {
        "action": "webLink",
        "label": "지도 보기",
        "webLinkUrl": f"https://map.kakao.com/link/map/{name},{lat},{lon}",
    }


def _phone_btn(phone: str) -> dict:
    """전화 버튼"""
    return {"action": "phone", "label": "전화하기", "phoneNumber": phone}


# ---------------------------------------------------------------------------
# 엔드포인트 — 텍스트 챗
# ---------------------------------------------------------------------------

@app.post("/skill/chat")
async def skill_chat(request: Request) -> JSONResponse:
    """
    카카오 i 오픈빌더 → 텍스트 발화 처리

    오픈빌더 스킬 설정:
      URL: https://<domain>/skill/chat
      Method: POST
    """
    body: dict = await request.json()
    utterance: str = body.get("userRequest", {}).get("utterance", "")
    logger.info("[chat] utterance=%s", utterance)

    reply = bot.chat(utterance)
    return JSONResponse(_simple_text(reply))


# ---------------------------------------------------------------------------
# 엔드포인트 — 위치 기반 검색
# ---------------------------------------------------------------------------

@app.post("/skill/location")
async def skill_location(request: Request) -> JSONResponse:
    """
    사용자가 [위치 보내기]를 탭하면 호출됩니다.

    카카오 오픈빌더에서 '위치 블록'을 만들고
    위치 파라미터(sys.location)를 이 스킬로 전달하도록 설정하세요.

    요청 예시 (카카오가 보내는 JSON):
    {
      "userRequest": { "utterance": "주변 병원" },
      "action": {
        "params": {
          "location": "{\"lat\": 36.35, \"lng\": 127.38, \"name\": \"현재위치\"}"
        }
      }
    }
    """
    body: dict = await request.json()

    # 위치 파라미터 파싱
    import json as _json
    params = body.get("action", {}).get("params", {})
    loc_raw = params.get("location", "{}")
    try:
        loc = _json.loads(loc_raw) if isinstance(loc_raw, str) else loc_raw
    except Exception:
        loc = {}

    lat = float(loc.get("lat") or loc.get("latitude") or 0)
    lon = float(loc.get("lng") or loc.get("longitude") or 0)
    utterance: str = body.get("userRequest", {}).get("utterance", "")

    logger.info("[location] lat=%s lon=%s utterance=%s", lat, lon, utterance)

    if lat == 0 and lon == 0:
        return JSONResponse(_simple_text("위치 정보를 받지 못했습니다. 다시 위치를 보내 주세요."))

    # 약국 또는 병원 여부 판단
    want_pharmacy = "약국" in utterance

    if want_pharmacy:
        items = _nearby(store.all_pharmacies(), lat, lon, radius_km=3.0)
        kind = "약국"
    else:
        items = _nearby(store.all_hospitals(), lat, lon, radius_km=5.0)
        kind = "병원"

    if not items:
        radius = 3 if want_pharmacy else 5
        return JSONResponse(_simple_text(
            f"반경 {radius}km 이내에 등록된 {kind}이 없습니다.\n"
            "더 넓은 범위나 다른 지역을 검색해 보세요."
        ))

    # BasicCard carousel 구성
    cards = []
    for item in items[:6]:
        dist_str = f"{item['_dist_km']} km"
        if want_pharmacy:
            duty_str = " 🌙당번" if item.get("duty_pharmacy") else ""
            status = store.get_today_pharmacy_status(item["id"])
            open_str = "✅ 영업중" if (status and status.get("is_open")) else "❌ 휴무"
            desc = (
                f"{dist_str}{duty_str} | {open_str}\n"
                f"📍 {item.get('address', '')}\n"
                f"⏰ {status.get('hours', '-') if status else '-'}"
            )
        else:
            status = store.get_today_status(item["id"])
            open_str = "✅ 영업중" if (status and status.get("is_open")) else "❌ 휴진"
            emg = " 🚨응급" if item.get("emergency") else ""
            desc = (
                f"{dist_str}{emg} | {open_str}\n"
                f"📍 {item.get('address', '')}\n"
                f"⏰ {status.get('hours', '-') if status else '-'}"
            )

        buttons = []
        if item.get("latitude") and item.get("longitude"):
            buttons.append(_kakao_map_btn(item["name"], item["latitude"], item["longitude"]))
        if item.get("phone"):
            buttons.append(_phone_btn(item["phone"]))

        cards.append(_basic_card(item["name"], desc, buttons or None))

    title = f"📍 근처 {kind} {len(items)}개 (가까운 순)"
    if len(items) > 6:
        title += f" — 상위 6개 표시"

    return JSONResponse(_carousel(cards))


# ---------------------------------------------------------------------------
# 엔드포인트 — 당번약국 빠른 조회
# ---------------------------------------------------------------------------

@app.post("/skill/duty_pharmacy")
async def skill_duty_pharmacy(request: Request) -> JSONResponse:
    """당번약국 목록을 반환합니다 (위치 없이도 동작)."""
    body: dict = await request.json()

    # 위치가 있으면 가까운 순으로
    import json as _json
    params = body.get("action", {}).get("params", {})
    loc_raw = params.get("location", "{}")
    try:
        loc = _json.loads(loc_raw) if isinstance(loc_raw, str) else loc_raw
    except Exception:
        loc = {}

    lat = float(loc.get("lat") or 0)
    lon = float(loc.get("lng") or 0)

    duty_pharmacies = [p for p in store.all_pharmacies() if p.get("duty_pharmacy")]

    if not duty_pharmacies:
        return JSONResponse(_simple_text("등록된 당번약국이 없습니다."))

    if lat and lon:
        # 위치 있으면 거리순
        duty_pharmacies = _nearby(duty_pharmacies, lat, lon, radius_km=20.0) or duty_pharmacies

    cards = []
    for p in duty_pharmacies[:6]:
        status = store.get_today_pharmacy_status(p["id"])
        open_str = "✅ 영업중" if (status and status.get("is_open")) else "❌ 휴무"
        dist_str = f"{p['_dist_km']} km | " if "_dist_km" in p else ""
        desc = (
            f"🌙 당번약국 | {dist_str}{open_str}\n"
            f"📍 {p.get('address', '')}\n"
            f"⏰ {status.get('hours', '-') if status else '-'}"
        )
        buttons = []
        if p.get("latitude") and p.get("longitude"):
            buttons.append(_kakao_map_btn(p["name"], p["latitude"], p["longitude"]))
        if p.get("phone"):
            buttons.append(_phone_btn(p["phone"]))
        cards.append(_basic_card(p["name"], desc, buttons or None))

    return JSONResponse(_carousel(cards))


# ---------------------------------------------------------------------------
# 헬스체크
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "hospitals": len(store.all_hospitals()),
        "pharmacies": len(store.all_pharmacies()),
    }


# ---------------------------------------------------------------------------
# 실행
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
