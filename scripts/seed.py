"""The measured runs behind RESULTS.md, shipped with the repo so a fresh `docker compose up` shows them.

    uv run python -m scripts.seed export [source.db]   # maintainers: write data/seed/seed.json.gz
    uv run python -m scripts.seed load                 # what `init` runs when the database has no labels

The seed holds policy rows (v1 published, v2 as a draft, so the v2 demo still runs its
draft -> shadow-run -> publish path) and every stored decision on EMSCAD postings, traces
included. Postings themselves come from the dataset load.
"""

from __future__ import annotations

import gzip
import json
import sqlite3
import sys
from pathlib import Path

from labeler.bootstrap import build_db
from labeler.config import get_settings
from labeler.labeling.schemas import LabelResult


def seed_path() -> Path:
    return get_settings().data_dir / "seed" / "seed.json.gz"


def export(source: Path) -> None:
    con = sqlite3.connect(source)
    con.row_factory = sqlite3.Row
    pols = [dict(r) for r in con.execute("SELECT version, source, note FROM policies ORDER BY created_at")]
    for p in pols:
        p["status"] = "published" if p["version"] == "v1" else "draft"
    labels = [
        {"result": json.loads(r["result"]), "created_at": r["created_at"]}
        for r in con.execute("SELECT result, created_at FROM labels ORDER BY policy_version, created_at")
        if r["result"] and json.loads(r["result"])["job_id"].isdigit()  # EMSCAD ids only, no ad-hoc demos
    ]
    out = seed_path()
    out.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(out, "wt", encoding="utf-8") as f:
        json.dump({"policies": pols, "labels": labels}, f, ensure_ascii=False)
    print(f"wrote {out}: {len(pols)} policies, {len(labels)} labels, {out.stat().st_size // 1024} KiB")


def load() -> None:
    path = seed_path()
    if not path.exists():
        print("no seed file; skipping")
        return
    with gzip.open(path, "rt", encoding="utf-8") as f:
        data = json.load(f)
    db = build_db(get_settings())
    for p in data["policies"]:
        if not db.get_policy_row(p["version"]):
            db.insert_policy(p["version"], p["source"], "draft", p.get("note", ""))
            if p["status"] == "published":
                db.publish_policy(p["version"])
    for row in data["labels"]:
        db.save_label(LabelResult.model_validate(row["result"]), emit_event=False, created_at=row["created_at"])
    print(f"seed: {len(data['policies'])} policies, {len(data['labels'])} labels (traces -> object store)")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "load"
    if cmd == "export":
        export(Path(sys.argv[2]) if len(sys.argv) > 2 else get_settings().data_dir / "labeler.db")
    else:
        load()
