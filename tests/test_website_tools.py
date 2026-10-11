import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "website" / "tools"))

import set_domain  # noqa: E402
import sync_release  # noqa: E402

GOOD = {"version": "1.6.0", "url": "RLAnalyser-Setup-1.6.0.exe", "sha256": "ab" * 32, "size": 12345,
        "released": "2026-11-01", "notes": "Real accounts and payments."}
URL = "https://github.com/me/repo/releases/download/v1.6.0/RLAnalyser-Setup-1.6.0.exe"


def test_a_normal_release_is_published():
    rel = sync_release.build_release(GOOD, URL)
    assert rel == {"version": "1.6.0", "url": URL, "size": 12345, "sha256": "ab" * 32,
                   "released": "2026-11-01", "notes": "Real accounts and payments."}


def test_a_demo_build_is_refused_unless_forced():
    demo = dict(GOOD, notes="DEMO BUILD: pretend accounts and payments")
    with pytest.raises(sync_release.SyncError, match="demo build"):
        sync_release.build_release(demo, URL)
    assert sync_release.build_release(demo, URL, allow_demo=True)["version"] == "1.6.0"


def test_only_https_download_links_are_allowed():
    with pytest.raises(sync_release.SyncError):
        sync_release.build_release(GOOD, "http://example.com/setup.exe")
    with pytest.raises(sync_release.SyncError):
        sync_release.build_release(GOOD, "RLAnalyser-Setup.exe")


def test_incomplete_manifest_is_refused():
    with pytest.raises(sync_release.SyncError, match="sha256"):
        sync_release.build_release({k: v for k, v in GOOD.items() if k != "sha256"}, URL)


def test_installer_is_checked_against_the_manifest(tmp_path):
    exe = tmp_path / "setup.exe"
    exe.write_bytes(b"hello installer")
    manifest = dict(GOOD, sha256=hashlib.sha256(b"hello installer").hexdigest(), size=len(b"hello installer"))
    assert sync_release.build_release(manifest, URL, installer=exe)["size"] == len(b"hello installer")
    exe.write_bytes(b"tampered")
    with pytest.raises(sync_release.SyncError, match="does not match"):
        sync_release.build_release(manifest, URL, installer=exe)


def test_set_domain_replaces_the_placeholder_everywhere_but_the_tools(tmp_path):
    (tmp_path / "tools").mkdir()
    (tmp_path / "index.html").write_text('<link rel="canonical" href="https://YOURDOMAIN/">', encoding="utf-8")
    (tmp_path / "sitemap.xml").write_text("<loc>https://YOURDOMAIN/download.html</loc>", encoding="utf-8")
    (tmp_path / "site.config.js").write_text('supportEmail: "support@YOURDOMAIN"', encoding="utf-8")
    (tmp_path / "tools" / "set_domain.py").write_text("YOURDOMAIN", encoding="utf-8")
    (tmp_path / "logo.png").write_bytes(b"YOURDOMAIN")
    assert set_domain.replace_domain(tmp_path, "YOURDOMAIN", "rlanalyser.app") == 3
    assert "https://rlanalyser.app/" in (tmp_path / "index.html").read_text()
    assert "support@rlanalyser.app" in (tmp_path / "site.config.js").read_text()
    assert (tmp_path / "tools" / "set_domain.py").read_text() == "YOURDOMAIN"      # the tool itself is left alone
    assert (tmp_path / "logo.png").read_bytes() == b"YOURDOMAIN"                   # binary files are never touched


def test_domain_validation():
    assert set_domain.DOMAIN.match("rlanalyser.app")
    assert set_domain.DOMAIN.match("play.rl-analyser.co.uk")
    assert not set_domain.DOMAIN.match("https://rlanalyser.app")
    assert not set_domain.DOMAIN.match("rlanalyser.app/path")
    assert not set_domain.DOMAIN.match("nodot")
