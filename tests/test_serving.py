import pytest
from fastapi.testclient import TestClient
from test_pipeline import MemoryStore, config, execute_all

from openings_research.api import create_app
from openings_research.pipeline import Pipeline
from openings_research.schema import TABLES
from openings_research.serving import ArrowSQL, IcebergReader, ResearchReader, StoreUnavailable

ARROW_TYPES = {"STRING": "string", "BOOLEAN": "bool", "INT": "int32", "ARRAY<STRING>": "list<string>"}


def arrow_schema(table):
    import pyarrow as pa

    types = {"string": pa.string(), "bool": pa.bool_(), "int32": pa.int32(), "list<string>": pa.list_(pa.string())}
    columns = [column.split(" ", 1) for column in TABLES[table].split(", ")]
    return pa.schema([(name, types[ARROW_TYPES[kind]]) for name, kind in columns])


def arrow_tables(store):
    import pyarrow as pa

    return {table: pa.Table.from_pylist(store.read(table), schema=arrow_schema(table)) for table in TABLES}


def memory_reader(store):
    """The production SQL path (DuckDB over Arrow) on the in-memory pipeline output."""
    tables = arrow_tables(store)
    return ArrowSQL(tables.__getitem__)


@pytest.fixture
def client():
    store = MemoryStore()
    execute_all(Pipeline(store, "published", config()))
    # A later, partial write must not become current or be served by run ID.
    partial = {
        **store.read("research_runs")[0],
        "run_id": "partial",
        "status": "failed",
        "completed_at": "9999",
    }
    store.upsert("research_runs", [partial])
    store.upsert("claims", [{**store.read("claims")[0], "record_id": "partial", "run_id": "partial"}])
    with TestClient(create_app(ResearchReader(memory_reader(store)))) as client:
        yield client


def test_publication_boundary_and_history(client):
    item = client.get("/api/v1/openings").json()["items"][0]
    assert item["run_id"] == "published"
    assert len(client.get(f"/api/v1/openings/{item['opening_id']}/runs").json()["items"]) == 2
    assert client.get("/api/v1/runs/partial/claims").status_code == 404
    assert client.get("/api/v1/runs/partial/coverage").status_code == 404


def test_evidence_and_coverage(client):
    line = client.get("/api/v1/runs/published/lines").json()["items"][0]
    assert line["moves_san"] == ["e4", "e5", "Nf3", "Nc6", "Bc4"]
    claim = client.get("/api/v1/runs/published/claims").json()["items"][0]
    evidence = client.get(f"/api/v1/runs/published/evidence/{claim['candidate_id']}").json()["items"]
    assert evidence[0]["url"].startswith("fixture://")
    assert "White develops" in evidence[0]["excerpt"]
    assert client.get("/api/v1/runs/published/coverage").json()["report"]["published_claims"] == 1


def test_bounds_injection_and_read_only(client):
    assert client.get("/api/v1/openings?limit=101").status_code == 422
    assert client.get("/api/v1/openings?offset=-1").status_code == 422
    assert client.get("/api/v1/runs/' OR 1=1 --/claims").status_code == 404
    assert client.post("/api/v1/openings", json={}).status_code == 405
    assert client.get("/api/v1/openings?limit=1&offset=1").json()["items"] == []


def test_comparison(client):
    data = client.get("/api/v1/compare?before=published&after=published").json()
    assert data["claims"] == {"added": [], "removed": [], "retained": 1}
    assert client.get("/api/v1/compare?before=partial&after=published").status_code == 404


def test_static_explorer(client):
    assert "Openings Research" in client.get("/").text
    assert client.get("/app.js").status_code == 200
    assert client.get("/api/openapi.json").status_code == 200


def test_backend_error_does_not_leak_credentials():
    class Unavailable:
        def query(self, *args):
            raise StoreUnavailable("sensitive upstream exception")

    with TestClient(create_app(ResearchReader(Unavailable()))) as client:
        assert client.get("/healthz").status_code == 200
        response = client.get("/readyz")
        assert response.status_code == 503
        assert "sensitive" not in response.text


def test_namespace_validation():
    with pytest.raises(ValueError):
        ResearchReader(None, "research.openings;DROP")


def test_reads_a_real_iceberg_catalog_and_caches_by_snapshot(tmp_path):
    from pyiceberg.catalog.sql import SqlCatalog

    store = MemoryStore()
    execute_all(Pipeline(store, "published", config()))
    catalog = SqlCatalog("research", uri=f"sqlite:///{tmp_path}/catalog.db", warehouse=f"file://{tmp_path}")
    catalog.create_namespace("openings_research")
    for name, data in arrow_tables(store).items():
        catalog.create_table(("openings_research", name), schema=data.schema).append(data)
    iceberg = IcebergReader(catalog=catalog)
    with TestClient(create_app(ResearchReader(iceberg))) as client:
        assert client.get("/readyz").status_code == 200
        assert client.get("/api/v1/openings").json()["items"][0]["run_id"] == "published"
        line = client.get("/api/v1/runs/published/lines").json()["items"][0]
        assert line["moves_san"] == ["e4", "e5", "Nf3", "Nc6", "Bc4"]
        cached = iceberg._snapshots["research_runs"][1]
        client.get("/api/v1/openings")
        assert iceberg._snapshots["research_runs"][1] is cached  # unchanged snapshot: no rescan
        runs = catalog.load_table(("openings_research", "research_runs"))
        runs.append(arrow_tables(store)["research_runs"].slice(0, 0))  # empty commit, new snapshot
        client.get("/api/v1/openings")
        assert iceberg._snapshots["research_runs"][1] is not cached


def test_unreachable_catalog_is_not_ready(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENINGS_CATALOG_TOKEN_FILE", str(tmp_path / "missing-token"))
    with TestClient(create_app(ResearchReader(IcebergReader()))) as client:
        assert client.get("/readyz").status_code == 503
