"""The queue consumer: takes messages, runs the agent, acknowledges. The ECS Fargate service of the design.

Runs standalone (`python -m labeler_worker`, see __main__.py) or embedded in the API process when
EMBEDDED_WORKER=true (the default with the in-memory queue), so `make dev` and the tests need
no extra process.

Scheduling: up to MAX_CONCURRENCY postings in flight. Live messages always first; the backfill
queue is read only when live is empty, so a 30-day re-label never delays new postings.
Delivery is at-least-once: a message is deleted only after its label is stored, and the DB
records each job item once, so redelivery is harmless.

Readiness: before taking messages the worker checks that both tiers' providers can be called
(an API key is set, the `claude` command exists for claude_cli). If not, it keeps running and
heartbeating as `waiting`, takes nothing, and starts by itself within seconds of the key being
added on the Settings page. No restart, and no posting is failed for a missing key.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from labeler.infra.queue import Message, QueueName, WorkQueue
from labeler.infra.telemetry import QUEUE_DEPTH, WORKER_MESSAGES
from labeler.services.labeling import Service
from labeler_worker.heartbeat import Heartbeat

log = logging.getLogger("labeler_worker")
HEARTBEAT_S = 10.0
READY_CHECK_S = 3.0  # how often a waiting worker re-checks (settings and keys are cached ~5 s)

MAX_RECEIVES = 3  # matches the queues' redrive policy: the 3rd failure goes to the DLQ


class Worker:
    def __init__(
        self,
        svc: Service,
        queue: WorkQueue,
        concurrency: int,
        idle_wait_s: float = 2.0,
        max_backoff_s: float = 30.0,
        role: str = "standalone",
        ready_check_s: float = READY_CHECK_S,
    ):
        self.svc = svc
        self.queue = queue
        self.concurrency = concurrency
        self.idle_wait_s = idle_wait_s
        self.max_backoff_s = max_backoff_s
        self.ready_check_s = ready_check_s
        self._inflight: set[asyncio.Task] = set()
        self._stop = asyncio.Event()
        self.heartbeat = Heartbeat(svc.db, role=role, concurrency=concurrency)

    def stop(self) -> None:
        self._stop.set()

    async def run(self) -> None:
        log.info("worker started (concurrency=%d)", self.concurrency)
        with contextlib.suppress(Exception):
            if closed := await asyncio.to_thread(self.svc.db.close_finished_jobs):
                log.info("closed finished jobs left running: %s", closed)
        await self._waiting()  # first heartbeat already carries the right status (no racing insert)
        depth_task = asyncio.create_task(self._report_depth())
        beat_task = asyncio.create_task(self._beat())
        backoff = 0.5
        try:
            while not self._stop.is_set():
                if await self._waiting():
                    with contextlib.suppress(TimeoutError):
                        await asyncio.wait_for(self._stop.wait(), timeout=self.ready_check_s)
                    continue
                free = self.concurrency - len(self._inflight)
                if free <= 0:
                    await asyncio.wait(self._inflight, return_when=asyncio.FIRST_COMPLETED)
                    continue
                try:
                    got = await self._poll(free)
                    backoff = 0.5
                except Exception as e:  # noqa: BLE001  (queue unreachable: wait and retry, never die)
                    log.warning("queue receive failed (%s); retrying in %.1fs", type(e).__name__, backoff)
                    WORKER_MESSAGES.labels("any", "receive_error").inc()
                    with contextlib.suppress(TimeoutError):
                        await asyncio.wait_for(self._stop.wait(), timeout=backoff)
                    backoff = min(backoff * 2, self.max_backoff_s)
                    continue
                if not got:
                    continue
                for qname, msg in got:
                    task = asyncio.create_task(self._handle(qname, msg))
                    self._inflight.add(task)
                    task.add_done_callback(self._inflight.discard)
        finally:
            depth_task.cancel()
            beat_task.cancel()
            if self._inflight:  # graceful shutdown: finish what we took, the rest stays queued
                log.info("draining %d in-flight messages", len(self._inflight))
                await asyncio.gather(*self._inflight, return_exceptions=True)
            await asyncio.to_thread(self.heartbeat.stopped)
            log.info("worker stopped")

    async def _waiting(self) -> bool:
        """True while a tier's provider cannot be called; records the state in the heartbeat."""
        try:
            reason = await asyncio.to_thread(self.svc.blocked_reason)
        except Exception:  # DB briefly down: do not block on the check, the poll will retry
            log.debug("readiness check failed", exc_info=True)
            return False
        status = "waiting" if reason else "running"
        if (status, reason or "") != (self.heartbeat.status, self.heartbeat.detail):
            if reason:
                log.warning("not taking messages: %s", reason)
            else:
                log.info("provider ready; taking messages")
            self.heartbeat.status, self.heartbeat.detail = status, reason or ""
            with contextlib.suppress(Exception):  # show the change now, not at the next beat
                await asyncio.to_thread(self.heartbeat.beat, len(self._inflight))
        return reason is not None

    async def _poll(self, n: int) -> list[tuple[QueueName, Message]]:
        live = await self.queue.receive("live", n, 0)
        if live:
            return [("live", m) for m in live]
        backfill = await self.queue.receive("backfill", n, 0)
        if backfill:
            return [("backfill", m) for m in backfill]
        # Both empty: long-poll live so new postings are picked up immediately.
        stop = asyncio.create_task(self._stop.wait())
        poll = asyncio.create_task(self.queue.receive("live", n, self.idle_wait_s))
        done, _ = await asyncio.wait({stop, poll}, return_when=asyncio.FIRST_COMPLETED)
        stop.cancel()
        if poll in done:
            return [("live", m) for m in poll.result()]
        poll.cancel()
        return []

    async def _handle(self, qname: QueueName, msg: Message) -> None:
        b = msg.body
        try:
            failed = await self.svc.process_item(int(b["job_id"]), str(b["posting_id"]), str(b["policy_version"]))
        except Exception:
            log.exception("message for %s failed (receive %d)", b.get("posting_id"), msg.receive_count)
            WORKER_MESSAGES.labels(qname, "error").inc()
            if msg.receive_count >= MAX_RECEIVES:
                # The queue moves it to the DLQ for inspection and replay; close the item so the job finishes.
                try:
                    await asyncio.to_thread(
                        self.svc.db.mark_item,
                        int(b["job_id"]),
                        str(b["posting_id"]),
                        failed=True,
                        error=f"gave up after {msg.receive_count} attempts; message is in the dead-letter queue",
                    )
                except Exception:
                    log.exception("could not record dead-lettered item")
            return  # not acked: redelivered after the visibility timeout
        await self.queue.ack(qname, msg)
        WORKER_MESSAGES.labels(qname, "failed" if failed else "ok").inc()
        self.heartbeat.count(failed)

    async def _beat(self) -> None:
        """Tell the API this worker is alive, so the UI can say when nobody is consuming the queue."""
        while True:
            try:
                await asyncio.to_thread(self.heartbeat.beat, len(self._inflight))
            except Exception:
                log.debug("heartbeat failed", exc_info=True)
            await asyncio.sleep(HEARTBEAT_S)

    async def _report_depth(self) -> None:
        while True:
            for q in ("live", "backfill"):
                try:
                    for state, n in (await self.queue.depth(q)).items():
                        QUEUE_DEPTH.labels(q, state).set(n)
                except Exception:
                    log.debug("queue depth unavailable", exc_info=True)
            await asyncio.sleep(10)
