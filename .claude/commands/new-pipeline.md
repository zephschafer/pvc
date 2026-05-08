You are helping the user create a new pvc pipeline. pvc is a YAML-driven data ingestion framework that writes to a local Apache Iceberg data lake.

Follow these steps in order. Do not skip ahead — each step informs the next.

---

## 1. Understand the data source

Ask the user (or use context already provided):
- What data do they want to ingest?
- What is the source? (REST API, website to scrape, file, etc.)
- Do they have API docs or a sample URL?

## 2. Probe the API before writing any code

Before designing the pipeline, make a real request to understand the response shape. This determines which source type to use and how the scraper needs to work.

```python
import requests
resp = requests.get("https://example.com/api/data", params={...})
print(resp.json())
```

Key questions to answer:
- Does the response contain a flat array of records? → `type: http` with `records_path`
- Does it return parallel arrays (e.g. `{"time": [...], "value": [...]}`)? → `type: python` to reshape
- Does it require pagination, HTML parsing, or multi-step auth? → `type: python`
- What fields are available and what are their names exactly?

## 3. Reference existing pipelines

Use `list_pipelines` to see what already exists. Use `get_pipeline` on the most structurally similar one as a reference.

## 4. Choose source type and design the pipeline

**`type: http`** — for REST APIs that return a clean records array (JSON or CSV). pvc constructs the request and parses the response automatically.

**`type: python`** — for anything requiring custom logic: response reshaping, HTML scraping, pagination that depends on response content, multi-step auth. Write a function in `connectors/` that receives params and returns `list[dict]`.

### For `type: python`: design the scraper function

The function signature is always:
```python
def fetch_data(dynamic_params: dict) -> list[dict]:
    ...
```

`dynamic_params` contains ALL params: both iterate values (e.g. `city=portland`) and static params from the YAML (e.g. `start_date`, `max_records`). The function is responsible for the full fetch-and-return cycle for one iteration.

Important: pvc passes static param values as-is from the YAML. If the YAML has `value: "today"`, the function receives the literal string `"today"` — it does not get resolved to a date. Handle this in the function:
```python
if end_date == "today":
    end_date = date.today().isoformat()
```

### Choose a build strategy

- **`incremental` + `primary_key`** — upsert by key. Each run updates existing rows and inserts new ones. Good for records that change over time (permits, weather observations). Re-running the same date range should produce the same final row count.
- **`append`** — snapshot each run. Good for listings, prices, events where you want a time series.
- **`full_refresh`** — replace the whole table on each run.

### Iteration design

Each iterate axis loops over one param. Multiple axes produce a cartesian product:
- `date_range` — iterates over time windows (only for `type: http`)
- `categorical` — iterates over a list of values (works for both types)

For `type: python` pipelines that span a date range, pass `start_date` and `end_date` as **static params** (not iterate axes) and let the scraper fetch the full range in one call per iteration. This is simpler than iterating over dates.

## 5. Write the files

For `type: python` pipelines, write the scraper first so you can test the fetch logic in isolation before wiring it into pvc:
1. Use `write_connector` to save `connectors/{name}.py`
2. Quickly verify the scraper returns sensible data for one iteration by calling it directly
3. Use `write_pipeline` to save `pipelines/{name}.yml`
4. Run `validate_pipeline` — fix any errors before proceeding

## 6. Test with a small run

Use `run_pipeline` with `limit=1` to run only the first iteration, and small params to limit data volume:

```
run_pipeline("my_pipeline", limit=1, params={"max_records": 5, "end_date": "2024-01-07"})
```

Watch for:
- Fetch errors (auth, URL, response format)
- Schema projection errors (wrong column paths — check the exact field names from step 2)
- Write errors

## 7. Verify the data

Use `query_warehouse` to confirm the data looks right:

```sql
SELECT * FROM my_pipeline.my_pipeline LIMIT 10
```

Check: are column types sensible? Are values in the expected range? Is the row count what you expected from the test run?

## 8. Run fully and verify dedup

Run the full pipeline across all iterations:

```
run_pipeline("my_pipeline", params={"start_date": "2024-01-01", "end_date": "2024-01-07"})
```

Then **re-run the exact same command**. For `incremental` pipelines, the row count must stay the same — this confirms upserts are working and you won't accumulate duplicates on repeated runs. Query and compare:

```sql
SELECT COUNT(*) FROM my_pipeline.my_pipeline
```

If the count grows on re-run, the primary key is not matching correctly — check that the `id` or key field is constructed deterministically (same inputs always produce the same key).

## 9. Done

Report:
- Pipeline name and warehouse table location (`namespace.table`)
- Number of columns
- Row count after the full test run
- Confirmation that re-run produced the same row count (for `incremental` pipelines)
