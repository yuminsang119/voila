"""
Hospital Agent Team — Main Orchestrator
병원 정보 에이전트 팀 메인 진입점

실행 모드:
  python -m hospital_agents.main              # 스케줄러 데몬 실행
  python -m hospital_agents.main --once       # 1회 수집+체크 후 종료
  python -m hospital_agents.main --chat       # 로체 봇 대화 모드
  python -m hospital_agents.main --collect    # 수집만 실행
  python -m hospital_agents.main --check      # 체크만 실행
"""

import argparse
import logging
import sys

from .collector_agent import HospitalInfoCollectorAgent, CollectorConfig
from .daily_checker_agent import DailyBusinessCheckerAgent, CheckerConfig
from .roche_bot import RocheBot
from .scheduler import HospitalAgentScheduler
from .data_store import HospitalDataStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Team factory
# ---------------------------------------------------------------------------

def build_team(
    hira_api_key: str = "",
    holiday_api_key: str = "",
    use_dummy: bool = True,
) -> dict:
    """
    에이전트 팀을 생성하고 공유 DataStore로 연결합니다.

    Returns:
        {
            "store"    : HospitalDataStore,
            "collector": HospitalInfoCollectorAgent,
            "checker"  : DailyBusinessCheckerAgent,
            "bot"      : RocheBot,
            "scheduler": HospitalAgentScheduler,
        }
    """
    store = HospitalDataStore()

    collector = HospitalInfoCollectorAgent(
        config=CollectorConfig(
            hira_api_key=hira_api_key,
            use_dummy_data=use_dummy,
        ),
        store=store,
    )

    checker = DailyBusinessCheckerAgent(
        config=CheckerConfig(holiday_api_key=holiday_api_key),
        store=store,
    )

    bot = RocheBot(store=store)

    scheduler = HospitalAgentScheduler(
        collector=collector,
        checker=checker,
        store=store,
    )

    logger.info(
        "팀 구성 완료 — Collector: %s | Checker: %s | Bot: %s",
        collector.name,
        checker.name,
        bot.name,
    )
    return {
        "store": store,
        "collector": collector,
        "checker": checker,
        "bot": bot,
        "scheduler": scheduler,
    }


# ---------------------------------------------------------------------------
# Chat loop
# ---------------------------------------------------------------------------

def run_chat(bot: RocheBot):
    print("\n" + "=" * 55)
    print("  로체 봇에 오신 것을 환영합니다! (종료: 'quit' 또는 'exit')")
    print("=" * 55)
    print(bot.chat("안녕"))
    print()

    while True:
        try:
            user_input = input("사용자: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n[로체 봇] 이용해 주셔서 감사합니다. 건강하세요!")
            break

        if user_input.lower() in ("quit", "exit", "종료", "끝"):
            print("[로체 봇] 이용해 주셔서 감사합니다. 건강하세요!")
            break

        if not user_input:
            continue

        response = bot.chat(user_input)
        print(f"\n로체 봇: {response}\n")


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="병원 정보 에이전트 팀",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--once", action="store_true", help="1회 수집+체크 후 종료")
    parser.add_argument("--chat", action="store_true", help="로체 봇 대화 모드")
    parser.add_argument("--collect", action="store_true", help="수집만 실행")
    parser.add_argument("--check", action="store_true", help="체크만 실행")
    parser.add_argument("--hira-key", default="", metavar="KEY", help="HIRA 공공 API 서비스키")
    parser.add_argument("--holiday-key", default="", metavar="KEY", help="공휴일 공공 API 서비스키")
    parser.add_argument("--no-dummy", action="store_true", help="더미 데이터 사용 안 함")
    args = parser.parse_args()

    use_dummy = not args.no_dummy or not args.hira_key
    team = build_team(
        hira_api_key=args.hira_key,
        holiday_api_key=args.holiday_key,
        use_dummy=use_dummy,
    )

    if args.collect:
        result = team["collector"].run()
        print(f"수집 완료: {result['count']}건")

    elif args.check:
        result = team["checker"].run()
        print(f"체크 완료: 영업 {result['open']}건 / 휴진 {result['closed']}건")

    elif args.once:
        result = team["scheduler"].run_once()
        print("1회 실행 완료:", result)

    elif args.chat:
        # 데이터가 없으면 먼저 수집+체크
        if not team["store"].all_hospitals():
            logger.info("병원 데이터 없음 — 초기 수집 실행")
            team["scheduler"].run_once()
        run_chat(team["bot"])

    else:
        # 기본: 스케줄러 데몬 실행
        try:
            team["scheduler"].start(immediate=True)
            logger.info("스케줄러 실행 중... (Ctrl+C로 종료)")
            # 메인 스레드 대기
            import time
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            team["scheduler"].stop()
            logger.info("스케줄러 종료")


if __name__ == "__main__":
    main()
