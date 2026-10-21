"""Offline fixture integration: real Spark/Iceberg merges, repair and publication."""
import json

from pyspark.sql import SparkSession

from openings_research.agents import FixtureAgent
from openings_research.collectors import FixtureCollector
from openings_research.iceberg import IcebergStore, spark_config
from openings_research.pipeline import STAGES, Pipeline, provenance_config
from openings_research.review import FixtureReviewer

builder = SparkSession.builder.appName("openings-iceberg-smoke")
for key, value in spark_config({"OPENINGS_LOCAL_WAREHOUSE": "file:///tmp/research-smoke"}).items():
    builder = builder.config(key, value)
spark = builder.getOrCreate()
spark.sparkContext.setLogLevel("WARN")
try:
    store = IcebergStore(spark, "research", "openings_research")
    store.bootstrap()
    config = provenance_config(opening="__smoke_italian__", mode="refresh", source_run_id="",
                               agent="fixture", model="fixture", code_version="smoke")
    pipeline = Pipeline(store, "smoke-iceberg", config)
    for stage in STAGES:
        pipeline.execute(stage, collector=FixtureCollector(), agent=FixtureAgent(), reviewer=FixtureReviewer())
    counts = {t: len(store.read(t, run_id="smoke-iceberg")) for t in
              ["claims", "opening_lines", "claim_evidence", "candidate_reviews", "research_gaps"]}
    for stage in STAGES:
        pipeline.execute(stage)  # Completion markers must avoid every provider call.
    assert counts == {t: len(store.read(t, run_id="smoke-iceberg")) for t in counts}
    assert store.read("research_runs", run_id="smoke-iceberg")[0]["status"] == "completed"
    assert counts["claims"] > 0 and counts["opening_lines"] > 0
    assert len(store.sources_for_run("smoke-iceberg")) == 1
    assert json.loads(store.read("coverage_reports", run_id="smoke-iceberg")[0]["report_json"])["gaps"]
    print(json.dumps({"iceberg_smoke": "passed", "counts": counts}), flush=True)
finally:
    spark.stop()
