"""Analyst UI reads: the decision queue, a single case, metrics and version comparison."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query

from labeler.labeling.metrics import evaluate, review_summary
from labeler.labeling.schemas import Label
from labeler_api.deps import ServiceDep
from labeler_api.schemas import ReviewIn

router = APIRouter(prefix="/api", tags=["analyst"])


@router.get("/labels")
def list_labels(
    svc: ServiceDep,
    policy_version: str | None = None,
    label: Label | None = None,
    section: str | None = None,
    tier: str | None = None,
    eval_only: bool = False,
    disagree: bool = False,
    review: Literal["unreviewed", "agree", "overturn"] | None = None,
    q: str | None = None,
    order: Literal["risk", "confidence", "recent", "id"] = "risk",
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    version = policy_version or svc.policy().version
    total, items = svc.db.query_labels(
        version,
        label=label.value if label else None,
        section=section,
        tier=tier,
        eval_only=eval_only,
        disagree=disagree,
        review=review,
        q=q,
        order=order,
        limit=limit,
        offset=offset,
    )
    return {"policy_version": version, "total": total, "items": items}


@router.get("/postings/{job_id}")
def get_posting(job_id: str, svc: ServiceDep, policy_version: str | None = None) -> dict[str, Any]:
    """Posting text, its decision under a version, and its history across versions."""
    found = svc.db.get_posting(job_id)
    if not found:
        raise HTTPException(404, "posting not found")
    posting, gold, is_eval = found
    result, version = svc.result_for(job_id, policy_version)
    return {
        "posting": posting.model_dump(),
        "gold": gold,
        "is_eval": is_eval,
        "policy_version": version,
        "result": result.model_dump(mode="json") if result else None,
        "history": svc.db.label_versions(job_id),
        "review": svc.db.get_review(job_id, version) if result else None,
    }


@router.put("/postings/{job_id}/review")
def review_decision(job_id: str, body: ReviewIn, svc: ServiceDep) -> dict[str, Any]:
    """Agree with the decision, or overturn it with the right label and a reason. Replaces an earlier
    check of the same decision, and emits a PostingReviewed event for the marketplace."""
    return svc.review(
        job_id,
        body.policy_version,
        verdict=body.verdict,
        final_label=body.label,
        note=body.note,
        reviewer=body.reviewer,
    )


@router.delete("/postings/{job_id}/review")
def undo_review(job_id: str, svc: ServiceDep, policy_version: str | None = None) -> dict[str, bool]:
    if not svc.db.delete_review(job_id, policy_version or svc.policy().version):
        raise HTTPException(404, "no review to undo")
    return {"undone": True}


@router.get("/postings/{job_id}/versions")
def posting_versions(
    job_id: str, svc: ServiceDep, v: Annotated[list[str], Query(min_length=1, max_length=8)]
) -> dict[str, Any]:
    """One posting's decision under several policy versions, side by side (`?v=v1&v=v2&v=v3`).
    A version that never labeled this posting comes back with `result: null`; label it with
    POST /api/policies/{version}/relabel {"scope": "ids", "ids": [job_id]}."""
    return {"job_id": job_id, "versions": svc.posting_versions(job_id, v)}


@router.get("/metrics")
def metrics(svc: ServiceDep, policy_version: str | None = None, eval_only: bool = True) -> dict[str, Any]:
    version = policy_version or svc.policy().version
    rows = svc.db.label_rows(version, eval_only=eval_only)
    reviews = review_summary(svc.db.review_rows(version, eval_only=eval_only))
    return {"policy_version": version, "eval_only": eval_only, **evaluate(rows), "reviews": reviews}


@router.get("/compare")
def compare(a: str, b: str, svc: ServiceDep) -> dict[str, Any]:
    return svc.compare(a, b)
