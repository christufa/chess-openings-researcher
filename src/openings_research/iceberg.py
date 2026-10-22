"""Iceberg persistence for bounded research records; never reads the games lake."""

import os
import uuid
from pathlib import Path

from .schema import KEYS, TABLES
from .storage import DeltaStore, identifier


class IcebergStore(DeltaStore):
    def bootstrap(self):
        self.spark.sql(f"CREATE NAMESPACE IF NOT EXISTS {self.namespace}")
        for name, ddl in TABLES.items():
            self.spark.sql(
                f"CREATE TABLE IF NOT EXISTS {self.table(name)} ({ddl}) USING iceberg "
                "TBLPROPERTIES ('format-version'='2')"
            )
        # Serving queries resolve completed runs themselves. Do not rely on
        # Spark-specific views being readable through a different query engine.

    def upsert(self, name, rows):
        table = self.table(name)
        if not rows:
            return
        key = KEYS[name]
        unique = {}
        for row in rows:
            if row[key] in unique and unique[row[key]] != row:
                raise ValueError(f"Conflicting duplicate key in {name}")
            unique[row[key]] = row
        frame = self.spark.createDataFrame(list(unique.values()), schema=TABLES[name])
        view = f"research_merge_{uuid.uuid4().hex}"
        frame.createOrReplaceTempView(view)
        try:
            self.spark.sql(
                f"MERGE INTO {table} t USING {view} s ON t.{key} = s.{key} "
                "WHEN MATCHED THEN UPDATE SET * WHEN NOT MATCHED THEN INSERT *"
            )
        finally:
            self.spark.catalog.dropTempView(view)


def spark_config(env=None):
    env = os.environ if env is None else env
    catalog = identifier(env.get("OPENINGS_CATALOG", "research"))
    prefix = f"spark.sql.catalog.{catalog}"
    settings = {
        "spark.sql.extensions": "org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions",
        prefix: "org.apache.iceberg.spark.SparkCatalog",
        "spark.ui.enabled": "false",
        "spark.sql.shuffle.partitions": "2",
        "spark.redaction.regex": "(?i)secret|password|token|access[.]?key|credential",
    }
    if env.get("OPENINGS_LOCAL_WAREHOUSE"):
        settings.update({f"{prefix}.type": "hadoop", f"{prefix}.warehouse": env["OPENINGS_LOCAL_WAREHOUSE"]})
    else:
        uri = env.get("OPENINGS_CATALOG_URI", "")
        if not uri.startswith(("https://", "http://")):
            raise ValueError("OPENINGS_CATALOG_URI must be an explicit REST catalog URL")
        warehouse = env.get("OPENINGS_WAREHOUSE")
        if not warehouse:
            raise ValueError("OPENINGS_WAREHOUSE must explicitly select the research warehouse")
        settings.update(
            {
                f"{prefix}.type": "rest",
                f"{prefix}.uri": uri,
                f"{prefix}.warehouse": warehouse,
                f"{prefix}.header.X-Iceberg-Access-Delegation": "vended-credentials",
            }
        )
        if env.get("OPENINGS_FILE_IO"):
            settings[f"{prefix}.io-impl"] = env["OPENINGS_FILE_IO"]
        token_file = env.get("OPENINGS_CATALOG_TOKEN_FILE")
        if token_file:
            settings[f"{prefix}.token"] = Path(token_file).read_text().strip()
    return settings
