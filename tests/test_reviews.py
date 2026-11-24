"""Analyst checks: agree with or overturn a decision, filter by them, count them."""

from fastapi.testclient import TestClient

from labeler.infra.llm.fake import FakeProvider
from labeler.labeling.metrics import review_summary
from labeler.labeling.schemas import Label, Posting
from labeler_api.main import create_app
from tests.test_repository import label, make_db


def test_review_upserts_filters_and_emits_event(db_url, tmp_path):
    db = make_db(db_url, tmp_path)
    db.upsert_postings([(Posting(job_id=j, title=j), None, False) for j in ("1", "2", "3")])
    for j in ("1", "2", "3"):
        db.save_label(
            label(j, lab=Label.VIOLATING if j != "3" else Label.ALLOWED, sections=() if j == "3" else ("§3",))
        )

    assert db.put_review("missing", "v1", verdict="agree", final_label="ALLOWED") is None
    db.put_review("1", "v1", verdict="agree", final_label="VIOLATING")
    db.put_review("2", "v1", verdict="agree", final_label="VIOLATING")
    db.put_review("2", "v1", verdict="overturn", final_label="ALLOWED", note="recruiter is real")  # replaces

    r2 = db.get_review("2", "v1")
    assert r2["verdict"] == "overturn" and r2["agent_label"] == "VIOLATING" and r2["final_label"] == "ALLOWED"

    _, overturned = db.query_labels("v1", review="overturn")
    _, unreviewed = db.query_labels("v1", review="unreviewed")
    total, everything = db.query_labels("v1")
    assert [i["job_id"] for i in overturned] == ["2"]
    assert [i["job_id"] for i in unreviewed] == ["3"]
    assert total == 3 and {i["job_id"]: i["review"] for i in everything}["2"] == {
        "verdict": "overturn",
        "final_label": "ALLOWED",
    }

    reviewed = [e for e in db.events_after(0, 100) if e["type"] == "PostingReviewed"]
    assert len(reviewed) == 3 and reviewed[-1]["payload"]["final_label"] == "ALLOWED"

    s = review_summary(db.review_rows("v1"))
    assert s["checked"] == 2 and s["overturned"] == 1 and s["agreement_rate"] == 0.5
    assert s["transitions"] == {"VIOLATING->ALLOWED": 1}

    assert db.delete_review("2", "v1") and not db.delete_review("2", "v1")


def test_review_api_validates_and_shows_on_the_case(settings):
    app = create_app(settings, FakeProvider())  # the scripted model finds nothing: ALLOWED
    with TestClient(app) as c:
        posting = {
            "job_id": "r1",
            "title": "Clerk",
            "description": "Pay a $99 starter kit fee before your first shift.",
        }
        assert c.post("/api/postings", json=posting).json()["label"] == "ALLOWED"

        bad = [
            ({"verdict": "overturn"}, 422),  # no label
            ({"verdict": "overturn", "label": "ALLOWED", "note": "x"}, 422),  # same as the decision
            ({"verdict": "overturn", "label": "VIOLATING"}, 422),  # no reason given
            ({"verdict": "maybe"}, 422),
        ]
        for body, status in bad:
            assert c.put("/api/postings/r1/review", json=body).status_code == status, body
        assert c.put("/api/postings/nope/review", json={"verdict": "agree"}).status_code == 404

        r = c.put(
            "/api/postings/r1/review",
            json={"verdict": "overturn", "label": "VIOLATING", "note": "§1: asks for a starter-kit fee"},
        )
        assert r.status_code == 200 and r.json()["final_label"] == "VIOLATING"

        case = c.get("/api/postings/r1").json()
        assert case["result"]["label"] == "ALLOWED"  # the agent's decision is kept as it was
        assert case["review"]["verdict"] == "overturn" and case["review"]["note"].startswith("§1")

        m = c.get("/api/metrics", params={"eval_only": False}).json()["reviews"]
        assert m["checked"] == 1 and m["by_label"] == {"ALLOWED": {"checked": 1, "overturned": 1}}

        assert c.get("/api/labels", params={"review": "overturn"}).json()["total"] == 1
        assert c.delete("/api/postings/r1/review").status_code == 200
        assert c.get("/api/postings/r1").json()["review"] is None
