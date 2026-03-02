"""
DailyBusinessCheckerAgent
매일 병원 영업 상태를 체크하는 에이전트

체크 항목:
  - 오늘 날짜의 요일 (평일/토요일/일요일/공휴일)
  - 공휴일 여부 (한국 공휴일 API 또는 내장 달력)
  - 병원별 영업 여부 및 영업 시간
  - 비상 진료 여부
"""

import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import requests

from .data_store import HospitalDataStore

logger = logging.getLogger(__name__)

# 공공데이터 포털 공휴일 API
HOLIDAY_API_URL = "http://apis.data.go.kr/B090041/openapi/service/SpcdeInfoService/getRestDeInfo"

# 대체공휴일을 포함한 한국 고정 공휴일 (MM-DD)
FIXED_HOLIDAYS: set[str] = {
    "01-01",  # 신정
    "03-01",  # 삼일절
    "05-05",  # 어린이날
    "06-06",  # 현충일
    "08-15",  # 광복절
    "10-03",  # 개천절
    "10-09",  # 한글날
    "12-25",  # 크리스마스
}


@dataclass
class CheckerConfig:
    """체커 에이전트 설정"""

    holiday_api_key: str = ""   # 공공데이터 공휴일 서비스키 (없으면 내장 달력 사용)
    timeout: int = 10


class DailyBusinessCheckerAgent:
    """
    매일 병원 영업 정보를 체크하는 에이전트

    역할:
    - 오늘 날짜의 요일·공휴일 여부 판단
    - 저장된 모든 병원의 오늘 영업 상태 계산
    - HospitalDataStore에 daily_status 저장
    """

    name = "DailyBusinessCheckerAgent"

    def __init__(self, config: CheckerConfig | None = None, store: HospitalDataStore | None = None):
        self.config = config or CheckerConfig()
        self.store = store or HospitalDataStore()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check_all(self, target_date: date | None = None) -> dict[str, dict]:
        """
        모든 병원의 영업 상태를 체크하고 저장합니다.

        Returns:
            {hospital_id: status_dict} 형태의 결과
        """
        target = target_date or date.today()
        date_str = target.strftime("%Y-%m-%d")
        day_type = self._get_day_type(target)

        logger.info("[%s] 영업 체크 날짜: %s (%s)", self.name, date_str, day_type)

        results: dict[str, dict] = {}
        for hospital in self.store.all_hospitals():
            hid = hospital["id"]
            status = self._compute_status(hospital, day_type)
            self.store.save_daily_status(hid, date_str, status)
            results[hid] = status
            logger.info(
                "[%s] %s → %s (%s)",
                self.name,
                hospital.get("name"),
                "영업" if status["is_open"] else "휴진",
                status.get("hours", ""),
            )

        logger.info("[%s] 체크 완료 — 총 %d건", self.name, len(results))
        return results

    def check_one(self, hospital_id: str, target_date: date | None = None) -> dict | None:
        """단일 병원의 영업 상태를 체크합니다."""
        hospital = self.store.get_hospital(hospital_id)
        if not hospital:
            logger.warning("[%s] 병원 없음: %s", self.name, hospital_id)
            return None

        target = target_date or date.today()
        date_str = target.strftime("%Y-%m-%d")
        day_type = self._get_day_type(target)
        status = self._compute_status(hospital, day_type)
        self.store.save_daily_status(hospital_id, date_str, status)
        return status

    def run(self, **kwargs) -> dict[str, Any]:
        """에이전트 실행 인터페이스 (오케스트레이터 호환)"""
        results = self.check_all(**kwargs)
        open_count = sum(1 for s in results.values() if s.get("is_open"))
        return {
            "agent": self.name,
            "action": "check_all",
            "date": date.today().isoformat(),
            "total": len(results),
            "open": open_count,
            "closed": len(results) - open_count,
            "timestamp": datetime.now().isoformat(),
        }

    # ------------------------------------------------------------------
    # Status computation
    # ------------------------------------------------------------------

    def _compute_status(self, hospital: dict, day_type: str) -> dict:
        """
        병원 정보와 요일 타입으로 영업 상태를 계산합니다.

        day_type: 'weekday' | 'saturday' | 'sunday' | 'holiday'
        """
        hours_info = hospital.get("hours", {})
        raw_hours = hours_info.get(day_type, "휴진")

        is_open = raw_hours not in ("휴진", "", None)
        emergency = hospital.get("emergency", False)

        # 공휴일이라도 응급실은 운영
        if not is_open and emergency and day_type in ("sunday", "holiday"):
            is_open = True
            raw_hours = hours_info.get("holiday", "응급실 24시간")

        return {
            "hospital_id": hospital["id"],
            "hospital_name": hospital.get("name", ""),
            "day_type": day_type,
            "is_open": is_open,
            "hours": raw_hours,
            "emergency": emergency,
            "phone": hospital.get("phone", ""),
        }

    # ------------------------------------------------------------------
    # Date/holiday helpers
    # ------------------------------------------------------------------

    def _get_day_type(self, target: date) -> str:
        """날짜를 'weekday' | 'saturday' | 'sunday' | 'holiday' 중 하나로 반환합니다."""
        if self._is_holiday(target):
            return "holiday"
        weekday = target.weekday()  # 0=월 … 5=토, 6=일
        if weekday == 5:
            return "saturday"
        if weekday == 6:
            return "sunday"
        return "weekday"

    def _is_holiday(self, target: date) -> bool:
        """공휴일 여부를 판단합니다 (API → 내장 달력 폴백)."""
        if self.config.holiday_api_key:
            try:
                return self._check_holiday_api(target)
            except Exception as e:
                logger.warning("[%s] 공휴일 API 실패, 내장 달력 사용: %s", self.name, e)
        return target.strftime("%m-%d") in FIXED_HOLIDAYS

    def _check_holiday_api(self, target: date) -> bool:
        """공공데이터 포털 공휴일 API로 확인합니다."""
        params = {
            "serviceKey": self.config.holiday_api_key,
            "solYear": target.year,
            "solMonth": f"{target.month:02d}",
            "_type": "json",
        }
        resp = requests.get(HOLIDAY_API_URL, params=params, timeout=self.config.timeout)
        resp.raise_for_status()
        items = resp.json().get("response", {}).get("body", {}).get("items", {})
        if not items:
            return False
        holiday_list = items.get("item", [])
        if isinstance(holiday_list, dict):
            holiday_list = [holiday_list]
        holiday_dates = {str(h.get("locdate", "")) for h in holiday_list}
        return target.strftime("%Y%m%d") in holiday_dates
