"""
RocheBot (로체 봇)
수집된 병원 정보와 매일 업데이트된 영업 상태를 바탕으로 사용자 질문에 답변하는 챗봇

지원 채널:
  - 텍스트 (CLI / REST API)
  - 음성 (Voila 통합)
"""

import logging
import re
from datetime import datetime
from typing import Any

from .data_store import HospitalDataStore

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Intent patterns (간단한 규칙 기반 NLU)
# ---------------------------------------------------------------------------

INTENTS: list[dict] = [
    {
        "name": "check_open",
        "patterns": [
            r"(오늘|지금|현재).*(열|영업|진료|운영)",
            r"(영업|진료|운영).*(하|해|중|시간|여부)",
            r"문\s*(열|닫|여|닫)",
            r"몇\s*시.*까지",
            r"지금\s*진료",
        ],
    },
    {
        "name": "find_pharmacy",
        "patterns": [
            r"약국.*(찾|검색|추천|알려|어디|목록|리스트)",
            r"(근처|주변|가까운).*약국",
            r"약\s*(타러|사러|구하러)",
            r"처방전.*약국",
            r"당번\s*약국",
        ],
    },
    {
        "name": "find_hospital",
        "patterns": [
            r"(병원|의원|클리닉).*(찾|검색|추천|알려)",
            r"(근처|주변|가까운).*(병원|의원)",
            r"어디.*병원",
            r"(내과|외과|소아과|산부인과|정형외과|피부과|안과|치과|한의원).*병원",
        ],
    },
    {
        "name": "hospital_info",
        "patterns": [
            r"(전화|번호|연락처)",
            r"(주소|위치|어디)",
            r"(진료과|전문)",
            r"병원\s*(정보|안내)",
        ],
    },
    {
        "name": "emergency",
        "patterns": [
            r"응급",
            r"야간\s*(진료|병원)",
            r"24\s*시간",
            r"지금\s*(당장|빨리).*병원",
        ],
    },
    {
        "name": "list_hospitals",
        "patterns": [
            r"병원\s*(목록|리스트|전체|다|모두)",
            r"어떤\s*병원",
            r"등록된\s*병원",
        ],
    },
    {
        "name": "find_by_equipment",
        "patterns": [
            r"(MRI|CT|PET|후두내시경|초음파|내시경|맘모그래피|X-ray|엑스레이|방사선|심혈관조영|체열진단).*(있는|가능|검사|되는)",
            r"(의료|검사)\s*(장비|기기)",
            r"장비\s*(보유|있는|검색)",
        ],
    },
    {
        "name": "find_by_specialist",
        "patterns": [
            r"전문의\s*(있는|몇\s*명|수|검색)",
            r"(내과|외과|정형외과|소아과|산부인과|피부과|안과|신경과|이비인후과|재활의학과|응급의학과|가정의학과).*(전문의|의사|몇\s*명)",
            r"전문의\s*(내과|외과|정형외과|소아과)",
        ],
    },
]


class RocheBot:
    """
    로체 봇 — 병원 정보 챗봇

    역할:
    - 사용자 자연어 질의를 파싱하여 의도(intent) 파악
    - HospitalDataStore에서 병원 정보 및 영업 상태 조회
    - 텍스트 답변 생성
    - Voila 음성 모델 연동 (선택)
    """

    name = "RocheBot"

    def __init__(self, store: HospitalDataStore | None = None, voila_model=None):
        self.store = store or HospitalDataStore()
        self.voila_model = voila_model  # Voila 음성 모델 (선택적 연동)
        self._conversation: list[dict] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def chat(self, user_input: str) -> str:
        """
        사용자 입력을 받아 텍스트 답변을 반환합니다.

        Args:
            user_input: 사용자 질문 (한국어)

        Returns:
            답변 문자열
        """
        user_input = user_input.strip()
        if not user_input:
            return "안녕하세요! 로체 봇입니다. 병원 정보나 영업 시간을 물어보세요."

        self._conversation.append({"role": "user", "content": user_input, "ts": datetime.now().isoformat()})

        intent, entities = self._parse(user_input)
        response = self._dispatch(intent, entities, user_input)

        self._conversation.append({"role": "bot", "content": response, "ts": datetime.now().isoformat()})
        logger.info("[%s] 사용자: %s | 의도: %s | 응답 길이: %d", self.name, user_input[:30], intent, len(response))
        return response

    def reset(self):
        """대화 기록을 초기화합니다."""
        self._conversation = []

    def run(self, user_input: str = "", **kwargs) -> dict[str, Any]:
        """에이전트 실행 인터페이스 (오케스트레이터 호환)"""
        response = self.chat(user_input)
        return {
            "agent": self.name,
            "action": "chat",
            "input": user_input,
            "response": response,
            "timestamp": datetime.now().isoformat(),
        }

    # ------------------------------------------------------------------
    # NLU
    # ------------------------------------------------------------------

    def _parse(self, text: str) -> tuple[str, dict]:
        """의도와 개체를 추출합니다."""
        intent = "unknown"
        for item in INTENTS:
            if any(re.search(p, text) for p in item["patterns"]):
                intent = item["name"]
                break

        entities: dict = {}

        # 병원 이름 추출 (저장된 병원 이름과 매칭)
        for h in self.store.all_hospitals():
            name = h.get("name", "")
            if name and name in text:
                entities["hospital_name"] = name
                entities["hospital_id"] = h["id"]
                break

        # 약국 이름 추출
        if "약국" in text:
            for p in self.store.all_pharmacies():
                pname = p.get("name", "")
                if pname and pname in text:
                    entities["pharmacy_name"] = pname
                    entities["pharmacy_id"] = p["id"]
                    break

        # 장비 추출
        equip_keywords = ["MRI", "CT", "PET-CT", "후두내시경", "초음파", "내시경", "맘모그래피", "X-ray", "엑스레이", "심혈관조영술", "방사선치료기", "체열진단기"]
        for eq in equip_keywords:
            if eq in text or eq.replace("-", "") in text:
                entities["equipment"] = eq
                break

        # 진료과 추출
        specialties = ["내과", "외과", "소아과", "산부인과", "정형외과", "피부과", "안과", "신경과", "이비인후과", "재활의학과", "응급의학과", "가정의학과"]
        for sp in specialties:
            if sp in text:
                entities["specialty"] = sp
                break

        # 지역 추출
        regions = ["대전", "서울", "부산", "인천", "광주", "대구", "울산", "서구", "중구", "동구", "유성구", "대덕구"]
        for region in regions:
            if region in text:
                entities["region"] = region
                break

        return intent, entities

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def _dispatch(self, intent: str, entities: dict, raw: str) -> str:
        handler = {
            "check_open": self._handle_check_open,
            "find_pharmacy": self._handle_find_pharmacy,
            "find_hospital": self._handle_find_hospital,
            "hospital_info": self._handle_hospital_info,
            "emergency": self._handle_emergency,
            "list_hospitals": self._handle_list_hospitals,
            "find_by_equipment": self._handle_find_by_equipment,
            "find_by_specialist": self._handle_find_by_specialist,
            "unknown": self._handle_unknown,
        }.get(intent, self._handle_unknown)
        return handler(entities, raw)

    # ------------------------------------------------------------------
    # Response handlers
    # ------------------------------------------------------------------

    def _handle_check_open(self, entities: dict, raw: str) -> str:
        hospital_id = entities.get("hospital_id")
        if hospital_id:
            hospital = self.store.get_hospital(hospital_id)
            status = self.store.get_today_status(hospital_id)
            name = hospital.get("name") if hospital else hospital_id

            if not status:
                return f"'{name}'의 오늘 영업 정보가 아직 업데이트되지 않았습니다. 잠시 후 다시 확인해 주세요."

            if status["is_open"]:
                return (
                    f"✅ {name}은 오늘 영업 중입니다.\n"
                    f"📅 운영 시간: {status['hours']}\n"
                    f"📞 전화: {status['phone']}"
                )
            else:
                msg = f"❌ {name}은 오늘 휴진입니다."
                if status.get("emergency"):
                    msg += "\n🚨 단, 응급실은 24시간 운영합니다."
                return msg

        # 특정 병원 없으면 오늘 영업 중인 병원 목록
        today_statuses = self.store.all_today_statuses()
        if not today_statuses:
            return "오늘 영업 정보가 아직 업데이트되지 않았습니다. 잠시 후 다시 확인해 주세요."

        open_hospitals = [s for s in today_statuses.values() if s.get("is_open")]
        if not open_hospitals:
            return "오늘은 영업 중인 병원이 없거나 아직 정보가 업데이트되지 않았습니다."

        lines = ["오늘 영업 중인 병원 목록입니다:\n"]
        for s in open_hospitals:
            lines.append(f"🏥 {s['hospital_name']} — {s['hours']} (☎ {s['phone']})")
        return "\n".join(lines)

    def _handle_find_pharmacy(self, entities: dict, raw: str) -> str:
        region = entities.get("region", "")
        duty_only = "당번" in raw

        pharmacies = self.store.all_pharmacies()
        if region:
            pharmacies = [p for p in pharmacies if region in p.get("address", "")]
        if duty_only:
            pharmacies = [p for p in pharmacies if p.get("duty_pharmacy")]

        if not pharmacies:
            return "조건에 맞는 약국을 찾지 못했습니다."

        tag = "당번약국" if duty_only else ("약국" if not region else f"{region} 약국")
        lines = [f"💊 {tag} {len(pharmacies)}개:\n"]
        for p in pharmacies[:6]:
            status = self.store.get_today_pharmacy_status(p["id"])
            open_str = "영업중" if (status and status.get("is_open")) else "영업 미확인"
            duty_str = " 🌙당번" if p.get("duty_pharmacy") else ""
            lines.append(
                f"💊 {p['name']}{duty_str}\n"
                f"   📍 {p.get('address', '')}\n"
                f"   📞 {p.get('phone', '')}\n"
                f"   🔖 {open_str}"
            )
        if len(pharmacies) > 6:
            lines.append(f"\n... 외 {len(pharmacies)-6}건 더 있습니다.")
        return "\n".join(lines)

    def _handle_find_hospital(self, entities: dict, raw: str) -> str:
        specialty = entities.get("specialty", "")
        results = self.store.search_hospitals(specialty or raw)

        if not results:
            keyword = specialty or raw[:10]
            return f"'{keyword}'에 해당하는 병원을 찾지 못했습니다. 다른 키워드로 검색해 보세요."

        lines = [f"'{specialty or '검색'}' 관련 병원 {len(results)}개를 찾았습니다:\n"]
        for h in results[:5]:
            today_status = self.store.get_today_status(h["id"])
            open_str = "영업중" if (today_status and today_status.get("is_open")) else "상태 미확인"
            lines.append(
                f"🏥 {h['name']} ({h.get('type', '')})\n"
                f"   📍 {h.get('address', '')}\n"
                f"   📞 {h.get('phone', '')}\n"
                f"   🔖 {open_str}"
            )
        if len(results) > 5:
            lines.append(f"\n... 외 {len(results)-5}건 더 있습니다.")
        return "\n".join(lines)

    def _handle_hospital_info(self, entities: dict, raw: str) -> str:
        hospital_id = entities.get("hospital_id")
        if not hospital_id:
            return "어떤 병원의 정보가 궁금하신가요? 병원 이름을 함께 말씀해 주세요."

        h = self.store.get_hospital(hospital_id)
        if not h:
            return "해당 병원 정보를 찾을 수 없습니다."

        hours = h.get("hours", {})
        hours_str = "\n".join(f"   {k}: {v}" for k, v in hours.items()) if hours else "   정보 없음"
        specialties_str = ", ".join(h.get("specialties", [])) or "정보 없음"
        equipment_str = ", ".join(h.get("equipment", [])) or "정보 없음"
        specialists = h.get("specialists", {})
        specialists_str = ", ".join(f"{sp} {cnt}명" for sp, cnt in specialists.items()) or "정보 없음"

        return (
            f"🏥 {h.get('name')} ({h.get('type', '')})\n"
            f"📍 주소: {h.get('address', '정보 없음')}\n"
            f"📞 전화: {h.get('phone', '정보 없음')}\n"
            f"🔬 진료과: {specialties_str}\n"
            f"👨‍⚕️ 전문의: {specialists_str}\n"
            f"🩻 보유 장비: {equipment_str}\n"
            f"🕐 진료 시간:\n{hours_str}\n"
            f"🚨 응급실: {'있음' if h.get('emergency') else '없음'}"
        )

    def _handle_emergency(self, entities: dict, raw: str) -> str:
        emergency_hospitals = [h for h in self.store.all_hospitals() if h.get("emergency")]
        if not emergency_hospitals:
            return "응급실 운영 병원 정보가 없습니다. 119에 연락하시거나 가까운 종합병원을 방문해 주세요."

        lines = ["🚨 응급실 운영 병원 목록 (24시간):\n"]
        for h in emergency_hospitals:
            lines.append(f"🏥 {h['name']} — ☎ {h.get('phone', '전화 미등록')}\n   📍 {h.get('address', '')}")
        lines.append("\n⚠️  응급 상황 시 119로 먼저 연락하세요.")
        return "\n".join(lines)

    def _handle_list_hospitals(self, entities: dict, raw: str) -> str:
        hospitals = self.store.all_hospitals()
        if not hospitals:
            return "등록된 병원이 없습니다. 먼저 병원 정보를 수집해 주세요."

        lines = [f"등록된 병원 총 {len(hospitals)}개:\n"]
        for h in hospitals[:10]:
            lines.append(f"• {h['name']} ({h.get('type', '')}) — {h.get('address', '')[:20]}")
        if len(hospitals) > 10:
            lines.append(f"... 외 {len(hospitals)-10}개")
        return "\n".join(lines)

    def _handle_find_by_equipment(self, entities: dict, raw: str) -> str:
        equip = entities.get("equipment", "")
        results = [
            h for h in self.store.all_hospitals()
            if any(equip.lower() in e.lower() for e in h.get("equipment", []))
        ] if equip else []

        if not equip:
            return "어떤 장비를 찾으세요? (예: 'MRI 있는 병원', 'CT 검사 가능한 병원')"
        if not results:
            return f"'{equip}' 장비를 보유한 병원을 찾지 못했습니다."

        lines = [f"🩻 {equip} 보유 병원 {len(results)}개:\n"]
        for h in results[:5]:
            eq_list = ", ".join(h.get("equipment", []))
            lines.append(
                f"🏥 {h['name']} ({h.get('type', '')})\n"
                f"   📍 {h.get('address', '')}\n"
                f"   📞 {h.get('phone', '')}\n"
                f"   🩻 장비: {eq_list}"
            )
        return "\n".join(lines)

    def _handle_find_by_specialist(self, entities: dict, raw: str) -> str:
        specialty = entities.get("specialty", "")
        results = [
            (h, h.get("specialists", {}).get(specialty, 0))
            for h in self.store.all_hospitals()
            if specialty and h.get("specialists", {}).get(specialty, 0) > 0
        ]
        results.sort(key=lambda x: x[1], reverse=True)

        if not specialty:
            return "어떤 전문의를 찾으세요? (예: '내과 전문의 있는 병원', '정형외과 전문의 몇 명')"
        if not results:
            return f"'{specialty}' 전문의 정보가 있는 병원을 찾지 못했습니다."

        lines = [f"👨‍⚕️ {specialty} 전문의 보유 병원 {len(results)}개 (많은 순):\n"]
        for h, cnt in results[:5]:
            lines.append(
                f"🏥 {h['name']} ({h.get('type', '')})\n"
                f"   👨‍⚕️ {specialty} 전문의 {cnt}명\n"
                f"   📞 {h.get('phone', '')}"
            )
        return "\n".join(lines)

    def _handle_unknown(self, entities: dict, raw: str) -> str:
        return (
            "죄송합니다, 잘 이해하지 못했습니다. 다음과 같이 물어보실 수 있습니다:\n"
            "• '오늘 충남대학교병원 영업해?'\n"
            "• '대전 내과 병원 찾아줘'\n"
            "• '응급실 운영하는 병원 알려줘'\n"
            "• '대전 약국 찾아줘'\n"
            "• '당번약국 알려줘'\n"
            "• '등록된 병원 목록 보여줘'\n"
            "• 'MRI 있는 병원 알려줘'\n"
            "• '내과 전문의 있는 병원'"
        )
