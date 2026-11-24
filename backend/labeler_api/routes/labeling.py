"""Marketplace-facing API: submit postings, read decisions, follow jobs."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request

from labeler.errors import NotReady
from labeler.labeling.schemas import Posting
from labeler_api.deps import ServiceDep
from labeler_api.schemas import BatchIn

router = APIRouter(prefix="/api", tags=["labeling"])


@router.post("/postings")
async def submit_posting(posting: Posting, svc: ServiceDep, policy_version: str | None = None) -> dict[str, Any]:
    """Label one posting synchronously and return the full decision. 503 with the reason when the
    model provider is not set up yet (e.g. no API key): nothing is labeled or stored then."""
    svc.policy(policy_version)  # 404 before spending a model call on an unknown version
    if reason := svc.blocked_reason():
        raise NotReady(f"cannot label now: {reason}")
    result = await svc.label_one(posting, policy_version)
    return result.model_dump(mode="json")


@router.post("/postings/batch")
async def submit_batch(body: BatchIn, svc: ServiceDep) -> dict[str, Any]:
    """Put many postings on the live queue; poll /api/jobs/{id} and fetch results per job_id."""
    job_id = await svc.submit_batch(body.postings, body.policy_version)
    return {"job_id": job_id, "status_url": f"/api/jobs/{job_id}"}


@router.get("/results/{job_id}")
def get_result(job_id: str, svc: ServiceDep, policy_version: str | None = None, full: bool = False) -> dict[str, Any]:
    """The decision for a posting under the published policy (or a given version)."""
    result, version = svc.result_for(job_id, policy_version)
    if result is None:
        raise HTTPException(404, f"no label for {job_id} under {version}")
    return result.model_dump(mode="json") if full else result.public()


@router.get("/jobs/{job_id}")
def get_job(job_id: int, svc: ServiceDep) -> dict[str, Any]:
    job = svc.db.get_job(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    return job


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: int, svc: ServiceDep) -> dict[str, Any]:
    """Stop a queued or running job. Postings already labeled keep their labels; the rest are
    skipped when a worker receives their message. 409 if the job already finished."""
    job = svc.db.get_job(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    if job["status"] not in ("queued", "running"):
        raise HTTPException(409, f"job is {job['status']}; nothing to cancel")
    n = svc.db.cancel_job(job_id)
    return {"job_id": job_id, "status": "cancelled", "cancelled_items": n}


@router.post("/jobs/{job_id}/requeue")
async def requeue_job(job_id: int, svc: ServiceDep) -> dict[str, Any]:
    """Re-send the messages for a job's pending items (the local ElasticMQ keeps messages in
    memory, so a restart loses them; SQS does not). Idempotent: done items are skipped."""
    n = await svc.requeue(job_id)
    return {"job_id": job_id, "resent": n}


@router.get("/jobs")
def list_jobs(svc: ServiceDep) -> list[dict[str, Any]]:
    return svc.db.list_jobs()


@router.get("/work")
async def work(
    svc: ServiceDep,
    request: Request,
    status: Annotated[list[str] | None, Query()] = None,
    version: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """What is waiting (`queued`), being labeled now (`labeling`) or `failed`, per posting and
    version, with the queue depth and the workers next to it. `queued` here is the database's
    view; `queues` is the broker's, so a gap between them (e.g. a restarted local ElasticMQ)
    shows, and `POST /jobs/{id}/requeue` closes it."""
    counts, total, items = svc.db.query_work(status or [], version, limit=limit, offset=offset)
    queues: dict[str, Any] = {}
    for q in ("live", "backfill"):
        try:
            queues[q] = await request.app.state.queue.depth(q)
        except Exception as e:  # noqa: BLE001  (show the rest even if the broker is down)
            queues[q] = {"error": str(e)}
    return {
        "counts": counts,
        "total": total,
        "items": items,
        "queues": queues,
        "workers": svc.db.live_workers(),
        "jobs": [j for j in svc.db.list_jobs(50) if j["status"] in ("queued", "running")],
    }


@router.get("/events")
def list_events(svc: ServiceDep, after: int = 0, limit: int = Query(100, ge=1, le=1000)) -> dict[str, Any]:
    """PostingLabeled events after `after` (the outbox). The marketplace polls this to act on
    VIOLATING; in production a relay publishes the same rows to EventBridge."""
    items = svc.db.events_after(after, limit)
    return {"items": items, "next_after": items[-1]["id"] if items else after}
