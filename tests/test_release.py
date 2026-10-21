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
