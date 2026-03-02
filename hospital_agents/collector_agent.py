"""
HospitalInfoCollectorAgent
병원 정보를 수집하는 에이전트

지원 소스:
  - HIRA (건강보험심사평가원) 공공 API
  - 수동 등록 (직접 dict 전달)
  - 더미 데이터 (테스트용)
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import requests

from .data_store import HospitalDataStore

logger = logging.getLogger(__name__)

# HIRA 공공 API 엔드포인트 (https://www.data.go.kr)
HIRA_API_URL = "http://apis.data.go.kr/B551182/MadmDtlInfoService2/getDgsbjtInfo2"


@dataclass
class CollectorConfig:
    """수집 에이전트 설정"""

    hira_api_key: str = ""            # 공공데이터 서비스키
    max_results: int = 100            # 한 번에 수집할 최대 건수
    timeout: int = 10                 # HTTP 타임아웃 (초)
    use_dummy_data: bool = False      # API 키 없을 때 더미 데이터 사용


# ---------------------------------------------------------------------------
# Sample dummy data (개발·테스트용)
# ---------------------------------------------------------------------------

DUMMY_HOSPITALS: list[dict] = [
    {
        "id": "H00001",
        "name": "서울대학교병원",
        "type": "상급종합병원",
        "address": "서울특별시 종로구 대학로 101",
        "phone": "02-2072-2114",
        "specialties": ["내과", "외과", "소아과", "산부인과", "신경과", "응급의학과"],
        "hours": {
            "weekday": "08:30 ~ 17:30",
            "saturday": "08:30 ~ 12:30",
            "sunday": "휴진",
            "holiday": "응급실 24시간",
        },
        "emergency": True,
        "latitude": 37.5797,
        "longitude": 126.9990,
    },
    {
        "id": "H00002",
        "name": "강남세브란스병원",
        "type": "상급종합병원",
        "address": "서울특별시 강남구 언주로 211",
        "phone": "02-2019-3114",
        "specialties": ["내과", "외과", "정형외과", "피부과", "안과"],
        "hours": {
            "weekday": "08:30 ~ 17:30",
            "saturday": "08:30 ~ 12:30",
            "sunday": "휴진",
            "holiday": "응급실 24시간",
        },
        "emergency": True,
        "latitude": 37.4881,
        "longitude": 127.0343,
    },
    {
        "id": "H00003",
        "name": "연세의원",
        "type": "의원",
        "address": "서울특별시 마포구 홍익로 10",
        "phone": "02-333-5678",
        "specialties": ["내과", "가정의학과"],
        "hours": {
            "weekday": "09:00 ~ 18:00",
            "saturday": "09:00 ~ 13:00",
            "sunday": "휴진",
            "holiday": "휴진",
        },
        "emergency": False,
        "latitude": 37.5571,
        "longitude": 126.9242,
    },
    {
        "id": "H00004",
        "name": "한강성심병원",
        "type": "종합병원",
        "address": "서울특별시 영등포구 선유로 12",
        "phone": "02-2639-5000",
        "specialties": ["내과", "외과", "신경외과", "재활의학과"],
        "hours": {
            "weekday": "08:30 ~ 17:00",
            "saturday": "08:30 ~ 12:00",
            "sunday": "휴진",
            "holiday": "응급실 24시간",
        },
        "emergency": True,
        "latitude": 37.5237,
        "longitude": 126.8963,
    },
    {
        "id": "H00005",
        "name": "이대목동병원",
        "type": "종합병원",
        "address": "서울특별시 양천구 안양천로 1071",
        "phone": "02-2650-5114",
        "specialties": ["산부인과", "소아과", "내과", "외과"],
        "hours": {
            "weekday": "08:30 ~ 17:30",
            "saturday": "08:30 ~ 12:30",
            "sunday": "휴진",
            "holiday": "응급실 24시간",
        },
        "emergency": True,
        "latitude": 37.5272,
        "longitude": 126.8699,
    },
]


class HospitalInfoCollectorAgent:
    """
    병원 정보 수집 에이전트

    역할:
    - HIRA API 또는 더미 데이터로 병원 기본 정보를 수집
    - HospitalDataStore에 저장
    - 특정 지역/진료과 기준으로 필터링 수집 가능
    """

    name = "HospitalInfoCollectorAgent"

    def __init__(self, config: CollectorConfig | None = None, store: HospitalDataStore | None = None):
        self.config = config or CollectorConfig()
        self.store = store or HospitalDataStore()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def collect(self, region: str = "", specialty: str = "") -> list[str]:
        """
        병원 정보를 수집하고 저장된 hospital_id 목록을 반환합니다.

        Args:
            region   : 지역 필터 (예: '서울', '강남구')
            specialty: 진료과 필터 (예: '내과', '소아과')
        """
        logger.info("[%s] 수집 시작 (region=%s, specialty=%s)", self.name, region, specialty)

        hospitals = (
            self._fetch_from_api(region, specialty)
            if self.config.hira_api_key and not self.config.use_dummy_data
            else self._fetch_dummy(region, specialty)
        )

        saved_ids = []
        for h in hospitals:
            hid = self.store.save_hospital(h)
            saved_ids.append(hid)
            logger.info("[%s] 저장 완료: %s (%s)", self.name, h.get("name"), hid)

        logger.info("[%s] 수집 완료 — 총 %d건", self.name, len(saved_ids))
        return saved_ids

    def register(self, hospital: dict) -> str:
        """단일 병원 정보를 직접 등록합니다."""
        hid = self.store.save_hospital(hospital)
        logger.info("[%s] 수동 등록: %s (%s)", self.name, hospital.get("name"), hid)
        return hid

    def run(self, **kwargs) -> dict[str, Any]:
        """에이전트 실행 인터페이스 (오케스트레이터 호환)"""
        ids = self.collect(**kwargs)
        return {
            "agent": self.name,
            "action": "collect",
            "saved_ids": ids,
            "count": len(ids),
            "timestamp": datetime.now().isoformat(),
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _fetch_dummy(self, region: str, specialty: str) -> list[dict]:
        """더미 데이터에서 필터링하여 반환합니다."""
        data = DUMMY_HOSPITALS
        if region:
            data = [h for h in data if region in h.get("address", "")]
        if specialty:
            data = [h for h in data if specialty in h.get("specialties", [])]
        return data

    def _fetch_from_api(self, region: str, specialty: str) -> list[dict]:
        """HIRA 공공 API에서 병원 정보를 가져옵니다."""
        params = {
            "serviceKey": self.config.hira_api_key,
            "pageNo": 1,
            "numOfRows": self.config.max_results,
            "sidoCd": "",   # 시도 코드 (추후 region 매핑)
            "sgguCd": "",   # 시군구 코드
            "dgsbjtCd": "", # 진료과목 코드
            "_type": "json",
        }

        try:
            resp = requests.get(HIRA_API_URL, params=params, timeout=self.config.timeout)
            resp.raise_for_status()
            items = resp.json().get("response", {}).get("body", {}).get("items", {}).get("item", [])
            if isinstance(items, dict):
                items = [items]
            return [self._normalize_hira(item) for item in items]
        except requests.RequestException as e:
            logger.warning("[%s] API 호출 실패, 더미 데이터로 폴백: %s", self.name, e)
            return self._fetch_dummy(region, specialty)

    @staticmethod
    def _normalize_hira(item: dict) -> dict:
        """HIRA API 응답을 내부 포맷으로 변환합니다."""
        return {
            "name": item.get("yadmNm", ""),
            "type": item.get("clCdNm", ""),
            "address": f"{item.get('sidoNm', '')} {item.get('sgguNm', '')} {item.get('emdongNm', '')}".strip(),
            "phone": item.get("telno", ""),
            "specialties": [],
            "hours": {},
            "emergency": False,
            "latitude": float(item.get("YPos", 0) or 0),
            "longitude": float(item.get("XPos", 0) or 0),
            "hira_code": item.get("ykiho", ""),
        }
