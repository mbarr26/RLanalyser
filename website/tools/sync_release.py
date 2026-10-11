"""Copy a real release into the website's download page. Developer tool.

    python website/tools/sync_release.py --url https://github.com/<you>/<repo>/releases/download/v1.6.0/RLAnalyser-Setup-1.6.0.exe

Reads dist/release/latest.json (written by release.ps1) and writes website/assets/release.json: the version, size,
SHA-256, release date, notes and the public download address. The download page and every "Download" button read
that file, so the site can never drift from the real release.

Safety: a DEMO build (release.ps1 -Demo) lets anyone "pay" for Pro for free, so this refuses to publish one
unless you pass --allow-demo. The download address must be https.
Optionally pass --installer <path> to double-check the file you uploaded matches latest.json.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SITE = HERE.parent
DEFAULT_LATEST = SITE.parent / "dist" / "release" / "latest.json"
OUT = SITE / "assets" / "release.json"


class SyncError(Exception):
    pass


def build_release(manifest, url, allow_demo=False, installer=None):
    """The dict to write into release.json, or SyncError if it isn't safe to publish."""
    if not url.startswith("https://"):
        raise SyncError("The download address must start with https://")
    notes = str(manifest.get("notes", ""))
    if "demo" in notes.lower() and not allow_demo:
        raise SyncError("This release's notes mention DEMO: it is a demo build and must not be offered to the public. "
                        "Build a normal release (release.ps1 without -Demo), or pass --allow-demo if you really mean it.")
    for key in ("version", "sha256", "size"):
        if not manifest.get(key):
            raise SyncError(f"latest.json has no '{key}'")
    if installer:
        data = Path(installer).read_bytes()
        if hashlib.sha256(data).hexdigest() != manifest["sha256"] or len(data) != manifest["size"]:
            raise SyncError("The installer file does not match latest.json (checksum or size differs).")
    return {"version": manifest["version"], "url": url, "size": int(manifest["size"]), "sha256": manifest["sha256"],
            "released": manifest.get("released", ""), "notes": notes}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--latest", default=str(DEFAULT_LATEST), help="path to latest.json")
    ap.add_argument("--url", required=True, help="the public https address of the installer")
    ap.add_argument("--installer", help="optional: the installer file, to verify it matches latest.json")
    ap.add_argument("--allow-demo", action="store_true", help="publish even if the notes say DEMO (don't)")
    args = ap.parse_args()
    try:
        manifest = json.loads(Path(args.latest).read_text(encoding="utf-8-sig"))
        release = build_release(manifest, args.url, args.allow_demo, args.installer)
    except (OSError, ValueError, SyncError) as e:
        sys.exit(f"Not published: {e}")
    OUT.write_text(json.dumps(release, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {OUT}: version {release['version']}, {release['size'] / 1048576:.0f} MB")


if __name__ == "__main__":
    main()
