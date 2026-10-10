"""Precision per event type from the "Was this right?" votes in labels.jsonl. Developer tool, not shipped.

    python dev_tools/label_report.py [path\to\labels.jsonl]

Lists, for each kind of event, how many votes there are and how many said "right", then the replay and
time of every "wrong" one so you can re-watch it. Target: at least 80% on 20+ votes per kind.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import labels  # noqa: E402

TARGET = 0.8
ENOUGH = 20


def main():
    rows = labels.load(sys.argv[1] if len(sys.argv) > 1 else None)
    if not rows:
        sys.exit("No votes yet. Open a match, go to Key moments and press the thumbs up / down.")
    stats = labels.precision(rows)
    print(f"{'kind':<20}{'votes':>6}{'right':>7}{'precision':>11}")
    for kind, s in sorted(stats.items(), key=lambda kv: kv[1]["precision"]):
        note = "" if s["n"] >= ENOUGH else "  (need more votes)"
        note += "  <-- below target" if s["precision"] < TARGET and s["n"] >= ENOUGH else ""
        print(f"{kind:<20}{s['n']:>6}{s['right']:>7}{s['precision']:>10.0%}{note}")
    print()
    for kind, s in stats.items():
        for row in s["wrong"]:
            print(f"wrong {kind}: {row['replay']} at {row['at']:.1f}s - {row['title']}")


if __name__ == "__main__":
    main()
