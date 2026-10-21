import pytest

from openings_research.iceberg import IcebergStore, spark_config


def test_catalog_requires_explicit_destination():
    with pytest.raises(ValueError):
        spark_config({})
    with pytest.raises(ValueError):
        spark_config({"OPENINGS_CATALOG_URI": "http://catalog/catalog"})
    conf = spark_config({"OPENINGS_LOCAL_WAREHOUSE": "file:///tmp/test"})
    assert conf["spark.sql.catalog.research.type"] == "hadoop"


def test_catalog_token_loaded_and_redacted(tmp_path):
    path = tmp_path / "token"
    path.write_text("test-token\n")
    conf = spark_config(
        {
            "OPENINGS_CATALOG_URI": "http://catalog/catalog",
            "OPENINGS_WAREHOUSE": "openings",
            "OPENINGS_CATALOG_TOKEN_FILE": str(path),
        }
    )
    assert conf["spark.sql.catalog.research.token"] == "test-token"
    assert "token" in conf["spark.redaction.regex"]


def test_iceberg_merge_cleanup_on_failure():
    class Frame:
        def createOrReplaceTempView(self, name):
            pass

    class Spark:
        catalog = None
        dropped = []

        def createDataFrame(self, *args, **kwargs):
            return Frame()

        def sql(self, statement):
            assert "MERGE INTO research.openings_research.sources" in statement
            raise RuntimeError("failed commit")

        def dropTempView(self, name):
            self.dropped.append(name)

    spark = Spark()
    spark.catalog = spark
    with pytest.raises(RuntimeError):
        IcebergStore(spark, "research", "openings_research").upsert(
            "sources", [{"source_id": "1", "url": "x"}]
        )
    assert len(spark.dropped) == 1
