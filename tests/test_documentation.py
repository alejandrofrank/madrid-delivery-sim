"""The architecture reader exposes reviewed sources, never an arbitrary file browser."""

import hashlib
import json
import runpy
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from delivery import documentation
from delivery.api import app

ROOT = Path(__file__).resolve().parents[1]


def test_reference_loads_without_database_or_provider_access(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Documentation must not access simulation or cloud state")

    monkeypatch.setattr("delivery.db.connect", forbidden)
    client = TestClient(app)
    assert client.get("/architecture").status_code == 200
    assert "Swagger UI" in client.get("/docs").text
    response = client.get("/api/documentation")
    assert response.status_code == 200
    body = response.json()
    ids = [page["id"] for page in body["pages"]]
    assert len(ids) == len(set(ids)) == 18
    assert {"overview", "decisions", "capabilities", "enterprise-gcp", "memory"} <= set(ids)
    assert all(page["body"].startswith("# ") for page in body["pages"])
    assert "source_fingerprint" not in body  # Reference review is not a live health receipt.


def test_every_catalogued_source_is_readable_in_the_application_image():
    manifest = documentation.catalogue()
    allowed = manifest["sources"] + manifest["supplementary"]
    client = TestClient(app)
    for path in allowed:
        response = client.get("/api/documentation/source", params={"path": path})
        assert response.status_code == 200, path
        assert response.json()["path"] == path
        assert response.json()["text"] == (ROOT / path).read_text(encoding="utf-8-sig")


@pytest.mark.parametrize(
    "path",
    [
        ".env",
        ".env.jev",
        "data/local/private.csv",
        "infra/gcp-ai/terraform.tfstate",
        "infra/gcp-ai/private.tfvars",
        "infra/gcp-ai/private.tfplan",
        "../README.md",
        "/etc/passwd",
        "src/delivery/../../.env",
        "docs/../.env",
        "README.md/../.env",
        "C:/Users/aleja/.config/gcloud/application_default_credentials.json",
    ],
)
def test_private_and_traversal_sources_are_denied(path):
    response = TestClient(app).get("/api/documentation/source", params={"path": path})
    assert response.status_code == 404
    assert response.json() == {"detail": "Unknown documentation source"}


def test_source_reader_rejects_symlinks_escapes_and_oversized_files(tmp_path, monkeypatch):
    monkeypatch.setattr(documentation, "ROOT", tmp_path)
    public = tmp_path / "public"
    public.mkdir()
    (tmp_path / ".env").write_text("private", encoding="utf-8")
    (public / "direct.py").symlink_to(tmp_path / ".env")
    (tmp_path / "alias").symlink_to(public, target_is_directory=True)
    (public / "large.py").write_bytes(b"x" * (documentation.MAX_SOURCE_BYTES + 1))
    for path in ("public/direct.py", "alias/direct.py", "../outside", "public/large.py"):
        with pytest.raises(HTTPException) as error:
            documentation.read_public_file(path)
        assert error.value.status_code == 404


def test_documentation_assets_are_local_and_integrity_pinned():
    html = (ROOT / "web/documentation.html").read_text(encoding="utf-8")
    assert 'src="https://' not in html and 'href="https://' not in html
    assert 'src="http://' not in html and 'href="http://' not in html
    directory = ROOT / "web/vendor/documentation"
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    assert {package["name"] for package in manifest["packages"]} == {
        "marked",
        "dompurify",
        "@mermaid-js/tiny",
    }
    for package in manifest["packages"]:
        assert package["integrity"].startswith("sha512-")
        for file in package["files"]:
            assert (
                hashlib.sha256((directory / file["path"]).read_bytes()).hexdigest()
                == file["sha256"]
            )


def test_reviewed_links_match_the_explicit_source_catalogue():
    checker = runpy.run_path(str(ROOT / "scripts/check_documentation.py"))
    manifest = documentation.catalogue()
    assert checker["linked_sources"](manifest) == set(manifest["sources"])
    assert all(checker["public_source"](path) for path in manifest["sources"])
