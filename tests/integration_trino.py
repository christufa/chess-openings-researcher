"""Explicit integration command against a disposable LOCAL Trino memory catalog."""

import json

from fastapi.testclient import TestClient
from test_pipeline import MemoryStore, config, execute_all
from trino.dbapi import connect

from openings_research.api import create_app
from openings_research.pipeline import Pipeline
from openings_research.schema import TABLES
from openings_research.serving import ResearchReader


class LocalTrino:
    def query(self, sql, parameters=()):
        conn = connect(host="127.0.0.1", port=18081, user="openings-test", http_scheme="http")
        try:
            cursor = conn.cursor()
            cursor.execute(sql, list(parameters)) if parameters else cursor.execute(sql)
            rows = cursor.fetchall()
            return [dict(zip([c[0] for c in cursor.description], row, strict=True)) for row in rows]
        finally:
            conn.close()


if __name__ == "__main__":
    db = LocalTrino()
    db.query("CREATE SCHEMA memory.openings_research")
    store = MemoryStore()
    execute_all(Pipeline(store, "fixture", config()))
    for table, ddl in TABLES.items():
        ddl = ddl.replace("ARRAY<STRING>", "ARRAY(VARCHAR)").replace("STRING", "VARCHAR")
        db.query(f"CREATE TABLE memory.openings_research.{table} ({ddl})")
        for row in store.read(table):
            db.query(
                f"INSERT INTO memory.openings_research.{table} ({','.join(row)}) "
                f"VALUES ({','.join('?' for _ in row)})",
                tuple(row.values()),
            )
    with TestClient(create_app(ResearchReader(db, "memory.openings_research"))) as client:
        opening = client.get("/api/v1/openings").json()["items"][0]
        assert client.get("/api/v1/openings?offset=1").json()["items"] == []
        assert client.get(f"/api/v1/openings/{opening['opening_id']}/runs").status_code == 200
        claims = client.get("/api/v1/runs/fixture/claims").json()["items"]
        assert len(claims) == 1
        line = client.get("/api/v1/runs/fixture/lines").json()["items"][0]
        assert line["moves_san"][-1] == "Bc4"
        assert (
            len(client.get(f"/api/v1/runs/fixture/evidence/{claims[0]['candidate_id']}").json()["items"]) == 1
        )
        assert client.get("/api/v1/runs/fixture/coverage").json()["report"]["published_claims"] == 1
        assert client.get("/api/v1/compare?before=fixture&after=fixture").json()["claims"]["retained"] == 1
    print(json.dumps({"trino_integration": "passed"}))
