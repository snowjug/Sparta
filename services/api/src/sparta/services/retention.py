"""Retention: transcripts and call records expire according to each owner's own policy.

Two clocks per owner (``RetentionPolicy``): transcript content (turns, event log, evidence excerpts) goes after
``transcript_retention_days`` while the summary and risk level stay; the whole record goes after
``summary_retention_days``. Short-lived technical rows (idempotency keys, provider event ids) are purged as well.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from sparta.clock import Clock
from sparta.db.session import Database
from sparta.services.audit import record_audit

log = logging.getLogger("sparta.retention")
MAX_PER_USER_PER_BATCH = 500
MAX_BATCHES_PER_USER = 20  # a run clears up to 10,000 calls per owner, so purging keeps up with ingestion
PROVIDER_EVENT_AGE = timedelta(days=30)


@dataclass
class RetentionReport:
    users: int = 0
    content_deleted: int = 0
    records_deleted: int = 0


class RetentionService:
    def __init__(self, db: Database, clock: Clock) -> None:
        self.db, self.clock = db, clock

    async def run_once(self) -> RetentionReport:
        report = RetentionReport()
        now = self.clock.now()
        async with self.db.uow() as repo:
            users = await repo.user_ids()
        for user_id in users:
            report.users += 1
            for _ in range(MAX_BATCHES_PER_USER):
                content, records = await self._purge_batch(user_id, now)
                report.content_deleted += content
                report.records_deleted += records
                if content + records < MAX_PER_USER_PER_BATCH:
                    break
        async with self.db.uow() as repo:
            await repo.purge_expired_technical(now, PROVIDER_EVENT_AGE)
        if report.content_deleted or report.records_deleted:
            log.info(
                "retention applied",
                extra={"content_deleted": report.content_deleted, "records_deleted": report.records_deleted},
            )
        return report

    async def _purge_batch(self, user_id: str, now: datetime) -> tuple[int, int]:
        """Delete up to one batch of expired transcripts and records for one owner; returns the two counts."""
        async with self.db.uow() as repo:
            prefs = await repo.get_preferences(user_id)
            content_cutoff = now - timedelta(days=prefs.retention.transcript_retention_days)
            record_cutoff = now - timedelta(days=prefs.retention.summary_retention_days)
            expired_records = (await repo.record_expiry_candidates(user_id, record_cutoff))[:MAX_PER_USER_PER_BATCH]
            budget = MAX_PER_USER_PER_BATCH - len(expired_records)
            gone = set(expired_records)
            expired_content = [
                c for c in await repo.content_expiry_candidates(user_id, content_cutoff) if c not in gone
            ][: max(budget, 0)]
            for call_id in expired_content:
                await repo.delete_transcript(call_id)
            for call_id in expired_records:
                await repo.delete_call(user_id, call_id)
            if expired_content or expired_records:
                await record_audit(
                    repo,
                    user_id,
                    "retention.applied",
                    "calls",
                    None,
                    {"content": len(expired_content), "records": len(expired_records)},
                    now=now,
                )
        return len(expired_content), len(expired_records)
