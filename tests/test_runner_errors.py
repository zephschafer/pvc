"""
Tests for runner error reporting improvements (F-023).

Previously, fetch exceptions produced only "fetch error: {e}" with no traceback
and no failure summary. The collector also reported "complete" even when every
iteration failed.
"""
from __future__ import annotations

import io
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from dcf.config.models import Collector, PythonSource, Schema, Column, Cadence


def _make_collector(name: str = "test") -> Collector:
    return Collector(
        name=name,
        source=PythonSource(
            type="python", module="m", function="f",
            schema_=Schema(columns=[Column(name="id", path="id", type="string")]),
        ),
        cadence=Cadence(strategy="incremental", primary_key="id"),
    )


def _run_captured(collector, **kwargs) -> str:
    """Run collector and return all stdout as a string."""
    from dcf.engine.runner import run_collector

    buf = io.StringIO()
    with (
        patch("dcf.spark_session.get_spark", return_value=MagicMock()),
        patch("dcf.engine.runner.iceberg_writer"),
        patch("dcf.project.find_project_root", return_value=Path("/tmp/dcf-test")),
        redirect_stdout(buf),
    ):
        run_collector(collector, catalog="local", **kwargs)
    return buf.getvalue()


class TestFetchErrorReporting:
    def test_exception_type_in_error_line(self):
        """Error line must include the exception class name."""
        collector = _make_collector()
        with patch("dcf.engine.runner.fetch_records", side_effect=ValueError("bad value")):
            out = _run_captured(collector)
        assert "ValueError" in out

    def test_traceback_included(self):
        """Full traceback must appear in output so the failing line is identifiable."""
        collector = _make_collector()
        with patch("dcf.engine.runner.fetch_records", side_effect=KeyError("api_key")):
            out = _run_captured(collector)
        assert "Traceback" in out

    def test_all_failed_summary(self):
        """When every iteration fails, completion line must say FAILED, not complete."""
        collector = _make_collector()
        with patch("dcf.engine.runner.fetch_records", side_effect=RuntimeError("boom")):
            out = _run_captured(collector)
        assert "FAILED" in out
        assert "complete" not in out.split("FAILED")[0].split("[dcf]")[-1]

    def test_partial_failure_summary(self):
        """When some iterations fail and some succeed, report the failure count."""
        from dcf.config.models import CategoricalIterate
        collector = Collector(
            name="multi",
            source=PythonSource(
                type="python", module="m", function="f",
                schema_=Schema(columns=[Column(name="id", path="id", type="string")]),
            ),
            cadence=Cadence(
                strategy="append",
                iterate=[CategoricalIterate(type="categorical", param="x", values=["a", "b", "c"])],
            ),
        )

        call_count = 0
        def flaky(_source, _params):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise RuntimeError("second always fails")
            return [{"id": str(call_count)}]

        with patch("dcf.engine.runner.fetch_records", side_effect=flaky):
            out = _run_captured(collector)

        assert "1/3" in out          # one out of three failed
        assert "FAILED" not in out    # not a total failure
        assert "complete with errors" in out

    def test_clean_run_still_says_complete(self):
        """A run with no failures must still say 'complete' (no regression)."""
        collector = _make_collector()
        with patch("dcf.engine.runner.fetch_records", return_value=[{"id": "1"}]):
            out = _run_captured(collector)
        assert "complete" in out
        assert "FAILED" not in out
        assert "errors" not in out
