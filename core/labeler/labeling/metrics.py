"""Evaluation metrics against EMSCAD's binary gold label.

NEEDS_REVIEW is neither a yes nor a no, so it is reported explicitly and scored
two ways:

  strict   only VIOLATING counts as "fraud" (what the system blocks on its own)
  flagged  VIOLATING or NEEDS_REVIEW counts as "fraud" (what reaches a human or is blocked)

The confusion matrix keeps all three predicted labels so nothing is hidden.
"""

from __future__ import annotations

from statistics import quantiles
from typing import Any


def _prf(tp: int, fp: int, fn: int) -> dict[str, float]:
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * p * r / (p + r) if p + r else 0.0
    return {"precision": round(p, 3), "recall": round(r, 3), "f1": round(f1, 3), "tp": tp, "fp": fp, "fn": fn}


def _pct(values: list[float], q: int) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return round(values[0], 1)
    return round(quantiles(values, n=100, method="inclusive")[q - 1], 1)


def evaluate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """rows: dicts with label, gold (0/1), sections, tier, cost_usd, latency_ms."""
    scored = [r for r in rows if r.get("gold") is not None]
    matrix = {lab: {"fraud": 0, "legit": 0} for lab in ("VIOLATING", "NEEDS_REVIEW", "ALLOWED")}
    for r in scored:
        matrix[r["label"]]["fraud" if r["gold"] == 1 else "legit"] += 1

    v, nr, al = matrix["VIOLATING"], matrix["NEEDS_REVIEW"], matrix["ALLOWED"]
    strict = _prf(tp=v["fraud"], fp=v["legit"], fn=nr["fraud"] + al["fraud"])
    flagged = _prf(tp=v["fraud"] + nr["fraud"], fp=v["legit"] + nr["legit"], fn=al["fraud"])

    sections: dict[str, dict[str, int]] = {}
    for r in scored:
        for s in r.get("sections", []):
            d = sections.setdefault(s, {"fraud": 0, "legit": 0})
            d["fraud" if r["gold"] == 1 else "legit"] += 1

    costs = [r.get("cost_usd", 0.0) for r in rows]
    lat = [r.get("latency_ms", 0.0) for r in rows if r.get("tier") not in ("failed", "guard")]
    tiers: dict[str, int] = {}
    for r in rows:
        tiers[r.get("tier", "?")] = tiers.get(r.get("tier", "?"), 0) + 1

    n = len(rows)
    return {
        **policy_application(rows),
        "n": n,
        "n_scored": len(scored),
        "confusion": matrix,
        "strict": strict,
        "flagged": flagged,
        "review_rate": round((nr["fraud"] + nr["legit"]) / len(scored), 3) if scored else 0.0,
        "sections": sections,
        "tiers": tiers,
        "escalation_rate": round(tiers.get("tier2", 0) / n, 3) if n else 0.0,
        "cost_per_1k_usd": round(sum(costs) / n * 1000, 4) if n else 0.0,
        # Decisions made by a model with no list price (cost counted as 0): the cost above is a floor.
        "cost_unpriced": sum(1 for r in rows if r.get("cost_unpriced")),
        "total_cost_usd": round(sum(costs), 4),
        "latency_ms": {"p50": _pct(lat, 50), "p95": _pct(lat, 95), "max": round(max(lat), 1) if lat else 0.0},
    }


def policy_application(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """How the policy was applied, from the decisions alone (no dataset label needed).

    rows: dicts with label, sections, tier and evidence_n (verified quotes behind the decision).
    """
    labels = {lab: 0 for lab in ("VIOLATING", "NEEDS_REVIEW", "ALLOWED")}
    section_counts: dict[str, int] = {}
    combos: dict[str, int] = {}
    blocks = blocks_grounded = 0
    routes = {"section": 0, "failed": 0, "other": 0}
    for r in rows:
        labels[r["label"]] = labels.get(r["label"], 0) + 1
        secs = r.get("sections", [])
        for s in secs:
            section_counts[s] = section_counts.get(s, 0) + 1
        if secs:
            key = " + ".join(secs)
            combos[key] = combos.get(key, 0) + 1
        if r["label"] == "VIOLATING":
            blocks += 1
            blocks_grounded += bool(r.get("evidence_n"))
        elif r["label"] == "NEEDS_REVIEW":
            if r.get("tier") in ("failed", "guard"):
                routes["failed"] += 1  # a model failure or an input guard: a human looks instead
            elif secs:
                routes["section"] += 1  # routed by a section of the policy
            else:
                routes["other"] += 1  # the model reported it could not decide
    n = len(rows)
    return {
        "labels": labels,
        "blocks": {"total": blocks, "with_verified_quote": blocks_grounded},
        "review_routes": routes,
        "review_share": round(labels["NEEDS_REVIEW"] / n, 3) if n else 0.0,
        "section_counts": dict(sorted(section_counts.items())),
        "section_combos": dict(sorted(combos.items(), key=lambda kv: -kv[1])),
    }


def review_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Analyst checks of decisions: how often the agent is upheld, per label it gave.

    rows: dicts with verdict (agree | overturn), agent_label, final_label. Unlike the dataset
    metrics above, this is what the team itself says, so it is the production quality signal
    (DESIGN.md §5). It is only as unbiased as the choice of which cases get checked.
    """
    per: dict[str, dict[str, int]] = {}
    transitions: dict[str, int] = {}
    for r in rows:
        p = per.setdefault(r["agent_label"], {"checked": 0, "overturned": 0})
        p["checked"] += 1
        if r["verdict"] == "overturn":
            p["overturned"] += 1
            key = f"{r['agent_label']}->{r['final_label']}"
            transitions[key] = transitions.get(key, 0) + 1
    n = len(rows)
    overturned = sum(p["overturned"] for p in per.values())
    return {
        "checked": n,
        "agreed": n - overturned,
        "overturned": overturned,
        "agreement_rate": round((n - overturned) / n, 3) if n else None,
        "by_label": per,
        "transitions": transitions,
    }
