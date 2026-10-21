import copy

import pytest

from openings_research.release import application

API = "openingsprod.azurecr.io/openings-api@sha256:" + "a" * 64
WORKER = "openingsprod.azurecr.io/openings-worker@sha256:" + "b" * 64
SETTINGS = {"catalogUri": "https://lakekeeper.catalog.svc/catalog", "trinoHost": "trino.trino.svc"}


def test_release_keeps_images_and_source_in_one_reviewed_manifest():
    result = application("c" * 40, API, WORKER, SETTINGS)
    source = result["spec"]["source"]
    assert source["targetRevision"] == "c" * 40
    assert source["helm"]["valuesObject"]["workerImage"] == WORKER
    assert source["helm"]["valuesObject"]["apiImage"] == API
    assert "automated" not in result["spec"]["syncPolicy"]


@pytest.mark.parametrize("revision", ["main", "abc123", "v1.0", "a" * 40 + "; echo unsafe"])
def test_reject_mutable_or_partial_revisions(revision):
    with pytest.raises(ValueError):
        application(revision, API, WORKER, SETTINGS)


@pytest.mark.parametrize("image", ["openingsprod.azurecr.io/openings-api:latest", WORKER,
                                    API.replace("openingsprod", "otherregistry")])
def test_reject_wrong_images(image):
    with pytest.raises(ValueError):
        application("c" * 40, image, WORKER, SETTINGS)


@pytest.mark.parametrize("uri", ["http://catalog.svc/catalog", "https://user:password@catalog.svc",
                                  "https://catalog.svc?token=secret", "https://catalog.svc#secret"])
def test_reject_unsafe_catalog_settings(uri):
    values = copy.copy(SETTINGS)
    values["catalogUri"] = uri
    with pytest.raises(ValueError):
        application("c" * 40, API, WORKER, values)


def test_reject_secret_in_release_values():
    with pytest.raises(ValueError):
        application("c" * 40, API, WORKER, {**SETTINGS, "OPENAI_API_KEY": "secret"})

PLATFORM = {
    "catalogClientId": "00000000-0000-4000-8000-000000000001",
    "backupClientId": "00000000-0000-4000-8000-000000000002",
    "secretsClientId": "00000000-0000-4000-8000-000000000003",
    "tenantId": "00000000-0000-4000-8000-000000000004",
    "storageAccount": "openingsfixture", "vaultName": "openings-fixture",
    "aksIssuer": "https://eastus2.oic.prod-aks.azure.com/tenant/cluster/",
}


def test_coordinated_data_release_has_same_source_and_signed_bridge(tmp_path):
    from openings_research.release import data_applications, write_release
    data = data_applications("c" * 40, API, PLATFORM)
    assert set(data) == {"catalog", "query"}
    for name, manifest in data.items():
        spec = manifest["spec"]
        assert spec["source"]["targetRevision"] == "c" * 40
        assert spec["destination"]["namespace"] == "openings-" + name
        assert "automated" not in spec["syncPolicy"]
    assert data["query"]["spec"]["source"]["helm"]["valuesObject"]["bridgeImage"] == API
    write_release(tmp_path, {**data, "research": application("c" * 40, API, WORKER, SETTINGS)})
    text = (tmp_path / "kustomization.yaml").read_text()
    assert all("- " + name + ".json" in text for name in ("catalog", "query", "research"))
    with pytest.raises(ValueError):
        write_release(tmp_path, {"research": {}})
    assert (tmp_path / "kustomization.yaml").read_text() == text


@pytest.mark.parametrize("changes", [
    {"clientSecret": "secret"}, {"backupClientId": "not-an-id"},
    {"aksIssuer": "https://attacker.invalid/"},
    {"aksIssuer": "https://user:secret@eastus2.oic.prod-aks.azure.com/t/c/"},
    {"storageAccount": "account/../other"}, {"vaultName": "vault?secret"},
])
def test_platform_rejects_secrets_and_unsafe_identifiers(changes):
    from openings_research.release import data_applications
    with pytest.raises(ValueError):
        data_applications("c" * 40, API, {**PLATFORM, **changes})


def test_release_does_not_overwrite_custom_kustomization(tmp_path):
    from openings_research.release import write_release
    original = "resources:\n  - custom.yaml\n"
    (tmp_path / "kustomization.yaml").write_text(original)
    with pytest.raises(ValueError):
        write_release(tmp_path, {"research": {}})
    assert (tmp_path / "kustomization.yaml").read_text() == original
    assert not (tmp_path / "research.json").exists()


def test_cli_rejects_mismatched_runtime_before_fetch(tmp_path, monkeypatch):
    import json
    import sys

    from openings_research.release import main
    runtime = tmp_path / "runtime.json"
    platform = tmp_path / "platform.json"
    runtime.write_text(json.dumps(SETTINGS))
    platform.write_text(json.dumps(PLATFORM))
    monkeypatch.setattr(sys, "argv", ["release", "--revision", "c" * 40, "--api-image", API,
                                     "--worker-image", WORKER, "--values", str(runtime),
                                     "--platform-values", str(platform)])
    with pytest.raises(ValueError, match="coordinated private platform"):
        main()
