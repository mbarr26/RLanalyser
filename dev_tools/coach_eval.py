"""Run the AI coach on real replays and check what it writes. Developer tool, not shipped.

    python dev_tools/coach_eval.py                     # 5 replays from your replay folder, Lite model
    python dev_tools/coach_eval.py --count 10 --tier standard
    python dev_tools/coach_eval.py --folder path\\to\\replays --me "YourName"

For each replay it builds the dossier (the facts the model is given), asks for the report and checks:
  - the report has the expected shape and no empty summary,
  - every number of 11 or more, and every decimal, in the text appears in the dossier (so the model hasn't
    made one up; small whole numbers are allowed because "2 goals" is natural wording),
  - every game clock like 2:30 appears in the dossier,
  - strengths aren't padded (more strengths than the rule-based findings can support are flagged),
  - how long it took.
It prints each report so you can read it, and writes coach_eval_report.md (not committed).
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

NUMBER = re.compile(r"(?<![\w:.])\d+(?:\.\d+)?(?![\w:])")
CLOCK = re.compile(r"\b\d{1,2}:[0-5]\d\b")
SMALL_WHOLE = 10
BAD_NEWS = ("conceded", "ahead of the ball on", "beaten", "0 boost", "no boost", "nobody back", "lost")


def report_text(report):
    """All the free text of a report as one list of strings."""
    parts = [report.get("summary", "")] + list(report.get("strengths", [])) + list(report.get("weaknesses", []))
    parts += list(report.get("focus_for_next_games", []))
    for k in report.get("key_moments", []):
        parts += [k.get("title", ""), k.get("what_happened", ""), k.get("advice", "")]
    return [p for p in parts if p]


def invented_numbers(texts, dossier):
    """Numbers in the texts that are not in the dossier (small whole numbers and clocks are ignored here)."""
    known = {float(n) for n in NUMBER.findall(CLOCK.sub(" ", dossier))}
    bad = []
    for text in texts:
        for raw in NUMBER.findall(CLOCK.sub(" ", text)):
            value = float(raw)
            if "." not in raw and value <= SMALL_WHOLE:
                continue
            if value not in known and round(value) not in known:
                bad.append(raw)
    return bad


def invented_clocks(texts, dossier):
    known = set(CLOCK.findall(dossier))
    return [c for text in texts for c in CLOCK.findall(text) if c not in known]


def check(report, dossier, insights):
    """List of problems found in one report (empty = clean)."""
    problems = []
    if not str(report.get("summary", "")).strip():
        problems.append("empty summary")
    for key in ("strengths", "weaknesses", "key_moments", "focus_for_next_games"):
        if not isinstance(report.get(key), list):
            problems.append(f"{key} missing")
    texts = report_text(report)
    if (nums := invented_numbers(texts, dossier)):
        problems.append(f"numbers not in the data: {', '.join(nums)}")
    if (clocks := invented_clocks(texts, dossier)):
        problems.append(f"clocks not in the data: {', '.join(clocks)}")
    for text in report.get("strengths", []):
        if any(w in text.lower() for w in BAD_NEWS):
            problems.append(f"strength reads like a weakness: {text[:70]}")
    good = sum(i["kind"] == "good" for i in insights)
    if len(report.get("strengths", [])) > good + 1:
        problems.append(f"{len(report['strengths'])} strengths but only {good} positive findings")
    return problems


def pick_me(record, wanted_id, wanted_name):
    for p in record.summary.players:
        if (wanted_name and p.name == wanted_name) or (wanted_id and p.player_id == wanted_id):
            return p
    name = record.summary.recorded_by
    return next((p for p in record.summary.players if p.name == name), None)


def main():
    import coach
    from replay_library import analyse

    ap = argparse.ArgumentParser()
    ap.add_argument("--folder")
    ap.add_argument("--count", type=int, default=5)
    ap.add_argument("--tier", default=coach.DEFAULT_TIER, choices=list(coach.TIERS))
    ap.add_argument("--me", help="your player name (default: the 'me' saved in config.json)")
    ap.add_argument("--out", default=str(ROOT / "coach_eval_report.md"))
    args = ap.parse_args()

    config = json.loads((ROOT / "config.json").read_text()) if (ROOT / "config.json").exists() else {}
    folder = Path(args.folder or config.get("replay_dir", ""))
    files = sorted(folder.glob("*.replay"))
    if not files:
        sys.exit(f"No replays in {folder}")
    if not coach.model_ready(args.tier):
        sys.exit(f"The {args.tier} model isn't installed. Install it from the app's AI panel first.")

    out, clean, seconds = [f"# Coach evaluation ({args.tier})", ""], 0, []
    done = 0
    for path in files:
        if done >= args.count:
            break
        record, game = analyse(path)
        me = pick_me(record, config.get("me"), args.me) if game is not None else None
        if me is None or me.name not in (record.players or {}):
            continue
        done += 1
        facts = coach.analyse_for_coach(record, game, me.player_id, [])
        started = time.time()
        try:
            report = coach.generate_report(facts["dossier"], facts["moments"], facts["me"], facts["team"], args.tier)
        except Exception as e:
            out += [f"## {path.name}", f"FAILED: {e}", ""]
            print(f"{path.name}: FAILED {e}")
            continue
        took = time.time() - started
        seconds.append(took)
        problems = check(report, facts["dossier"], facts["insights"])
        clean += not problems
        status = "clean" if not problems else "; ".join(problems)
        print(f"{path.name[:8]} {me.name}: {took:.0f}s - {status}")
        out += [f"## {path.name} ({me.name}, {took:.0f}s)", f"Problems: {status}", "", "```", json.dumps(report, indent=1),
                "```", ""]
    summary = f"{clean}/{done} reports clean; average {sum(seconds) / max(len(seconds), 1):.0f}s each"
    print(summary)
    Path(args.out).write_text("\n".join([out[0], summary, ""] + out[1:]), encoding="utf-8")


if __name__ == "__main__":
    main()
