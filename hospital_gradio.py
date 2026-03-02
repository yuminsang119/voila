"""
Hospital Info Bot — Gradio 데모
로체 봇 챗 + 병원 현황 + 약국 현황 + 에이전트 관리

실행:
  python hospital_gradio.py
"""

from datetime import datetime

import gradio as gr

from hospital_agents.main import build_team

# ---------------------------------------------------------------------------
# 팀 초기화 (공유 상태)
# ---------------------------------------------------------------------------

team = build_team(use_dummy=True)
collector = team["collector"]
checker = team["checker"]
bot = team["bot"]
store = team["store"]

# 데이터가 없으면 초기 수집·체크 실행
if not store.all_hospitals():
    collector.run()
    checker.run()


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------

HOSPITAL_HEADERS = ["병원명", "종류", "주소", "전화", "진료과", "응급실", "오늘 상태", "운영 시간"]
PHARMACY_HEADERS = ["약국명", "주소", "전화", "취급품목", "당번약국", "오늘 상태", "운영 시간"]

REGION_CHOICES = ["전체", "대전", "서울", "부산", "인천", "광주", "대구", "울산"]


def _hospital_rows(region: str = "") -> list[list]:
    rows = []
    for h in store.all_hospitals():
        if region and region != "전체" and region not in h.get("address", ""):
            continue
        status = store.get_today_status(h["id"])
        open_str = "✅ 영업" if (status and status.get("is_open")) else "❌ 휴진"
        hours_str = status.get("hours", "-") if status else "-"
        rows.append([
            h.get("name", ""),
            h.get("type", ""),
            h.get("address", ""),
            h.get("phone", ""),
            ", ".join(h.get("specialties", [])),
            "🚨 있음" if h.get("emergency") else "없음",
            open_str,
            hours_str,
        ])
    return rows


def _pharmacy_rows(region: str = "") -> list[list]:
    rows = []
    for p in store.all_pharmacies():
        if region and region != "전체" and region not in p.get("address", ""):
            continue
        status = store.get_today_pharmacy_status(p["id"])
        open_str = "✅ 영업" if (status and status.get("is_open")) else "❌ 휴무"
        hours_str = status.get("hours", "-") if status else "-"
        rows.append([
            p.get("name", ""),
            p.get("address", ""),
            p.get("phone", ""),
            ", ".join(p.get("handled_items", [])),
            "🌙 당번" if p.get("duty_pharmacy") else "-",
            open_str,
            hours_str,
        ])
    return rows


# ---------------------------------------------------------------------------
# Tab 1: 로체 봇 채팅
# ---------------------------------------------------------------------------

def respond(message: str, history: list) -> tuple[str, list]:
    if not message.strip():
        return "", history
    reply = bot.chat(message)
    history.append({"role": "user", "content": message})
    history.append({"role": "assistant", "content": reply})
    return "", history


def get_chat_tab():
    with gr.Column():
        gr.Markdown(
            "## 로체 봇\n"
            "대전 관내 병원·약국 정보를 물어보세요.\n\n"
            "**예시:** `오늘 충남대학교병원 영업해?` / `대전 내과 병원 찾아줘` "
            "/ `응급실 운영하는 병원 알려줘` / `대전 약국 찾아줘` / `당번약국 알려줘`"
        )
        chatbot = gr.Chatbot(
            value=[
                {"role": "assistant", "content": (
                    "안녕하세요! 로체 봇입니다.\n"
                    "대전 관내 병원·약국 정보나 오늘 영업 여부를 물어보세요."
                )}
            ],
            height=480,
            label="로체 봇",
        )
        with gr.Row():
            msg_input = gr.Textbox(
                placeholder="질문을 입력하세요...",
                show_label=False,
                scale=9,
                autofocus=True,
            )
            send_btn = gr.Button("전송", scale=1, variant="primary")
        clear_btn = gr.Button("대화 초기화", size="sm")

    send_btn.click(respond, [msg_input, chatbot], [msg_input, chatbot])
    msg_input.submit(respond, [msg_input, chatbot], [msg_input, chatbot])
    clear_btn.click(lambda: ([], ""), None, [chatbot, msg_input])


# ---------------------------------------------------------------------------
# Tab 2: 병원 현황
# ---------------------------------------------------------------------------

def refresh_hospital_table(region: str, keyword: str) -> list:
    rows = _hospital_rows(region)
    if keyword.strip():
        kw = keyword.strip().lower()
        rows = [r for r in rows if any(kw in str(cell).lower() for cell in r)]
    return rows


def get_dashboard_tab():
    with gr.Column():
        gr.Markdown("## 병원 현황\n대전 관내 병원 목록과 오늘의 영업 상태입니다.")
        with gr.Row():
            region_filter = gr.Dropdown(
                choices=REGION_CHOICES,
                value="대전",
                label="지역",
                scale=2,
            )
            keyword_input = gr.Textbox(
                placeholder="병원명·진료과·주소로 추가 필터...",
                show_label=False,
                scale=6,
            )
            refresh_btn = gr.Button("새로고침", scale=2)

        table = gr.DataFrame(
            value=_hospital_rows("대전"),
            headers=HOSPITAL_HEADERS,
            interactive=False,
            wrap=True,
        )

    region_filter.change(refresh_hospital_table, [region_filter, keyword_input], table)
    keyword_input.change(refresh_hospital_table, [region_filter, keyword_input], table)
    refresh_btn.click(refresh_hospital_table, [region_filter, keyword_input], table)


# ---------------------------------------------------------------------------
# Tab 3: 약국 현황
# ---------------------------------------------------------------------------

def refresh_pharmacy_table(region: str, keyword: str, duty_only: bool) -> list:
    rows = _pharmacy_rows(region)
    if duty_only:
        rows = [r for r in rows if r[4] == "🌙 당번"]
    if keyword.strip():
        kw = keyword.strip().lower()
        rows = [r for r in rows if any(kw in str(cell).lower() for cell in r)]
    return rows


def get_pharmacy_tab():
    with gr.Column():
        gr.Markdown("## 약국 현황\n대전 관내 약국 목록과 오늘의 영업 상태입니다.")
        with gr.Row():
            pharm_region = gr.Dropdown(
                choices=REGION_CHOICES,
                value="대전",
                label="지역",
                scale=2,
            )
            pharm_keyword = gr.Textbox(
                placeholder="약국명·주소·취급품목으로 필터...",
                show_label=False,
                scale=5,
            )
            duty_check = gr.Checkbox(label="당번약국만", scale=2)
            pharm_refresh_btn = gr.Button("새로고침", scale=1)

        pharm_table = gr.DataFrame(
            value=_pharmacy_rows("대전"),
            headers=PHARMACY_HEADERS,
            interactive=False,
            wrap=True,
        )

    pharm_region.change(refresh_pharmacy_table, [pharm_region, pharm_keyword, duty_check], pharm_table)
    pharm_keyword.change(refresh_pharmacy_table, [pharm_region, pharm_keyword, duty_check], pharm_table)
    duty_check.change(refresh_pharmacy_table, [pharm_region, pharm_keyword, duty_check], pharm_table)
    pharm_refresh_btn.click(refresh_pharmacy_table, [pharm_region, pharm_keyword, duty_check], pharm_table)


# ---------------------------------------------------------------------------
# Tab 4: 에이전트 관리
# ---------------------------------------------------------------------------

def run_collect() -> tuple[str, list, list]:
    result = collector.run()
    log = (
        f"[{datetime.now().strftime('%H:%M:%S')}] 수집 완료\n"
        f"병원: {result['count']}건 | 약국: {result['pharmacy_count']}건\n"
        f"병원 ID: {', '.join(result['saved_ids'])}\n"
        f"약국 ID: {', '.join(result['pharmacy_ids'])}"
    )
    return log, _hospital_rows("대전"), _pharmacy_rows("대전")


def run_check() -> tuple[str, list, list]:
    result = checker.run()
    log = (
        f"[{datetime.now().strftime('%H:%M:%S')}] 영업 체크 완료\n"
        f"병원 영업: {result['open']}건 / 휴진: {result['closed']}건\n"
        f"약국 영업: {result['pharmacy_open']}건 / 휴무: {result['pharmacy_closed']}건"
    )
    return log, _hospital_rows("대전"), _pharmacy_rows("대전")


def manual_register_hospital(name, htype, address, phone, specialties, emergency) -> str:
    if not name.strip():
        return "병원 이름을 입력해 주세요."
    hid = store.save_hospital({
        "name": name.strip(),
        "type": htype,
        "address": address.strip(),
        "phone": phone.strip(),
        "specialties": [s.strip() for s in specialties.split(",") if s.strip()],
        "emergency": emergency,
        "hours": {},
    })
    return f"등록 완료: {name} ({hid})"


def manual_register_pharmacy(name, address, phone, items, duty) -> str:
    if not name.strip():
        return "약국 이름을 입력해 주세요."
    pid = store.save_pharmacy({
        "name": name.strip(),
        "type": "약국",
        "address": address.strip(),
        "phone": phone.strip(),
        "handled_items": [s.strip() for s in items.split(",") if s.strip()],
        "duty_pharmacy": duty,
        "hours": {},
    })
    return f"등록 완료: {name} ({pid})"


def get_admin_tab():
    with gr.Column():
        gr.Markdown("## 에이전트 관리\n수동으로 에이전트를 실행하거나 병원·약국을 직접 등록합니다.")

        with gr.Row():
            with gr.Column():
                gr.Markdown("### 병원·약국 정보 수집")
                gr.Markdown("HIRA 공공 API 또는 대전 더미 데이터로 수집합니다.")
                collect_btn = gr.Button("수집 실행", variant="primary")
                collect_log = gr.Textbox(label="수집 결과", lines=5, interactive=False)

            with gr.Column():
                gr.Markdown("### 영업 상태 체크")
                gr.Markdown("오늘 날짜 기준으로 병원·약국 영업 여부를 업데이트합니다.")
                check_btn = gr.Button("체크 실행", variant="primary")
                check_log = gr.Textbox(label="체크 결과", lines=5, interactive=False)

        gr.Markdown("---")

        with gr.Row():
            # 병원 등록 폼
            with gr.Column():
                gr.Markdown("### 병원 직접 등록")
                reg_name = gr.Textbox(label="병원명 *", placeholder="예) 대전○○의원")
                reg_type = gr.Dropdown(
                    choices=["의원", "병원", "종합병원", "상급종합병원", "한의원", "치과", "기타"],
                    value="의원",
                    label="종류",
                )
                reg_address = gr.Textbox(label="주소", placeholder="예) 대전광역시 서구 ...")
                reg_phone = gr.Textbox(label="전화번호", placeholder="예) 042-000-0000")
                reg_specialties = gr.Textbox(label="진료과 (쉼표 구분)", placeholder="예) 내과, 소아과")
                reg_emergency = gr.Checkbox(label="응급실 운영")
                reg_btn = gr.Button("병원 등록", variant="secondary")
                reg_log = gr.Textbox(label="등록 결과", lines=2, interactive=False)

            # 약국 등록 폼
            with gr.Column():
                gr.Markdown("### 약국 직접 등록")
                pharm_name = gr.Textbox(label="약국명 *", placeholder="예) 대전○○약국")
                pharm_address = gr.Textbox(label="주소", placeholder="예) 대전광역시 중구 ...")
                pharm_phone = gr.Textbox(label="전화번호", placeholder="예) 042-000-0000")
                pharm_items = gr.Textbox(
                    label="취급품목 (쉼표 구분)",
                    placeholder="예) 전문의약품, 일반의약품",
                    value="전문의약품, 일반의약품",
                )
                pharm_duty = gr.Checkbox(label="당번약국 (휴일·야간 운영)")
                pharm_btn = gr.Button("약국 등록", variant="secondary")
                pharm_log = gr.Textbox(label="등록 결과", lines=2, interactive=False)

        gr.Markdown("---")
        gr.Markdown("### 현재 등록 현황")
        with gr.Row():
            with gr.Column():
                gr.Markdown("**병원**")
                admin_hosp_table = gr.DataFrame(
                    value=_hospital_rows("대전"),
                    headers=HOSPITAL_HEADERS,
                    interactive=False,
                )
            with gr.Column():
                gr.Markdown("**약국**")
                admin_pharm_table = gr.DataFrame(
                    value=_pharmacy_rows("대전"),
                    headers=PHARMACY_HEADERS,
                    interactive=False,
                )

    collect_btn.click(run_collect, None, [collect_log, admin_hosp_table, admin_pharm_table])
    check_btn.click(run_check, None, [check_log, admin_hosp_table, admin_pharm_table])
    reg_btn.click(
        manual_register_hospital,
        [reg_name, reg_type, reg_address, reg_phone, reg_specialties, reg_emergency],
        reg_log,
    )
    pharm_btn.click(
        manual_register_pharmacy,
        [pharm_name, pharm_address, pharm_phone, pharm_items, pharm_duty],
        pharm_log,
    )


# ---------------------------------------------------------------------------
# 메인 앱
# ---------------------------------------------------------------------------

with gr.Blocks(title="로체 봇 — 대전 병원·약국 정보 서비스") as demo:
    gr.Markdown(
        "# 로체 봇 — 대전 병원·약국 정보 서비스\n"
        "병원·약국 정보 수집 · 매일 영업 체크 · 로체 봇 챗"
    )

    with gr.Tab("로체 봇 채팅"):
        get_chat_tab()

    with gr.Tab("병원 현황"):
        get_dashboard_tab()

    with gr.Tab("약국 현황"):
        get_pharmacy_tab()

    with gr.Tab("에이전트 관리"):
        get_admin_tab()


if __name__ == "__main__":
    demo.launch(share=False, theme=gr.themes.Soft())
