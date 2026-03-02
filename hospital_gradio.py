"""
Hospital Info Bot — Gradio 데모
로체 봇 챗 + 병원 현황 대시보드 + 에이전트 관리

실행:
  python hospital_gradio.py
"""

import json
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

def _hospital_rows() -> list[list]:
    """병원 목록을 DataFrame 행 형태로 반환합니다."""
    rows = []
    for h in store.all_hospitals():
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


HOSPITAL_HEADERS = ["병원명", "종류", "주소", "전화", "진료과", "응급실", "오늘 상태", "운영 시간"]


# ---------------------------------------------------------------------------
# Tab 1: 로체 봇 채팅
# ---------------------------------------------------------------------------

def respond(message: str, history: list) -> tuple[str, list]:
    """로체 봇 응답 생성."""
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
            "병원 정보 및 오늘 영업 여부를 물어보세요.\n\n"
            "**예시:** `오늘 서울대학교병원 영업해?` / `내과 병원 찾아줘` / `응급실 운영하는 병원 알려줘`"
        )
        chatbot = gr.Chatbot(
            value=[
                {"role": "assistant", "content": "안녕하세요! 로체 봇입니다. 병원 정보나 오늘 영업 여부를 물어보세요."}
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
# Tab 2: 병원 현황 대시보드
# ---------------------------------------------------------------------------

def refresh_table(filter_text: str):
    rows = _hospital_rows()
    if filter_text.strip():
        kw = filter_text.strip().lower()
        rows = [r for r in rows if any(kw in str(cell).lower() for cell in r)]
    return rows


def get_dashboard_tab():
    with gr.Column():
        gr.Markdown("## 병원 현황\n등록된 병원 목록과 오늘의 영업 상태입니다.")
        with gr.Row():
            filter_input = gr.Textbox(
                placeholder="병원명·진료과·주소로 필터...",
                show_label=False,
                scale=8,
            )
            refresh_btn = gr.Button("새로고침", scale=2)

        table = gr.DataFrame(
            value=_hospital_rows(),
            headers=HOSPITAL_HEADERS,
            interactive=False,
            wrap=True,
        )

    filter_input.change(refresh_table, filter_input, table)
    refresh_btn.click(refresh_table, filter_input, table)


# ---------------------------------------------------------------------------
# Tab 3: 에이전트 관리
# ---------------------------------------------------------------------------

def run_collect() -> str:
    result = collector.run()
    return (
        f"[{datetime.now().strftime('%H:%M:%S')}] 수집 완료\n"
        f"저장된 병원: {result['count']}건\n"
        f"ID 목록: {', '.join(result['saved_ids'])}"
    )


def run_check() -> tuple[str, list]:
    result = checker.run()
    log = (
        f"[{datetime.now().strftime('%H:%M:%S')}] 영업 체크 완료\n"
        f"영업: {result['open']}건 / 휴진: {result['closed']}건"
    )
    return log, _hospital_rows()


def manual_register(name, htype, address, phone, specialties, emergency) -> str:
    if not name.strip():
        return "병원 이름을 입력해 주세요."
    hospital = {
        "name": name.strip(),
        "type": htype,
        "address": address.strip(),
        "phone": phone.strip(),
        "specialties": [s.strip() for s in specialties.split(",") if s.strip()],
        "emergency": emergency,
        "hours": {},
    }
    hid = store.save_hospital(hospital)
    return f"등록 완료: {name} ({hid})"


def get_admin_tab():
    with gr.Column():
        gr.Markdown("## 에이전트 관리\n수동으로 에이전트를 실행하거나 병원을 직접 등록합니다.")

        with gr.Row():
            # 수집 패널
            with gr.Column():
                gr.Markdown("### 병원 정보 수집")
                gr.Markdown("HIRA 공공 API 또는 더미 데이터로 병원 정보를 수집합니다.")
                collect_btn = gr.Button("수집 실행", variant="primary")
                collect_log = gr.Textbox(label="수집 결과", lines=4, interactive=False)

            # 체크 패널
            with gr.Column():
                gr.Markdown("### 영업 상태 체크")
                gr.Markdown("오늘 날짜 기준으로 모든 병원의 영업 여부를 업데이트합니다.")
                check_btn = gr.Button("체크 실행", variant="primary")
                check_log = gr.Textbox(label="체크 결과", lines=4, interactive=False)

        gr.Markdown("---")
        gr.Markdown("### 병원 직접 등록")
        with gr.Row():
            with gr.Column():
                reg_name = gr.Textbox(label="병원명 *", placeholder="예) 서울내과의원")
                reg_type = gr.Dropdown(
                    choices=["의원", "병원", "종합병원", "상급종합병원", "한의원", "치과", "기타"],
                    value="의원",
                    label="종류",
                )
                reg_address = gr.Textbox(label="주소", placeholder="예) 서울특별시 강남구 ...")
            with gr.Column():
                reg_phone = gr.Textbox(label="전화번호", placeholder="예) 02-1234-5678")
                reg_specialties = gr.Textbox(label="진료과 (쉼표 구분)", placeholder="예) 내과, 소아과")
                reg_emergency = gr.Checkbox(label="응급실 운영")
        reg_btn = gr.Button("등록", variant="secondary")
        reg_log = gr.Textbox(label="등록 결과", lines=2, interactive=False)

        # 최하단 현황 테이블 (체크 후 자동 갱신)
        gr.Markdown("### 현재 등록 현황")
        admin_table = gr.DataFrame(
            value=_hospital_rows(),
            headers=HOSPITAL_HEADERS,
            interactive=False,
        )

    collect_btn.click(run_collect, None, collect_log)
    check_btn.click(run_check, None, [check_log, admin_table])
    reg_btn.click(
        manual_register,
        [reg_name, reg_type, reg_address, reg_phone, reg_specialties, reg_emergency],
        reg_log,
    )


# ---------------------------------------------------------------------------
# 메인 앱
# ---------------------------------------------------------------------------

with gr.Blocks(title="로체 봇 — 병원 정보 서비스") as demo:
    gr.Markdown(
        "# 로체 봇 병원 정보 서비스\n"
        "병원 정보 수집 · 매일 영업 체크 · 로체 봇 챗"
    )

    with gr.Tab("로체 봇 채팅"):
        get_chat_tab()

    with gr.Tab("병원 현황"):
        get_dashboard_tab()

    with gr.Tab("에이전트 관리"):
        get_admin_tab()


if __name__ == "__main__":
    demo.launch(share=False, theme=gr.themes.Soft())
