from dataclasses import dataclass
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.services.scans import ScanController


SCAN_JOB_ID = "job-agent-periodic-scan"


@dataclass(frozen=True)
class ScanScheduleSnapshot:
    interval_hours: float
    next_run_at: datetime | None


class ScanScheduler:
    def __init__(self, controller: ScanController, *, interval_hours: float) -> None:
        if not 0.25 <= interval_hours <= 168:
            raise ValueError("Scan interval must be between 0.25 and 168 hours")
        self.controller = controller
        self.interval_hours = interval_hours
        self.scheduler = AsyncIOScheduler(timezone=timezone.utc)

    def start(self) -> None:
        self.scheduler.add_job(
            self.controller.run_scheduled,
            "interval",
            hours=self.interval_hours,
            id=SCAN_JOB_ID,
            name="Job Agent scheduled scan",
            coalesce=True,
            max_instances=1,
            replace_existing=True,
        )
        self.scheduler.start()

    def snapshot(self) -> ScanScheduleSnapshot:
        job = self.scheduler.get_job(SCAN_JOB_ID)
        return ScanScheduleSnapshot(
            interval_hours=self.interval_hours,
            next_run_at=job.next_run_time if job is not None else None,
        )

    def pause(self) -> None:
        if self.scheduler.running:
            self.scheduler.pause()

    def resume(self) -> None:
        if self.scheduler.running:
            self.scheduler.resume()

    def shutdown(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
