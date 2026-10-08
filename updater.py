"""In-app updates: find a newer release, download it, check it, and hand it to the installer.

A release is a small JSON manifest (`latest.json`) next to the installer:

    {"version": "1.2.0", "url": "RLAnalyser-Setup-1.2.0.exe", "sha256": "<64 hex>",
     "size": 49123456, "notes": "What's new.", "released": "2026-10-20"}

`url` may be absolute (https) or relative to the manifest's own location. The manifest can live
on a website (https) or, before there is one, in any local or network folder. The downloaded
installer is only ever run if its SHA-256 matches the manifest. This protects against corrupted
downloads and network tampering; it does not protect against a compromised host (that needs
signing, see README).

Pure Python, no UI: rl_analyser.py exposes it to the page.
"""

import hashlib
import os
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from paths import user_data
from version import APP_VERSION, UPDATE_URL

MANIFEST_NAME = "latest.json"
MANIFEST_MAX_BYTES = 64 * 1024
INSTALLER_MAX_BYTES = 2 << 30          # sanity limit for the installer
NOTES_MAX_CHARS = 4000
TIMEOUT = 10                           # seconds, for connecting and for each read
LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")
USER_AGENT = f"RLAnalyser/{APP_VERSION}"

_VERSION_RE = re.compile(r"^\d+(\.\d+){0,3}$")
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_INSTALLER_RE = re.compile(r"^RLAnalyser-Setup-(\d+(?:\.\d+){0,3})\.exe(\.part)?$")


class UpdateError(Exception):
    """A problem with finding or fetching an update, worded for the user."""


class UpdateCancelled(UpdateError):
    pass


@dataclass
class UpdateInfo:
    version: str
    url: str        # absolute https URL, or an absolute local path / file URL
    sha256: str
    size: int | None
    notes: str
    released: str


# ---------- versions ----------

def parse_version(text):
    """'1.10.2' -> (1, 10, 2, 0). Always four parts so 1.1 == 1.1.0."""
    if not isinstance(text, str) or not _VERSION_RE.match(text.strip()):
        raise UpdateError(f"The update information has an invalid version number: {text!r}")
    parts = [int(p) for p in text.strip().split(".")]
    return tuple(parts + [0] * (4 - len(parts)))


def is_newer(candidate, current=APP_VERSION):
    return parse_version(candidate) > parse_version(current)


# ---------- where to look ----------

def update_source(config_value=None):
    """The manifest location: env var RLA_UPDATE_URL, else the config.json value, else the
    built-in UPDATE_URL. None when no source is set up."""
    for value in (os.environ.get("RLA_UPDATE_URL"), config_value, UPDATE_URL):
        if value and value.strip():
            return value.strip()
    return None


def _scheme(text):
    return urllib.parse.urlparse(text).scheme.lower() if "://" in text else ""


def _is_remote(source):
    return _scheme(source) in ("http", "https")


def _check_remote_url(url):
    """Remote downloads must be https (http is only allowed to this machine, for testing)."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme == "https":
        return
    if parsed.scheme == "http" and (parsed.hostname or "") in LOCAL_HOSTS:
        return
    raise UpdateError("Updates must be downloaded over https, so this address was refused.")


def _local_path(source):
    """A local/network path or file:// URL as a Path."""
    if _scheme(source) == "file":
        parsed = urllib.parse.urlparse(source)
        path = urllib.request.url2pathname(parsed.path)
        if parsed.netloc and parsed.netloc.lower() != "localhost":
            path = "\\\\" + parsed.netloc + path          # file://server/share/... -> \\server\share\...
        return Path(path)
    return Path(source)


def _open_remote(url):
    """Open an https URL, refusing any redirect that ends up somewhere that isn't https."""
    _check_remote_url(url)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        resp = urllib.request.urlopen(request, timeout=TIMEOUT)
    except urllib.error.HTTPError as e:
        raise UpdateError(f"The update server answered with an error ({e.code}).") from e
    except (urllib.error.URLError, OSError) as e:
        raise UpdateError(f"Couldn't reach the update server ({getattr(e, 'reason', e)}).") from e
    try:
        _check_remote_url(resp.geturl())
    except UpdateError:
        resp.close()
        raise
    return resp


# ---------- the manifest ----------

def _read_manifest(source):
    """(manifest dict, base) where base is what a relative `url` is resolved against."""
    import json

    if _is_remote(source):
        with _open_remote(source) as resp:
            raw = resp.read(MANIFEST_MAX_BYTES + 1)
        base = source
    else:
        path = _local_path(source)
        if path.is_dir():
            path = path / MANIFEST_NAME
        try:
            if path.stat().st_size > MANIFEST_MAX_BYTES:
                raise UpdateError("The update information file is unexpectedly large.")
            raw = path.read_bytes()
        except FileNotFoundError as e:
            raise UpdateError(f"Couldn't find the update information at {path}.") from e
        except OSError as e:
            raise UpdateError(f"Couldn't read the update information ({e}).") from e
        base = str(path)
    if len(raw) > MANIFEST_MAX_BYTES:
        raise UpdateError("The update information is unexpectedly large.")
    try:
        manifest = json.loads(raw.decode("utf-8-sig"))
    except (ValueError, UnicodeDecodeError) as e:
        raise UpdateError("The update information couldn't be read (it isn't valid JSON).") from e
    if not isinstance(manifest, dict):
        raise UpdateError("The update information is in an unexpected format.")
    return manifest, base


def _resolve_url(url, base, remote):
    if not isinstance(url, str) or not url.strip():
        raise UpdateError("The update information doesn't say where to download the update.")
    url = url.strip()
    scheme = urllib.parse.urlparse(url).scheme.lower()
    if remote:
        # A website's manifest may only point at https downloads (never a file on this PC)
        if scheme not in ("", "http", "https"):
            raise UpdateError("The update information points somewhere that isn't allowed.")
        resolved = urllib.parse.urljoin(base, url)
        _check_remote_url(resolved)
        return resolved
    if scheme in ("http", "https"):
        _check_remote_url(url)
        return url
    if scheme == "file":
        return str(_local_path(url))
    path = Path(url)
    return str(path if path.is_absolute() else Path(base).parent / path)


def parse_manifest(manifest, base, remote):
    """Validate a manifest dict into an UpdateInfo (raises UpdateError with a clear message)."""
    version = manifest.get("version")
    parse_version(version)
    sha256 = manifest.get("sha256")
    if not isinstance(sha256, str) or not _SHA256_RE.match(sha256.strip()):
        raise UpdateError("The update information is missing a valid checksum, so the update was refused.")
    size = manifest.get("size")
    if size is not None and (not isinstance(size, int) or isinstance(size, bool) or not 0 < size <= INSTALLER_MAX_BYTES):
        raise UpdateError("The update information has an invalid file size.")
    notes = manifest.get("notes", "")
    released = manifest.get("released", "")
    return UpdateInfo(
        version=version.strip(),
        url=_resolve_url(manifest.get("url"), base, remote),
        sha256=sha256.strip().lower(),
        size=size,
        notes=notes[:NOTES_MAX_CHARS] if isinstance(notes, str) else "",
        released=released[:40] if isinstance(released, str) else "",
    )


def check(source):
    """The newer release described at `source`, or None if this version is current."""
    manifest, base = _read_manifest(source)
    info = parse_manifest(manifest, base, _is_remote(source))
    return info if is_newer(info.version) else None


# ---------- downloading ----------

def updates_dir():
    return user_data("updates")


def download(info, on_progress=None, cancel=None):
    """Fetch the installer into the updates folder and return its path once it is verified.

    on_progress(done, total, phase) is called while downloading. The file is checked against
    the manifest's SHA-256 (and size, if given); a mismatch deletes it and raises UpdateError.
    """
    folder = updates_dir()
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"RLAnalyser-Setup-{info.version}.exe"
    part = target.with_name(target.name + ".part")
    last_report = 0.0

    def report(done, total):
        nonlocal last_report
        now = time.monotonic()
        if on_progress and (now - last_report > 0.2 or done >= total):
            last_report = now
            on_progress(done, total, "download")

    digest, done = hashlib.sha256(), 0
    remote = urllib.parse.urlparse(info.url).scheme in ("http", "https")
    try:
        source = _open_remote(info.url) if remote else open(_local_path(info.url), "rb")
    except FileNotFoundError as e:
        raise UpdateError("The update file couldn't be found where the update information says it is.") from e
    except OSError as e:
        raise UpdateError(f"Couldn't open the update file ({e}).") from e

    try:
        with source:
            total = info.size or int(getattr(source, "headers", {}).get("Content-Length", 0) or 0)
            if not total and not remote:
                total = os.path.getsize(_local_path(info.url))
            total = total or 1
            with open(part, "wb") as out:
                while chunk := source.read(1 << 20):
                    if cancel and cancel.is_set():
                        raise UpdateCancelled("Update cancelled")
                    done += len(chunk)
                    if done > INSTALLER_MAX_BYTES or (info.size and done > info.size):
                        raise UpdateError("The update file is larger than expected, so it was refused.")
                    try:
                        out.write(chunk)
                    except OSError as e:
                        raise UpdateError(f"Couldn't save the update (is the disk full?): {e}") from e
                    digest.update(chunk)
                    report(done, max(total, done))
    except UpdateError:
        part.unlink(missing_ok=True)
        raise
    except OSError as e:   # includes a dropped connection
        part.unlink(missing_ok=True)
        raise UpdateError(f"The download was interrupted ({getattr(e, 'reason', e)}). Please try again.") from e

    if (info.size and done != info.size) or digest.hexdigest() != info.sha256:
        part.unlink(missing_ok=True)
        raise UpdateError("The downloaded update was damaged (it doesn't match its checksum), so it wasn't installed. Please try again.")
    os.replace(part, target)
    if on_progress:
        on_progress(done, done, "download")
    return target


# ---------- installing ----------

def launch_installer(path):
    """Start the installer detached from this process. The caller should exit right after.

    /SILENT shows only a progress window; /CLOSEAPPLICATIONS lets Setup close a stray copy of
    the app; the installer relaunches the new version itself (see installer/RLAnalyser.iss).
    """
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    try:
        subprocess.Popen(
            [str(path), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"],
            creationflags=flags, close_fds=True,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except OSError as e:
        raise UpdateError(f"Couldn't start the installer ({e}). It was saved at {path}") from e


def cleanup_old():
    """Delete installers from earlier updates (and half-finished downloads). Best effort."""
    try:
        for item in updates_dir().iterdir():
            match = _INSTALLER_RE.match(item.name)
            if match and (match.group(2) or not is_newer(match.group(1))):
                item.unlink(missing_ok=True)
    except (OSError, UpdateError):
        pass
