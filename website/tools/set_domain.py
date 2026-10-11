"""Put your real domain into the website. Developer tool.

    python website/tools/set_domain.py rlanalyser.app

Search engines and link previews (Discord, Reddit, X) need absolute addresses in the page source, which a script on
the page can't provide, so the site ships with YOURDOMAIN as a placeholder in the canonical links, share tags, sitemap,
robots.txt and the support email. This replaces it everywhere. To change domain later, pass --from <old domain>.
"""

import argparse
import re
import sys
from pathlib import Path

SITE = Path(__file__).resolve().parent.parent
SUFFIXES = {".html", ".xml", ".txt", ".js", ".json"}
DOMAIN = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$", re.I)


def replace_domain(root, old, new):
    """Replace old with new in every text file under root. Returns the number of files changed."""
    changed = 0
    for path in root.rglob("*"):
        if path.suffix.lower() not in SUFFIXES or "tools" in path.relative_to(root).parts:
            continue
        text = path.read_text(encoding="utf-8")
        if old in text:
            path.write_text(text.replace(old, new), encoding="utf-8", newline="\n")
            changed += 1
    return changed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("domain", help="your domain, without https:// (for example rlanalyser.app)")
    ap.add_argument("--from", dest="old", default="YOURDOMAIN", help="the domain to replace (default: the placeholder)")
    args = ap.parse_args()
    if not DOMAIN.match(args.domain):
        sys.exit("Give just the domain name, like rlanalyser.app (no https://, no slashes).")
    print(f"Updated {replace_domain(SITE, args.old, args.domain)} files: {args.old} -> {args.domain}")


if __name__ == "__main__":
    main()
