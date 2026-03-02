"""
HospitalAgentScheduler
에이전트들의 실행 일정을 관리하는 스케줄러

스케줄:
  - 매일 06:00 : HospitalInfoCollectorAgent 실행 (병원 정보 갱신)
  - 매일 07:00 : DailyBusinessCheckerAgent 실행 (오늘 영업 상태 체크)
  - 매 6시간   : DailyBusinessCheckerAgent 재실행 (임시 휴진 등 갱신)
"""

import logging
import threading
from datetime import datetime

from .collector_agent import HospitalInfoCollectorAgent, CollectorConfig
from .daily_checker_agent import DailyBusinessCheckerAgent, CheckerConfig
from .data_store import HospitalDataStore

logger = logging.getLogger(__name__)


class HospitalAgentScheduler:
    """
    APScheduler 없이 threading.Timer 기반으로 동작하는 경량 스케줄러.
    APScheduler를 설치하면 _run_with_apscheduler()를 사용할 수 있습니다.
    """

    def __init__(
        self,
        collector: HospitalInfoCollectorAgent | None = None,
        checker: DailyBusinessCheckerAgent | None = None,
        store: HospitalDataStore | None = None,
    ):
        self.store = store or HospitalDataStore()
        self.collector = collector or HospitalInfoCollectorAgent(store=self.store)
        self.checker = checker or DailyBusinessCheckerAgent(store=self.store)
        self._timers: list[threading.Timer] = []
        self._running = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self, immediate: bool = True):
        """스케줄러를 시작합니다."""
        self._running = True
        logger.info("[Scheduler] 시작")

        if immediate:
            # 즉시 한 번 실행
            self._run_collect()
            self._run_check()

        self._schedule_next_collect()
        self._schedule_next_check()

    def stop(self):
        """스케줄러를 중지합니다."""
        self._running = False
        for t in self._timers:
            t.cancel()
        self._timers.clear()
        logger.info("[Scheduler] 중지")

    def run_once(self):
        """스케줄 없이 즉시 한 번 실행합니다 (테스트용)."""
        collect_result = self._run_collect()
        check_result = self._run_check()
        return {"collect": collect_result, "check": check_result}

    # ------------------------------------------------------------------
    # Job runners
    # ------------------------------------------------------------------

    def _run_collect(self) -> dict:
        logger.info("[Scheduler] 병원 정보 수집 시작")
        try:
            result = self.collector.run()
            logger.info("[Scheduler] 수집 완료: %d건", result.get("count", 0))
            return result
        except Exception as e:
            logger.error("[Scheduler] 수집 오류: %s", e)
            return {"error": str(e)}

    def _run_check(self) -> dict:
        logger.info("[Scheduler] 영업 상태 체크 시작")
        try:
            result = self.checker.run()
            logger.info("[Scheduler] 체크 완료: 영업 %d / 휴진 %d", result.get("open", 0), result.get("closed", 0))
            return result
        except Exception as e:
            logger.error("[Scheduler] 체크 오류: %s", e)
            return {"error": str(e)}

    # ------------------------------------------------------------------
    # Timer scheduling (lightweight)
    # ------------------------------------------------------------------

    def _seconds_until(self, hour: int, minute: int = 0) -> float:
        """지정한 시각까지 남은 초를 반환합니다. 이미 지났으면 다음날 기준."""
        now = datetime.now()
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        delta = (target - now).total_seconds()
        if delta <= 0:
            delta += 86400  # 다음날
        return delta

    def _schedule_next_collect(self):
        if not self._running:
            return
        delay = self._seconds_until(6, 0)
        t = threading.Timer(delay, self._collect_and_reschedule)
        t.daemon = True
        t.start()
        self._timers.append(t)
        logger.info("[Scheduler] 다음 수집: %.0f초 후 (06:00)", delay)

    def _schedule_next_check(self):
        if not self._running:
            return
        delay = self._seconds_until(7, 0)
        t = threading.Timer(delay, self._check_and_reschedule)
        t.daemon = True
        t.start()
        self._timers.append(t)
        logger.info("[Scheduler] 다음 체크: %.0f초 후 (07:00)", delay)

    def _collect_and_reschedule(self):
        self._run_collect()
        self._schedule_next_collect()

    def _check_and_reschedule(self):
        self._run_check()
        # 6시간 후 재체크
        t = threading.Timer(6 * 3600, self._check_and_reschedule)
        t.daemon = True
        t.start()
        self._timers.append(t)

    # ------------------------------------------------------------------
    # APScheduler integration (optional)
    # ------------------------------------------------------------------

    def run_with_apscheduler(self):
        """
        APScheduler를 사용한 고급 스케줄링 (pip install apscheduler 필요).
        크론 기반으로 더 정확한 일정 관리가 가능합니다.
        """
        try:
            from apscheduler.schedulers.blocking import BlockingScheduler
            from apscheduler.triggers.cron import CronTrigger
        except ImportError:
            raise RuntimeError("APScheduler가 설치되지 않았습니다: pip install apscheduler")

        sched = BlockingScheduler(timezone="Asia/Seoul")
        sched.add_job(self._run_collect, CronTrigger(hour=6, minute=0), id="collect_daily")
        sched.add_job(self._run_check, CronTrigger(hour="7,13,19", minute=0), id="check_triday")
        logger.info("[Scheduler] APScheduler 시작 (Asia/Seoul)")
        sched.start()
