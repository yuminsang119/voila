"""
대전 병원·약국 찾기 — 웹앱 서버
브라우저 Geolocation API로 현재 위치를 받아 주변 병원·약국을 안내합니다.

실행:
  uvicorn web_app:app --host 0.0.0.0 --port 8000

접속:
  http://localhost:8000          ← PC/모바일 브라우저
  (HTTPS 필요 시 ngrok 사용)
"""

import math
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from hospital_agents.main import build_team

# ---------------------------------------------------------------------------
# 초기화
# ---------------------------------------------------------------------------

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="대전 병원·약국 웹앱")

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

team = build_team(use_dummy=True)
collector = team["collector"]
checker   = team["checker"]
store     = team["store"]

if not store.all_hospitals():
    collector.run()
    checker.run()

# ---------------------------------------------------------------------------
# 거리 계산
# ---------------------------------------------------------------------------

def _haversine(lat1, lon1, lat2, lon2) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return R * 2 * math.asin(math.sqrt(a))


def _nearby_hospitals(lat: float, lon: float, radius_km: float) -> list[dict]:
    results = []
    for h in store.all_hospitals():
        hlat = float(h.get("latitude") or 0)
        hlon = float(h.get("longitude") or 0)
        if hlat == 0 and hlon == 0:
            continue
        dist = _haversine(lat, lon, hlat, hlon)
        if dist <= radius_km:
            status = store.get_today_status(h["id"])
            results.append({
                "name":      h.get("name", ""),
                "type":      h.get("type", ""),
                "address":   h.get("address", ""),
                "phone":     h.get("phone", ""),
                "latitude":  hlat,
                "longitude": hlon,
                "emergency":   h.get("emergency", False),
                "is_open":     bool(status and status.get("is_open")),
                "hours":       status.get("hours", "") if status else "",
                "dist_km":     round(dist, 2),
                "equipment":   h.get("equipment", []),
                "specialists": h.get("specialists", {}),
            })
    return sorted(results, key=lambda x: x["dist_km"])


def _nearby_pharmacies(lat: float, lon: float, radius_km: float) -> list[dict]:
    results = []
    for p in store.all_pharmacies():
        plat = float(p.get("latitude") or 0)
        plon = float(p.get("longitude") or 0)
        if plat == 0 and plon == 0:
            continue
        dist = _haversine(lat, lon, plat, plon)
        if dist <= radius_km:
            status = store.get_today_pharmacy_status(p["id"])
            results.append({
                "name":         p.get("name", ""),
                "address":      p.get("address", ""),
                "phone":        p.get("phone", ""),
                "latitude":     plat,
                "longitude":    plon,
                "duty_pharmacy": p.get("duty_pharmacy", False),
                "is_open":      bool(status and status.get("is_open")),
                "hours":        status.get("hours", "") if status else "",
                "dist_km":      round(dist, 2),
            })
    return sorted(results, key=lambda x: x["dist_km"])

# ---------------------------------------------------------------------------
# 라우트
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def index():
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    return HTMLResponse(html)


@app.get("/api/nearby")
async def api_nearby(lat: float, lon: float, kind: str = "hospital", radius: float = 3.0):
    """
    브라우저 Geolocation에서 받은 좌표로 주변 시설 검색.

    Query params:
      lat, lon   브라우저가 전달한 좌표
      kind       'hospital' | 'pharmacy'
      radius     반경 km (기본 3.0)
    """
    radius = max(0.5, min(radius, 20.0))  # 0.5 ~ 20km 제한

    if kind == "pharmacy":
        items = _nearby_pharmacies(lat, lon, radius)
    else:
        items = _nearby_hospitals(lat, lon, radius)

    logger.info("[nearby] kind=%s lat=%.4f lon=%.4f radius=%skm → %d건", kind, lat, lon, radius, len(items))
    return JSONResponse({"kind": kind, "radius_km": radius, "count": len(items), "items": items})


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "hospitals": len(store.all_hospitals()),
        "pharmacies": len(store.all_pharmacies()),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=False)
