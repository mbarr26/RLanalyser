"""Check this app's numbers against ballchasing.com and against the replay headers. Developer tool, not shipped.

    set BALLCHASING_TOKEN=<your token>
    python dev_tools/validate.py --per-band 10                  # download, analyse, compare, write the report
    python dev_tools/validate.py --offline                      # re-run on replays already in benchmark_cache/
    python dev_tools/validate.py --local                        # header checks only, on your own replay folder
    python dev_tools/validate.py --benchmarks                   # sanity-check benchmarks.json (no token needed)

A. Per-player stats ballchasing also measures (speed, boost, positioning) are compared with ours:
   correlation, mean bias (ours - theirs), mean absolute gap and the worst outliers. The two tools measure
   slightly differently, so a steady bias is expected; a low correlation or a wild outlier suggests a bug.
B. Checks that need no outside data: the goal scorer was the last toucher before each goal, touches line up
   with the header's shots/saves, and touches per minute are plausible.
The report is written to validation_report.md (not committed).
"""

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

# (our column, ballchasing stats group, ballchasing key). Percent stats are 0-100 in both;
# ballchasing's avg_amount is boost 0-100.
COMPARED = [
    ("avg_speed", "movement", "avg_speed"),
    ("pct_supersonic", "movement", "percent_supersonic_speed"),
    ("pct_boost_speed", "movement", "percent_boost_speed"),
    ("pct_slow", "movement", "percent_slow_speed"),
    ("pct_ground", "movement", "percent_ground"),
    ("pct_low_air", "movement", "percent_low_air"),
    ("pct_high_air", "movement", "percent_high_air"),
    ("pct_def_third", "positioning", "percent_defensive_third"),
    ("pct_mid_third", "positioning", "percent_neutral_third"),
    ("pct_off_third", "positioning", "percent_offensive_third"),
    ("pct_behind_ball", "positioning", "percent_behind_ball"),
    ("avg_dist_to_ball", "positioning", "avg_distance_to_ball"),
    ("pct_closest_to_ball", "positioning", "percent_closest_to_ball"),
    ("pct_farthest_from_ball", "positioning", "percent_farthest_from_ball"),
    ("avg_boost", "boost", "avg_amount"),
    ("boost_collected", "boost", "amount_collected"),
    ("big_pads", "boost", "count_collected_big"),
    ("small_pads", "boost", "count_collected_small"),
    ("stolen_big_pads", "boost", "count_stolen_big"),
    ("pct_zero_boost", "boost", "percent_zero_boost"),
    ("pct_full_boost", "boost", "percent_full_boost"),
]
TARGET_CORRELATION = 0.9
TOUCHES_PER_MIN = (0.5, 20.0)       # outside this a player-game is flagged as implausible
OUTLIERS = 3                        # worst gaps listed per stat
# stats expected to go up with rank (for the benchmarks.json check)
SKILL_UP = ["avg_speed", "pct_supersonic", "touches_per_min", "aerial_touches", "boost_collected"]


# ---- pure logic (unit-tested in tests/test_validate.py) ----

def ballchasing_players(detail):
    """{(team, name): stats-dict} from a ballchasing replay JSON; team 0 = blue, 1 = orange."""
    out = {}
    for team, colour in enumerate(("blue", "orange")):
        for p in (detail.get(colour) or {}).get("players", []):
            out[(team, p.get("name"))] = p.get("stats") or {}
    return out


def pairs_for_replay(detail, our_players):
    """Matched (name, our column, ours, theirs) tuples for one replay.

    our_players: record.players, {name: {"team": 0|1, <stat>: value, ...}}.
    """
    theirs = ballchasing_players(detail)
    rows = []
    for name, ours in our_players.items():
        stats = theirs.get((ours.get("team"), name))
        if not stats:
            continue
        for col, group, key in COMPARED:
            a, b = ours.get(col), (stats.get(group) or {}).get(key)
            if a is None or b is None or (isinstance(a, float) and math.isnan(a)):
                continue
            rows.append((name, col, float(a), float(b)))
    return rows


def summarise(samples):
    """samples: [(replay, name, col, ours, theirs)] -> {col: {n, r, bias, mae, worst}} (r is None if undefined)."""
    by_col = {}
    for sample in samples:
        by_col.setdefault(sample[2], []).append(sample)
    out = {}
    for col, rows in by_col.items():
        a = np.array([r[3] for r in rows])
        b = np.array([r[4] for r in rows])
        r = float(np.corrcoef(a, b)[0, 1]) if len(rows) >= 3 and a.std() > 0 and b.std() > 0 else None
        worst = sorted(rows, key=lambda r: -abs(r[3] - r[4]))[:OUTLIERS]
        out[col] = {"n": len(rows), "r": r, "bias": float((a - b).mean()), "mae": float(np.abs(a - b).mean()),
                    "worst": [(w[1], w[0], w[3], w[4]) for w in worst]}      # (name, replay, ours, theirs)
    return out


def goal_scorer_check(touches, goals):
    """(goals where the last toucher was the scorer, total goals). goals: [(scorer, time)] in replay time."""
    hits = 0
    for scorer, t in goals:
        before = touches[touches.time <= t]
        if not before.empty and before.player.iloc[-1] == scorer:
            hits += 1
    return hits, len(goals)


def shots_saves_check(touches, header_players):
    """Per player: do we have at least as many touches as header shots+saves? -> (ok, total, flagged names)."""
    counts = touches.groupby("player").size() if not touches.empty else {}
    ok, flagged = 0, []
    for p in header_players:
        have = int(counts.get(p.name, 0)) if len(counts) else 0
        if have >= p.shots + p.saves:
            ok += 1
        else:
            flagged.append(f"{p.name} ({have} touches, {p.shots} shots + {p.saves} saves)")
    return ok, len(header_players), flagged


def monotonic_check(table, stats=SKILL_UP, bands=None):
    """Adjacent rank bands (mode by mode) where a skill stat's median goes down instead of up.

    table: {mode: {band: {"stats": {stat: [p10..p90]}}}}. Returns [(mode, stat, ["Silver->Gold", ...])].
    """
    import benchmarks
    bands = bands or benchmarks.BANDS
    problems = []
    for mode, per_band in table.items():
        for stat in stats:
            medians = [(b, per_band[b]["stats"][stat][2]) for b in bands if stat in per_band.get(b, {}).get("stats", {})]
            dips = [f"{a}->{b}" for (a, x), (b, y) in zip(medians, medians[1:]) if y < x]
            if dips:
                problems.append((mode, stat, dips))
    return problems


def fmt_report(summary, scorer, shots, rate, replays):
    lines = [f"# Validation report ({replays} replays)", ""]
    if summary:
        lines += ["## A. Against ballchasing.com", "",
                  "| Stat | n | Correlation | Bias (ours - theirs) | Mean abs gap | |",
                  "|---|---|---|---|---|---|"]
        for col, s in sorted(summary.items(), key=lambda kv: (kv[1]["r"] is not None, kv[1]["r"] or 0)):
            flag = "" if s["r"] is not None and s["r"] >= TARGET_CORRELATION else "**check**"
            r = "n/a" if s["r"] is None else f"{s['r']:.3f}"
            lines.append(f"| {col} | {s['n']} | {r} | {s['bias']:+.2f} | {s['mae']:.2f} | {flag} |")
        lines += ["", "Worst gaps for stats under the target:"]
        for col, s in summary.items():
            if s["r"] is None or s["r"] < TARGET_CORRELATION:
                lines += [f"- {col}: {name} ours {ours:.1f} vs ballchasing {theirs:.1f} ({rid})"
                          for name, rid, ours, theirs in s["worst"]]
        lines.append("")
    lines += ["## B. Header checks", "",
              f"- Goal scorer was our last toucher: {scorer[0]}/{scorer[1]}",
              f"- Players with at least as many touches as shots+saves: {shots[0]}/{shots[1]}"]
    lines += [f"  - {f}" for f in shots[2][:20]]
    lines.append(f"- Touches/min outside {TOUCHES_PER_MIN}: {rate['bad']}/{rate['n']} player-games"
                 f" (median {rate['median']:.1f})")
    return "\n".join(lines) + "\n"


# ---- running it ----

def run(files, details_for):
    """files: [(replay_id, path)]. details_for(replay_id) -> ballchasing JSON or None."""
    from replay_library import analyse
    from touches import find_events

    samples, scorer, shots_ok, shots_total, flagged, rates, used = [], [0, 0], 0, 0, [], [], 0
    for replay_id, path in files:
        try:
            record, game = analyse(path)
            if record.error or game is None:
                continue
            ev = find_events(game)
        except Exception as e:
            print(f"  skipped {replay_id}: {e}")
            continue
        used += 1
        summary = record.summary
        detail = details_for(replay_id)
        if detail:
            samples += [(replay_id, *row) for row in pairs_for_replay(detail, record.players)]
        times = game.frames.time
        goals = [(g.scorer, float(times.iloc[g.frame])) for g in summary.goals if 0 <= g.frame < len(times)]
        hit, total = goal_scorer_check(ev.touches, goals)
        scorer[0] += hit
        scorer[1] += total
        ok, total, bad = shots_saves_check(ev.touches, [p for p in summary.players if not p.is_bot])
        shots_ok += ok
        shots_total += total
        flagged += [f"{replay_id}: {b}" for b in bad]
        rates += [p["touches_per_min"] for p in record.players.values() if p.get("touches_per_min") is not None]
        print(f"  analysed {used}/{len(files)}", end="\r")
    print()
    lo, hi = TOUCHES_PER_MIN
    rate = {"n": len(rates), "bad": sum(not lo <= r <= hi for r in rates),
            "median": float(np.median(rates)) if rates else float("nan")}
    return fmt_report(summarise(samples), tuple(scorer), (shots_ok, shots_total, flagged), rate, used)


def check_benchmarks():
    import benchmarks
    table = benchmarks._load().get("modes")
    if not table:
        sys.exit("No benchmarks.json yet (see README: Rank benchmarks).")
    problems = monotonic_check(table)
    for mode, stat, dips in problems:
        print(f"{mode} {stat}: median drops at {', '.join(dips)}")
    print("Medians rise with rank for every checked stat." if not problems else f"{len(problems)} stat(s) dip.")
    return 1 if problems else 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", action="append", choices=["1v1", "2v2", "3v3"], help="repeatable; default 2v2")
    parser.add_argument("--band", action="append", help="repeatable; default every band")
    parser.add_argument("--per-band", type=int, default=10, help="replays per rank band (default 10)")
    parser.add_argument("--offline", action="store_true", help="use only replays already in benchmark_cache/")
    parser.add_argument("--local", action="store_true", help="header checks on the replays in your replay folder")
    parser.add_argument("--benchmarks", action="store_true", help="check benchmarks.json and exit")
    parser.add_argument("--out", default=str(ROOT / "validation_report.md"))
    args = parser.parse_args()

    if args.benchmarks:
        sys.exit(check_benchmarks())

    import ballchasing as bc

    if args.local:
        folder = json.loads((ROOT / "config.json").read_text()).get("replay_dir")
        files = [(Path(p).stem, Path(p)) for p in sorted(Path(folder).glob("*.replay"))]

        def details_for(replay_id):
            return None
    elif args.offline:
        bc.CACHE.mkdir(exist_ok=True)
        files = [(p.stem, p) for p in sorted(bc.CACHE.glob("*.replay"))]

        def details_for(replay_id):
            path = bc.CACHE / f"{replay_id}.json"
            return json.loads(path.read_text()) if path.exists() else None
    else:
        token = bc.token_or_exit()
        files = []
        for mode in args.mode or ["2v2"]:
            for band in args.band or bc.RANK_IDS:
                for replay_id in bc.replay_ids(token, mode, band, args.per_band):
                    files.append((replay_id, bc.download(token, replay_id)))

        def details_for(replay_id):
            try:
                return bc.details(token, replay_id)
            except Exception as e:
                print(f"  no ballchasing stats for {replay_id}: {e}")
                return None

    if not files:
        sys.exit("No replays to check.")
    report = run(files, details_for)
    Path(args.out).write_text(report, encoding="utf-8")
    print(report)
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
