"""Forget any test sign-in: the saved session in the Windows Credential Manager and the cached plan in config.json.

Run by try_accounts.bat before and after a pretend-account session, so a test account never lingers (a leftover
session would point at a service that has forgotten it, and a cached "Pro" would be stale). Safe to run any time:
it only removes the sign-in and the cached plan, never replays, caches or your other settings.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from account import KEYRING_SERVICE, KEYRING_USER  # noqa: E402
from paths import user_data  # noqa: E402


def main():
    try:
        import keyring
        keyring.delete_password(KEYRING_SERVICE, KEYRING_USER)
    except Exception:
        pass                                   # nothing saved, or no secure store: nothing to forget
    path = user_data("config.json")
    try:
        config = json.loads(path.read_text())
    except (OSError, ValueError):
        return
    if config.pop("entitlement", None) is not None:
        path.write_text(json.dumps(config, indent=2))


if __name__ == "__main__":
    main()
