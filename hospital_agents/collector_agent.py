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
# 약국 정보 API
PHARM_API_URL = "http://apis.data.go.kr/B551182/pharmacyInfoServicev2/getPharmBasisList"


@dataclass
class CollectorConfig:
    """수집 에이전트 설정"""

    hira_api_key: str = ""            # 공공데이터 서비스키
    max_results: int = 100            # 한 번에 수집할 최대 건수
    timeout: int = 10                 # HTTP 타임아웃 (초)
    use_dummy_data: bool = False      # API 키 없을 때 더미 데이터 사용
    default_region: str = "대전"      # 기본 수집 지역


# ---------------------------------------------------------------------------
# Sample dummy data (개발·테스트용)
# ---------------------------------------------------------------------------

DUMMY_HOSPITALS: list[dict] = [
    # ── 서울 ────────────────────────────────────────────────────
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
        "equipment": ["CT", "MRI", "PET-CT", "X-ray", "초음파", "내시경", "심혈관조영술"],
        "specialists": {"내과": 45, "외과": 30, "소아과": 15, "산부인과": 12, "신경과": 18, "응급의학과": 10},
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
        "equipment": ["CT", "MRI", "PET-CT", "X-ray", "초음파", "내시경", "맘모그래피"],
        "specialists": {"내과": 38, "외과": 25, "정형외과": 20, "피부과": 8, "안과": 12},
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
        "equipment": ["X-ray", "초음파", "심전도"],
        "specialists": {"내과": 1, "가정의학과": 1},
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
        "equipment": ["CT", "MRI", "X-ray", "초음파", "내시경"],
        "specialists": {"내과": 12, "외과": 8, "신경외과": 5, "재활의학과": 6},
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
        "equipment": ["CT", "MRI", "X-ray", "초음파", "내시경", "맘모그래피"],
        "specialists": {"산부인과": 10, "소아과": 8, "내과": 15, "외과": 10},
    },
    # ── 대전 ────────────────────────────────────────────────────
    {
        "id": "H00101",
        "name": "충남대학교병원",
        "type": "상급종합병원",
        "address": "대전광역시 중구 문화로 282",
        "phone": "042-280-7114",
        "specialties": ["내과", "외과", "소아과", "산부인과", "신경과", "응급의학과", "정형외과", "재활의학과"],
        "hours": {
            "weekday": "08:30 ~ 17:30",
            "saturday": "08:30 ~ 12:00",
            "sunday": "휴진",
            "holiday": "응급실 24시간",
        },
        "emergency": True,
        "latitude": 36.3219,
        "longitude": 127.4089,
        "equipment": ["CT", "MRI", "PET-CT", "X-ray", "초음파", "내시경", "심혈관조영술", "방사선치료기"],
        "specialists": {"내과": 30, "외과": 20, "소아과": 12, "산부인과": 10, "신경과": 14, "응급의학과": 8, "정형외과": 15, "재활의학과": 8},
    },
    {
        "id": "H00102",
        "name": "건양대학교병원",
        "type": "상급종합병원",
        "address": "대전광역시 서구 관저동로 158",
        "phone": "042-600-9114",
        "specialties": ["내과", "외과", "소아과", "안과", "피부과", "응급의학과"],
        "hours": {
            "weekday": "08:30 ~ 17:30",
            "saturday": "08:30 ~ 12:30",
            "sunday": "휴진",
            "holiday": "응급실 24시간",
        },
        "emergency": True,
        "latitude": 36.3028,
        "longitude": 127.3613,
        "equipment": ["CT", "MRI", "PET-CT", "X-ray", "초음파", "내시경", "안과정밀장비"],
        "specialists": {"내과": 22, "외과": 15, "소아과": 8, "안과": 10, "피부과": 6, "응급의학과": 7},
    },
    {
        "id": "H00103",
        "name": "대전성모병원",
        "type": "종합병원",
        "address": "대전광역시 중구 대흥로 64-31",
        "phone": "042-220-9114",
        "specialties": ["내과", "외과", "산부인과", "소아과", "정형외과"],
        "hours": {
            "weekday": "08:30 ~ 17:00",
            "saturday": "08:30 ~ 12:00",
            "sunday": "휴진",
            "holiday": "응급실 24시간",
        },
        "emergency": True,
        "latitude": 36.3259,
        "longitude": 127.4268,
        "equipment": ["CT", "MRI", "X-ray", "초음파", "내시경", "맘모그래피"],
        "specialists": {"내과": 18, "외과": 12, "산부인과": 8, "소아과": 6, "정형외과": 10},
    },
    {
        "id": "H00104",
        "name": "대전을지대학교병원",
        "type": "종합병원",
        "address": "대전광역시 서구 둔산서로 95",
        "phone": "042-611-3000",
        "specialties": ["내과", "외과", "신경과", "재활의학과", "응급의학과"],
        "hours": {
            "weekday": "08:30 ~ 17:30",
            "saturday": "08:30 ~ 12:30",
            "sunday": "휴진",
            "holiday": "응급실 24시간",
        },
        "emergency": True,
        "latitude": 36.3505,
        "longitude": 127.3867,
        "equipment": ["CT", "MRI", "X-ray", "초음파", "내시경", "심혈관조영술"],
        "specialists": {"내과": 20, "외과": 14, "신경과": 10, "재활의학과": 8, "응급의학과": 7},
    },
    {
        "id": "H00105",
        "name": "대전선병원",
        "type": "종합병원",
        "address": "대전광역시 중구 목중로 29",
        "phone": "042-220-8114",
        "specialties": ["내과", "외과", "정형외과", "재활의학과"],
        "hours": {
            "weekday": "08:30 ~ 17:00",
            "saturday": "08:30 ~ 12:00",
            "sunday": "휴진",
            "holiday": "응급실 24시간",
        },
        "emergency": True,
        "latitude": 36.3275,
        "longitude": 127.4219,
        "equipment": ["CT", "MRI", "X-ray", "초음파", "내시경"],
        "specialists": {"내과": 15, "외과": 10, "정형외과": 12, "재활의학과": 7},
    },
    {
        "id": "H00106",
        "name": "유성선병원",
        "type": "종합병원",
        "address": "대전광역시 유성구 북유성대로 93",
        "phone": "042-607-9999",
        "specialties": ["내과", "외과", "소아과", "신경과"],
        "hours": {
            "weekday": "08:30 ~ 17:30",
            "saturday": "08:30 ~ 13:00",
            "sunday": "휴진",
            "holiday": "응급실 24시간",
        },
        "emergency": True,
        "latitude": 36.3825,
        "longitude": 127.3385,
        "equipment": ["CT", "MRI", "X-ray", "초음파", "내시경"],
        "specialists": {"내과": 12, "외과": 8, "소아과": 5, "신경과": 7},
    },
    {
        "id": "H00107",
        "name": "한국한의원 (대전)",
        "type": "한의원",
        "address": "대전광역시 중구 중앙로 76",
        "phone": "042-255-1234",
        "specialties": ["한방내과", "침구과", "재활의학과"],
        "hours": {
            "weekday": "09:00 ~ 18:30",
            "saturday": "09:00 ~ 13:00",
            "sunday": "휴진",
            "holiday": "휴진",
        },
        "emergency": False,
        "latitude": 36.3272,
        "longitude": 127.4276,
        "equipment": ["한방초음파", "경락기능검사기", "적외선체열진단기"],
        "specialists": {"한방내과": 2, "침구과": 3, "재활의학과": 1},
    },
    {
        "id": "H00108",
        "name": "대전둔산내과의원",
        "type": "의원",
        "address": "대전광역시 서구 둔산로 131",
        "phone": "042-483-5000",
        "specialties": ["내과", "가정의학과"],
        "hours": {
            "weekday": "09:00 ~ 18:00",
            "saturday": "09:00 ~ 13:00",
            "sunday": "휴진",
            "holiday": "휴진",
        },
        "emergency": False,
        "latitude": 36.3534,
        "longitude": 127.3842,
        "equipment": ["X-ray", "초음파", "심전도", "혈액검사기"],
        "specialists": {"내과": 2, "가정의학과": 1},
    },
]


# ---------------------------------------------------------------------------
# 약국 더미 데이터 (대전 관내)
# ---------------------------------------------------------------------------

DUMMY_PHARMACIES: list[dict] = [
    {
        "id": "P00001",
        "name": "충남대학교병원 원외약국",
        "type": "약국",
        "address": "대전광역시 중구 문화로 282",
        "phone": "042-280-8501",
        "handled_items": ["전문의약품", "일반의약품"],
        "hours": {
            "weekday": "09:00 ~ 18:00",
            "saturday": "09:00 ~ 13:00",
            "sunday": "휴진",
            "holiday": "휴진",
        },
        "duty_pharmacy": False,
        "latitude": 36.3221,
        "longitude": 127.4091,
    },
    {
        "id": "P00002",
        "name": "건양대병원약국",
        "type": "약국",
        "address": "대전광역시 서구 관저동로 158",
        "phone": "042-600-0123",
        "handled_items": ["전문의약품", "일반의약품"],
        "hours": {
            "weekday": "09:00 ~ 18:00",
            "saturday": "09:00 ~ 13:00",
            "sunday": "휴진",
            "holiday": "휴진",
        },
        "duty_pharmacy": False,
        "latitude": 36.3030,
        "longitude": 127.3615,
    },
    {
        "id": "P00003",
        "name": "둔산중앙약국",
        "type": "약국",
        "address": "대전광역시 서구 둔산중로 97",
        "phone": "042-472-0001",
        "handled_items": ["전문의약품", "일반의약품", "한약재"],
        "hours": {
            "weekday": "09:00 ~ 21:00",
            "saturday": "09:00 ~ 18:00",
            "sunday": "10:00 ~ 16:00",
            "holiday": "휴진",
        },
        "duty_pharmacy": True,
        "latitude": 36.3510,
        "longitude": 127.3848,
    },
    {
        "id": "P00004",
        "name": "대전역전약국",
        "type": "약국",
        "address": "대전광역시 동구 중앙로 215",
        "phone": "042-252-3456",
        "handled_items": ["일반의약품", "건강기능식품"],
        "hours": {
            "weekday": "08:30 ~ 20:00",
            "saturday": "09:00 ~ 17:00",
            "sunday": "휴진",
            "holiday": "휴진",
        },
        "duty_pharmacy": False,
        "latitude": 36.3318,
        "longitude": 127.4347,
    },
    {
        "id": "P00005",
        "name": "유성온천약국",
        "type": "약국",
        "address": "대전광역시 유성구 유성대로 665",
        "phone": "042-823-7890",
        "handled_items": ["전문의약품", "일반의약품"],
        "hours": {
            "weekday": "09:00 ~ 19:30",
            "saturday": "09:00 ~ 15:00",
            "sunday": "휴진",
            "holiday": "휴진",
        },
        "duty_pharmacy": False,
        "latitude": 36.3650,
        "longitude": 127.3410,
    },
    {
        "id": "P00006",
        "name": "서구중앙약국",
        "type": "약국",
        "address": "대전광역시 서구 갈마중로 10",
        "phone": "042-526-1122",
        "handled_items": ["전문의약품", "일반의약품", "의료용품"],
        "hours": {
            "weekday": "09:00 ~ 20:00",
            "saturday": "09:00 ~ 17:00",
            "sunday": "10:00 ~ 14:00",
            "holiday": "휴진",
        },
        "duty_pharmacy": True,
        "latitude": 36.3492,
        "longitude": 127.3786,
    },
    {
        "id": "P00007",
        "name": "대덕약국",
        "type": "약국",
        "address": "대전광역시 대덕구 대덕대로 1400",
        "phone": "042-636-5500",
        "handled_items": ["일반의약품", "건강기능식품"],
        "hours": {
            "weekday": "09:00 ~ 18:00",
            "saturday": "09:00 ~ 13:00",
            "sunday": "휴진",
            "holiday": "휴진",
        },
        "duty_pharmacy": False,
        "latitude": 36.3482,
        "longitude": 127.4153,
    },
    {
        "id": "P00008",
        "name": "24시 행복약국",
        "type": "약국",
        "address": "대전광역시 중구 대종로 480",
        "phone": "042-254-2424",
        "handled_items": ["전문의약품", "일반의약품", "의료용품"],
        "hours": {
            "weekday": "00:00 ~ 24:00",
            "saturday": "00:00 ~ 24:00",
            "sunday": "00:00 ~ 24:00",
            "holiday": "00:00 ~ 24:00",
        },
        "duty_pharmacy": True,
        "latitude": 36.3298,
        "longitude": 127.4260,
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

    def collect_pharmacies(self, region: str = "", keyword: str = "") -> list[str]:
        """
        약국 정보를 수집하고 저장된 pharmacy_id 목록을 반환합니다.

        Args:
            region  : 지역 필터 (예: '대전', '서구')
            keyword : 이름·취급품목 필터
        """
        region = region or self.config.default_region
        logger.info("[%s] 약국 수집 시작 (region=%s, keyword=%s)", self.name, region, keyword)

        pharmacies = (
            self._fetch_pharmacies_from_api(region)
            if self.config.hira_api_key and not self.config.use_dummy_data
            else self._fetch_dummy_pharmacies(region, keyword)
        )

        saved_ids = []
        for p in pharmacies:
            pid = self.store.save_pharmacy(p)
            saved_ids.append(pid)
            logger.info("[%s] 약국 저장: %s (%s)", self.name, p.get("name"), pid)

        logger.info("[%s] 약국 수집 완료 — 총 %d건", self.name, len(saved_ids))
        return saved_ids

    def register_pharmacy(self, pharmacy: dict) -> str:
        """단일 약국 정보를 직접 등록합니다."""
        pid = self.store.save_pharmacy(pharmacy)
        logger.info("[%s] 약국 수동 등록: %s (%s)", self.name, pharmacy.get("name"), pid)
        return pid

    def run(self, **kwargs) -> dict[str, Any]:
        """에이전트 실행 인터페이스 — 병원 + 약국 동시 수집."""
        region = kwargs.pop("region", self.config.default_region)
        hosp_ids = self.collect(region=region, **kwargs)
        pharm_ids = self.collect_pharmacies(region=region)
        return {
            "agent": self.name,
            "action": "collect",
            "saved_ids": hosp_ids,
            "count": len(hosp_ids),
            "pharmacy_ids": pharm_ids,
            "pharmacy_count": len(pharm_ids),
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

    def _fetch_dummy_pharmacies(self, region: str, keyword: str) -> list[dict]:
        """약국 더미 데이터에서 필터링하여 반환합니다."""
        data = DUMMY_PHARMACIES
        if region:
            data = [p for p in data if region in p.get("address", "")]
        if keyword:
            data = [p for p in data if keyword in p.get("name", "") or
                    any(keyword in item for item in p.get("handled_items", []))]
        return data

    def _fetch_pharmacies_from_api(self, region: str) -> list[dict]:
        """HIRA 약국 정보 API에서 데이터를 가져옵니다."""
        # 시도 코드 매핑 (대전: 30)
        sido_map = {"대전": "30", "서울": "11", "부산": "21", "인천": "22",
                    "광주": "23", "대구": "27", "울산": "31"}
        sido_cd = sido_map.get(region, "30")

        params = {
            "serviceKey": self.config.hira_api_key,
            "pageNo": 1,
            "numOfRows": self.config.max_results,
            "sidoCd": sido_cd,
            "_type": "json",
        }
        try:
            resp = requests.get(PHARM_API_URL, params=params, timeout=self.config.timeout)
            resp.raise_for_status()
            items = resp.json().get("response", {}).get("body", {}).get("items", {}).get("item", [])
            if isinstance(items, dict):
                items = [items]
            return [self._normalize_pharm(item) for item in items]
        except requests.RequestException as e:
            logger.warning("[%s] 약국 API 호출 실패, 더미 데이터로 폴백: %s", self.name, e)
            return self._fetch_dummy_pharmacies(region, "")

    @staticmethod
    def _normalize_pharm(item: dict) -> dict:
        """HIRA 약국 API 응답을 내부 포맷으로 변환합니다."""
        return {
            "name": item.get("yadmNm", ""),
            "type": "약국",
            "address": f"{item.get('sidoNm', '')} {item.get('sgguNm', '')} {item.get('emdongNm', '')}".strip(),
            "phone": item.get("telno", ""),
            "handled_items": ["전문의약품", "일반의약품"],
            "hours": {},
            "duty_pharmacy": False,
            "latitude": float(item.get("YPos", 0) or 0),
            "longitude": float(item.get("XPos", 0) or 0),
            "hira_code": item.get("ykiho", ""),
        }

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
            "equipment": [],
            "specialists": {},
        }
