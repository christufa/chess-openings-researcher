import json
import re
import sqlite3

import pytest
from fastapi.testclient import TestClient
from test_pipeline import MemoryStore, config, execute_all

from openings_research.api import create_app
from openings_research.pipeline import Pipeline
from openings_research.schema import TABLES
from openings_research.serving import ResearchReader, StoreUnavailable


class SQLiteReader:
    def __init__(self, store):
        self.connection = sqlite3.connect(":memory:", check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        for table, ddl in TABLES.items():
            self.connection.execute(f"CREATE TABLE {table} ({ddl.replace('ARRAY<STRING>', 'TEXT')})")
            for row in store.read(table):
                values = [json.dumps(v) if isinstance(v, list) else v for v in row.values()]
                self.connection.execute(
                    f"INSERT INTO {table} ({','.join(row)}) VALUES ({','.join('?' for _ in row)})", values
                )

    def query(self, sql, parameters=()):
        # SQLite reverses Trino pagination syntax; preserve bind meaning explicitly.
        if "OFFSET ? LIMIT ?" in sql:
            sql = re.sub(r"OFFSET \? LIMIT \?", "LIMIT ? OFFSET ?", sql)
            parameters = (*parameters[:-2], parameters[-1], parameters[-2])
        return [
            dict(r)
            for r in self.connection.execute(sql.replace("research.openings_research.", ""), parameters)
        ]


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
    reader = SQLiteReader(store)
    with TestClient(create_app(ResearchReader(reader))) as client:
        yield client
    reader.connection.close()


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
