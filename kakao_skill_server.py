"""
카카오 i 오픈빌더 스킬 서버 (FastAPI)
로체 봇을 카카오 채널 챗봇과 연동합니다.

[위치정보사업자 불필요 설계]
  - 단말기 GPS 자동 수집 없음
  - 사용자가 직접 입력한 주소(텍스트) → 카카오 Local API로 좌표 변환
  - 또는 대전 행정구역 버튼 선택 방식

실행:
  uvicorn kakao_skill_server:app --host 0.0.0.0 --port 8000

환경변수:
  KAKAO_REST_API_KEY   카카오 REST API 키 (Local API 주소검색용)

카카오 오픈빌더 스킬 URL:
  POST /skill/chat            텍스트 질의 → 로체봇 응답
  POST /skill/search_address  주소 텍스트 → 주변 병원·약국
  POST /skill/select_district 행정구역 버튼 선택 → 주변 병원·약국
  POST /skill/duty_pharmacy   당번약국 목록
"""

import json
import math
import os
import logging

import requests as _requests
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from hospital_agents.main import build_team

# ---------------------------------------------------------------------------
# 초기화
# ---------------------------------------------------------------------------

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="로체 봇 카카오 스킬 서버")

# 카카오 REST API 키 (주소→좌표 변환용, 위치정보사업자와 무관)
KAKAO_REST_KEY = os.environ.get("KAKAO_REST_API_KEY", "")

team = build_team(use_dummy=True)
collector = team["collector"]
checker   = team["checker"]
bot       = team["bot"]
store     = team["store"]

if not store.all_hospitals():
    collector.run()
    checker.run()

# ---------------------------------------------------------------------------
# 대전 행정구역 중심 좌표 (버튼 선택 방식 — 위치정보 수집 없음)
# ---------------------------------------------------------------------------

DAEJEON_DISTRICTS = {
    "서구":  (36.3551, 127.3838),
    "중구":  (36.3259, 127.4268),
    "동구":  (36.3122, 127.4545),
    "유성구": (36.3624, 127.3564),
    "대덕구": (36.3466, 127.4153),
}

# ---------------------------------------------------------------------------
# 주소 → 좌표 변환 (카카오 Local API)
# 사용자가 입력한 주소 문자열을 좌표로 변환 — GPS 수집 아님
# ---------------------------------------------------------------------------

def _address_to_coord(address: str) -> tuple[float, float] | None:
    """
    카카오 주소검색 API로 텍스트 주소를 (위도, 경도)로 변환합니다.
    이 API는 위치정보사업자 등록 없이 사용 가능합니다.
    """
    if not KAKAO_REST_KEY:
        # API 키 없으면 대전 중심 좌표로 대체
        return (36.3504, 127.3845)

    try:
        resp = _requests.get(
            "https://dapi.kakao.com/v2/local/search/address.json",
            headers={"Authorization": f"KakaoAK {KAKAO_REST_KEY}"},
            params={"query": address},
            timeout=5,
        )
        docs = resp.json().get("documents", [])
        if docs:
            return float(docs[0]["y"]), float(docs[0]["x"])

        # 주소 검색 실패 시 키워드 검색으로 재시도
        resp2 = _requests.get(
            "https://dapi.kakao.com/v2/local/search/keyword.json",
            headers={"Authorization": f"KakaoAK {KAKAO_REST_KEY}"},
            params={"query": address, "rect": "127.28,36.22,127.54,36.48"},
            timeout=5,
        )
        docs2 = resp2.json().get("documents", [])
        if docs2:
            return float(docs2[0]["y"]), float(docs2[0]["x"])
    except Exception as e:
        logger.warning("주소→좌표 변환 실패: %s", e)

    return None

# ---------------------------------------------------------------------------
# 거리 계산 (Haversine)
# ---------------------------------------------------------------------------

def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


def _nearby(items: list[dict], lat: float, lon: float, radius_km: float = 5.0) -> list[dict]:
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

def _simple_text(text: str, quick_replies: list[dict] | None = None) -> dict:
    resp: dict = {
        "version": "2.0",
        "template": {
            "outputs": [{"simpleText": {"text": text}}],
        }
    }
    if quick_replies:
        resp["template"]["quickReplies"] = quick_replies
    return resp


def _carousel(cards: list[dict], quick_replies: list[dict] | None = None) -> dict:
    resp: dict = {
        "version": "2.0",
        "template": {
            "outputs": [{"carousel": {"type": "basicCard", "items": cards[:10]}}],
        }
    }
    if quick_replies:
        resp["template"]["quickReplies"] = quick_replies
    return resp


def _basic_card(title: str, desc: str, buttons: list[dict] | None = None) -> dict:
    card: dict = {"title": title, "description": desc}
    if buttons:
        card["buttons"] = buttons
    return card


def _kakao_map_btn(name: str, lat: float, lon: float) -> dict:
    return {
        "action": "webLink",
        "label": "지도 보기",
        "webLinkUrl": f"https://map.kakao.com/link/map/{name},{lat},{lon}",
    }


def _phone_btn(phone: str) -> dict:
    return {"action": "phone", "label": "전화하기", "phoneNumber": phone}


def _district_quick_replies(action_name: str) -> list[dict]:
    """대전 5개 구 선택 버튼 (QuickReply)"""
    return [
        {"action": "block", "label": f"📍 {dist}", "blockId": action_name, "extra": {"district": dist}}
        for dist in DAEJEON_DISTRICTS
    ]


# ---------------------------------------------------------------------------
# 공통 — 좌표 기반 검색 결과 Carousel 생성
# ---------------------------------------------------------------------------

def _build_carousel(lat: float, lon: float, want_pharmacy: bool) -> dict:
    kind = "약국" if want_pharmacy else "병원"
    radius = 3.0 if want_pharmacy else 5.0

    items = (
        _nearby(store.all_pharmacies(), lat, lon, radius)
        if want_pharmacy
        else _nearby(store.all_hospitals(), lat, lon, radius)
    )

    if not items:
        return _simple_text(
            f"반경 {int(radius)}km 이내에 등록된 {kind}이 없습니다.\n"
            "다른 구를 선택하거나 더 넓은 지역을 검색해 보세요.",
            quick_replies=_district_quick_replies("district_search"),
        )

    cards = []
    for item in items[:6]:
        dist_str = f"{item['_dist_km']} km"
        if want_pharmacy:
            duty_str = " 🌙당번" if item.get("duty_pharmacy") else ""
            status = store.get_today_pharmacy_status(item["id"])
            open_str = "✅ 영업중" if (status and status.get("is_open")) else "❌ 휴무"
            desc = f"{dist_str}{duty_str} | {open_str}\n📍 {item.get('address','')}\n⏰ {status.get('hours','-') if status else '-'}"
        else:
            status = store.get_today_status(item["id"])
            open_str = "✅ 영업중" if (status and status.get("is_open")) else "❌ 휴진"
            emg = " 🚨응급" if item.get("emergency") else ""
            desc = f"{dist_str}{emg} | {open_str}\n📍 {item.get('address','')}\n⏰ {status.get('hours','-') if status else '-'}"

        btns = []
        if item.get("latitude") and item.get("longitude"):
            btns.append(_kakao_map_btn(item["name"], item["latitude"], item["longitude"]))
        if item.get("phone"):
            btns.append(_phone_btn(item["phone"]))
        cards.append(_basic_card(item["name"], desc, btns or None))

    return _carousel(cards)


# ---------------------------------------------------------------------------
# 엔드포인트 1 — 텍스트 챗
# ---------------------------------------------------------------------------

@app.post("/skill/chat")
async def skill_chat(request: Request) -> JSONResponse:
    """일반 텍스트 발화 → 로체봇 응답"""
    body: dict = await request.json()
    utterance: str = body.get("userRequest", {}).get("utterance", "")
    logger.info("[chat] %s", utterance)

    reply = bot.chat(utterance)

    # 병원/약국 검색 의도가 있으면 구 선택 버튼 추가 안내
    qr = None
    if any(kw in utterance for kw in ("병원", "약국", "주변", "근처")):
        qr = _district_quick_replies("district_search")

    return JSONResponse(_simple_text(reply, qr))


# ---------------------------------------------------------------------------
# 엔드포인트 2 — 주소 텍스트 입력 → 주변 검색
# (위치정보 수집 없음 — 사용자가 직접 입력한 텍스트 주소 사용)
# ---------------------------------------------------------------------------

@app.post("/skill/search_address")
async def skill_search_address(request: Request) -> JSONResponse:
    """
    사용자가 직접 입력한 주소(예: '둔산동', '대전시청')를
    카카오 주소검색 API로 좌표로 변환 후 주변 시설 안내.

    오픈빌더 블록 설정:
      사용자 발화 예시: "둔산동 병원 찾아줘", "갈마동 약국"
      파라미터: address (사용자 발화에서 추출)
    """
    body: dict = await request.json()
    params = body.get("action", {}).get("params", {})
    utterance: str = body.get("userRequest", {}).get("utterance", "")

    # 파라미터로 받거나 발화 전체를 주소로 사용
    address = params.get("address") or utterance
    want_pharmacy = "약국" in utterance

    logger.info("[search_address] address=%s pharmacy=%s", address, want_pharmacy)

    coord = _address_to_coord(address)
    if not coord:
        return JSONResponse(_simple_text(
            f"'{address}' 위치를 찾지 못했습니다.\n"
            "동네 이름이나 도로명 주소로 다시 입력해 주세요.\n"
            "예) '둔산동', '대전시청', '갈마동'",
            quick_replies=_district_quick_replies("district_search"),
        ))

    lat, lon = coord
    return JSONResponse(_build_carousel(lat, lon, want_pharmacy))


# ---------------------------------------------------------------------------
# 엔드포인트 3 — 행정구역 버튼 선택 → 주변 검색
# (위치정보 수집 없음 — 미리 정의된 구 중심 좌표 사용)
# ---------------------------------------------------------------------------

@app.post("/skill/select_district")
async def skill_select_district(request: Request) -> JSONResponse:
    """
    대전 5개 구(서구/중구/동구/유성구/대덕구) 버튼 선택 시 호출.

    오픈빌더에서 QuickReply 버튼의 extra 파라미터로 district 전달.
    """
    body: dict = await request.json()
    params = body.get("action", {}).get("params", {})
    utterance: str = body.get("userRequest", {}).get("utterance", "")

    district = params.get("district", "")
    want_pharmacy = "약국" in utterance

    # 발화에서 구 이름 추출 (버튼 텍스트 포함)
    if not district:
        for d in DAEJEON_DISTRICTS:
            if d in utterance:
                district = d
                break

    logger.info("[select_district] district=%s pharmacy=%s", district, want_pharmacy)

    if district not in DAEJEON_DISTRICTS:
        qr = _district_quick_replies("district_search")
        return JSONResponse(_simple_text(
            "어느 구를 선택하시겠어요?",
            quick_replies=qr,
        ))

    lat, lon = DAEJEON_DISTRICTS[district]
    kind = "약국" if want_pharmacy else "병원"
    result = _build_carousel(lat, lon, want_pharmacy)

    # 결과 앞에 안내 텍스트 추가
    if "outputs" in result.get("template", {}):
        result["template"]["outputs"].insert(0, {
            "simpleText": {"text": f"📍 {district} 주변 {kind} 안내입니다."}
        })

    return JSONResponse(result)


# ---------------------------------------------------------------------------
# 엔드포인트 4 — 당번약국 (위치 무관)
# ---------------------------------------------------------------------------

@app.post("/skill/duty_pharmacy")
async def skill_duty_pharmacy(request: Request) -> JSONResponse:
    """당번약국 목록 (구 선택 시 해당 구 필터)"""
    body: dict = await request.json()
    params = body.get("action", {}).get("params", {})
    utterance: str = body.get("userRequest", {}).get("utterance", "")

    district = params.get("district", "")
    if not district:
        for d in DAEJEON_DISTRICTS:
            if d in utterance:
                district = d
                break

    duty = [p for p in store.all_pharmacies() if p.get("duty_pharmacy")]

    if district:
        duty = [p for p in duty if district in p.get("address", "")]

    if not duty:
        return JSONResponse(_simple_text(
            "등록된 당번약국이 없습니다.",
            quick_replies=_district_quick_replies("duty_pharmacy"),
        ))

    cards = []
    for p in duty[:6]:
        status = store.get_today_pharmacy_status(p["id"])
        open_str = "✅ 영업중" if (status and status.get("is_open")) else "❌ 휴무"
        desc = (
            f"🌙 당번약국 | {open_str}\n"
            f"📍 {p.get('address','')}\n"
            f"⏰ {status.get('hours','-') if status else '-'}"
        )
        btns = []
        if p.get("latitude") and p.get("longitude"):
            btns.append(_kakao_map_btn(p["name"], p["latitude"], p["longitude"]))
        if p.get("phone"):
            btns.append(_phone_btn(p["phone"]))
        cards.append(_basic_card(p["name"], desc, btns or None))

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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
