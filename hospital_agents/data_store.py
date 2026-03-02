"""
HospitalDataStore
JSON 파일 기반의 병원 정보 데이터 저장소
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any


DATA_DIR = Path(__file__).parent / "data"
HOSPITALS_FILE = DATA_DIR / "hospitals.json"
DAILY_STATUS_FILE = DATA_DIR / "daily_status.json"


class HospitalDataStore:
    """병원 정보 및 영업 상태를 JSON 파일로 저장/조회합니다."""

    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._ensure_files()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_files(self):
        if not HOSPITALS_FILE.exists():
            HOSPITALS_FILE.write_text(json.dumps({}, ensure_ascii=False, indent=2))
        if not DAILY_STATUS_FILE.exists():
            DAILY_STATUS_FILE.write_text(json.dumps({}, ensure_ascii=False, indent=2))

    def _read(self, path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    def _write(self, path: Path, data: dict):
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2))

    # ------------------------------------------------------------------
    # Hospital info CRUD
    # ------------------------------------------------------------------

    def save_hospital(self, hospital: dict) -> str:
        """병원 정보를 저장하고 hospital_id를 반환합니다."""
        hospitals = self._read(HOSPITALS_FILE)
        hid = hospital.get("id") or f"H{len(hospitals) + 1:05d}"
        hospital["id"] = hid
        hospital["updated_at"] = datetime.now().isoformat()
        hospitals[hid] = hospital
        self._write(HOSPITALS_FILE, hospitals)
        return hid

    def get_hospital(self, hospital_id: str) -> dict | None:
        return self._read(HOSPITALS_FILE).get(hospital_id)

    def all_hospitals(self) -> list[dict]:
        return list(self._read(HOSPITALS_FILE).values())

    def search_hospitals(self, keyword: str) -> list[dict]:
        """이름, 주소, 진료과목으로 병원을 검색합니다."""
        keyword = keyword.lower()
        results = []
        for h in self.all_hospitals():
            searchable = " ".join(
                [
                    h.get("name", ""),
                    h.get("address", ""),
                    " ".join(h.get("specialties", [])),
                    h.get("type", ""),
                ]
            ).lower()
            if keyword in searchable:
                results.append(h)
        return results

    # ------------------------------------------------------------------
    # Daily status CRUD
    # ------------------------------------------------------------------

    def save_daily_status(self, hospital_id: str, date: str, status: dict):
        """특정 날짜의 영업 상태를 저장합니다. date: 'YYYY-MM-DD'"""
        all_status = self._read(DAILY_STATUS_FILE)
        all_status.setdefault(hospital_id, {})[date] = {
            **status,
            "checked_at": datetime.now().isoformat(),
        }
        self._write(DAILY_STATUS_FILE, all_status)

    def get_daily_status(self, hospital_id: str, date: str) -> dict | None:
        return self._read(DAILY_STATUS_FILE).get(hospital_id, {}).get(date)

    def get_today_status(self, hospital_id: str) -> dict | None:
        today = datetime.now().strftime("%Y-%m-%d")
        return self.get_daily_status(hospital_id, today)

    def all_today_statuses(self) -> dict[str, dict]:
        today = datetime.now().strftime("%Y-%m-%d")
        all_status = self._read(DAILY_STATUS_FILE)
        return {
            hid: statuses[today]
            for hid, statuses in all_status.items()
            if today in statuses
        }
