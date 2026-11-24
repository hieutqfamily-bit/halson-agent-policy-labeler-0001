from labeler.labeling.metrics import evaluate


def row(label, gold, tier="tier1", cost=0.001, lat=1000.0, sections=()):
    return {"label": label, "gold": gold, "tier": tier, "cost_usd": cost, "latency_ms": lat, "sections": list(sections)}


def test_needs_review_is_scored_both_ways():
    rows = [
        row("VIOLATING", 1),
        row("VIOLATING", 0),
        row("NEEDS_REVIEW", 1),
        row("NEEDS_REVIEW", 0),
        row("ALLOWED", 1),
        row("ALLOWED", 0),
        row("ALLOWED", 0),
    ]
    m = evaluate(rows)
    assert m["confusion"]["NEEDS_REVIEW"] == {"fraud": 1, "legit": 1}
    # strict: only VIOLATING is a positive
    assert (m["strict"]["tp"], m["strict"]["fp"], m["strict"]["fn"]) == (1, 1, 2)
    # flagged: VIOLATING or NEEDS_REVIEW is a positive
    assert (m["flagged"]["tp"], m["flagged"]["fp"], m["flagged"]["fn"]) == (2, 2, 1)
    assert m["strict"]["recall"] == round(1 / 3, 3)
    assert m["review_rate"] == round(2 / 7, 3)


def test_cost_and_latency_summary():
    rows = [row("ALLOWED", 0, cost=0.002, lat=float(i)) for i in range(1, 101)]
    rows.append(row("NEEDS_REVIEW", 0, tier="failed", cost=0.0, lat=99999.0))
    m = evaluate(rows)
    assert m["latency_ms"]["p50"] == 50.5
    assert m["latency_ms"]["max"] == 100.0  # failed items excluded from latency
    assert m["cost_per_1k_usd"] == round(0.2 / 101 * 1000, 4)


def test_policy_application_needs_no_dataset_label():
    from labeler.labeling.metrics import policy_application

    rows = [
        {"label": "VIOLATING", "sections": ["§4", "§5"], "tier": "tier1", "evidence_n": 2},
        {"label": "VIOLATING", "sections": ["§1"], "tier": "tier2", "evidence_n": 0},
        {"label": "NEEDS_REVIEW", "sections": ["§5"], "tier": "tier1", "evidence_n": 0},
        {"label": "NEEDS_REVIEW", "sections": [], "tier": "failed", "evidence_n": 0},
        {"label": "ALLOWED", "sections": [], "tier": "tier1", "evidence_n": 0},
    ]
    m = policy_application(rows)
    assert m["labels"] == {"VIOLATING": 2, "NEEDS_REVIEW": 2, "ALLOWED": 1}
    assert m["blocks"] == {"total": 2, "with_verified_quote": 1}
    assert m["review_routes"] == {"section": 1, "failed": 1, "other": 0}
    assert m["section_counts"] == {"§1": 1, "§4": 1, "§5": 2}
    assert m["section_combos"] == {"§4 + §5": 1, "§1": 1, "§5": 1}
    assert m["review_share"] == 0.4
