""""Was this right?" votes on detected events, kept so the detection rules can be tuned against real games.

One JSON line per vote in `labels.jsonl` (in the app's data folder). The newest vote for the same event
replaces older ones when the file is read. Pure storage and arithmetic, no UI.
"""

import json
import time
from pathlib import Path

from paths import user_data

LABELS_PATH = user_data("labels.jsonl")


def add(replay, kind, at, vote, version, title="", path=None):
    """Append a vote. vote: True = the event was right, False = it was wrong. at: replay time in seconds."""
    row = {"replay": Path(replay).name, "kind": kind, "at": round(float(at), 2), "right": bool(vote),
           "version": version, "title": title, "saved": int(time.time())}
    path = Path(path or LABELS_PATH)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")
    return row


def load(path=None):
    """Latest vote per (replay, kind, time), oldest first. Missing or damaged lines are skipped."""
    path = Path(path or LABELS_PATH)
    latest = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in lines:
        try:
            row = json.loads(line)
            latest[(row["replay"], row["kind"], round(row["at"], 1))] = row
        except (ValueError, KeyError, TypeError):
            continue
    return sorted(latest.values(), key=lambda r: r["saved"])


def precision(rows):
    """{kind: {n, right, precision, wrong: [rows]}}: how often each kind of event was marked right."""
    out = {}
    for row in rows:
        s = out.setdefault(row["kind"], {"n": 0, "right": 0, "wrong": []})
        s["n"] += 1
        if row["right"]:
            s["right"] += 1
        else:
            s["wrong"].append(row)
    for s in out.values():
        s["precision"] = s["right"] / s["n"]
    return out
