import os
from pathlib import Path

import pyspark as _pyspark
from pyspark.sql import SparkSession

# Force PySpark to use its own bundled Spark JARs instead of any system SPARK_HOME
os.environ['SPARK_HOME'] = str(Path(_pyspark.__file__).parent)

def get_spark(app_name="pvc"):
    from .project import find_project_root
    warehouse_path = find_project_root() / "warehouse"

    spark = (
        SparkSession.builder
        .appName(app_name)
        .master("local[*]")
        .config("spark.driver.memory", "4g")
        # Downloads Iceberg runtime JAR from Maven on first run; cached in ~/.ivy2
        .config("spark.jars.packages", "org.apache.iceberg:iceberg-spark-runtime-4.0_2.13:1.10.1")
        .config("spark.sql.extensions",
                "org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions")
        .config("spark.sql.catalog.local", "org.apache.iceberg.spark.SparkCatalog")
        .config("spark.sql.catalog.local.type", "hadoop")
        .config("spark.sql.catalog.local.warehouse", str(warehouse_path))
        .config("spark.sql.ansi.enabled", "false")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("ERROR")
    return spark


def drop_namespace(spark, catalog, namespace):
    """Drop all tables in a namespace then drop the namespace itself.
    Iceberg's Hadoop catalog doesn't support CASCADE on DROP NAMESPACE."""
    try:
        tables = spark.sql(f"SHOW TABLES IN {catalog}.{namespace}").collect()
        for row in tables:
            spark.sql(f"DROP TABLE IF EXISTS {catalog}.{namespace}.{row.tableName}")
    except Exception:
        pass
    spark.sql(f"DROP NAMESPACE IF EXISTS {catalog}.{namespace}")
