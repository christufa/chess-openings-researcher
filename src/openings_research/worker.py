"""Run all durable stages in one bounded Spark driver on Kubernetes."""

import argparse
import json
import os

from .agents import make_agent
from .collectors import FixtureCollector, TavilyCollector
from .iceberg import IcebergStore, spark_config
from .pipeline import STAGES, Pipeline, provenance_config
from .review import make_reviewer


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--opening", required=True)
    parser.add_argument("--agent", choices=["fixture", "openai"], default="openai")
    parser.add_argument("--mode", choices=["refresh", "reextract"], default="refresh")
    parser.add_argument("--source-run-id", default="")
    parser.add_argument("--model", default="gpt-4.1-mini")
    parser.add_argument("--review-model", default="gpt-4.1-mini")
    args = parser.parse_args()
    if args.mode == "reextract" and (not args.source_run_id or args.source_run_id == args.run_id):
        parser.error("Re-extraction requires a different source run ID")
    if args.agent == "fixture" and args.opening != "__smoke_italian__":
        parser.error("Fixture runs require the isolated smoke opening")
    from pyspark.sql import SparkSession

    builder = SparkSession.builder.appName("openings-research")
    for key, value in spark_config().items():
        builder = builder.config(key, value)
    spark = builder.getOrCreate()
    try:
        store = IcebergStore(spark, os.getenv("OPENINGS_CATALOG", "research"), "openings_research")
        store.bootstrap()
        config = provenance_config(
            **vars(args),
            code_version=os.environ.get("OPENINGS_CODE_VERSION", "local"),
            storage_backend="iceberg",
        )
        pipeline = Pipeline(store, args.run_id, config)

        class Collector:
            def collect(self, opening):
                return (
                    FixtureCollector()
                    if args.agent == "fixture"
                    else TavilyCollector(os.environ["TAVILY_API_KEY"], store, args.run_id)
                ).collect(opening)

        class Agent:
            def extract(self, request):
                return make_agent(args.agent, args.model, os.getenv("OPENAI_API_KEY", "")).extract(request)

        class Reviewer:
            def review(self, *items):
                return make_reviewer(args.agent, args.review_model, os.getenv("OPENAI_API_KEY", "")).review(
                    *items
                )

        for stage in STAGES:
            print(json.dumps({"event": "stage_started", "run_id": args.run_id, "stage": stage}), flush=True)
            try:
                pipeline.execute(stage, collector=Collector(), agent=Agent(), reviewer=Reviewer())
            except Exception as exc:
                raise RuntimeError(
                    f"Research stage {stage} failed ({type(exc).__name__}); inspect audit tables"
                ) from None
            print(json.dumps({"event": "stage_completed", "run_id": args.run_id, "stage": stage}), flush=True)
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
