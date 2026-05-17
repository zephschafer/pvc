"""Tests for Deployment model and cron validation (F-030)."""

import pytest
from pydantic import ValidationError

from dcf.config.models import Deployment, Collector


# ------------------------------------------------------------------ #
# Deployment model — cron validation                                   #
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("schedule", [
    "0 8 * * *",        # daily at 8am
    "*/15 * * * *",     # every 15 minutes
    "0 0 1 * *",        # monthly
    "0 0 * * 0",        # weekly on Sunday
    "30 6 * * 1-5",     # weekdays at 6:30
])
def test_deployment_accepts_valid_cron(schedule):
    d = Deployment(schedule=schedule)
    assert d.schedule == schedule


@pytest.mark.parametrize("schedule", [
    "not a cron",
    "* * * *",          # only 4 fields
    "* * * * * *",      # 6 fields (seconds — not standard 5-field cron)
    "",
    "8am daily",
])
def test_deployment_rejects_invalid_cron(schedule):
    with pytest.raises(ValidationError) as exc_info:
        Deployment(schedule=schedule)
    err = str(exc_info.value)
    assert "valid cron expression" in err or "schedule is required" in err


def test_deployment_paused_defaults_false():
    d = Deployment(schedule="0 8 * * *")
    assert d.paused is False


def test_deployment_paused_can_be_set():
    d = Deployment(schedule="0 8 * * *", paused=True)
    assert d.paused is True


# ------------------------------------------------------------------ #
# Collector.deployment field                                            #
# ------------------------------------------------------------------ #

_PIPELINE_BASE = {
    "name": "test_collector",
    "source": {
        "type": "http",
        "url": "https://example.com/api",
        "schema": {
            "columns": [{"name": "id", "path": "id", "type": "integer"}],
        },
    },
    "cadence": {"strategy": "incremental", "primary_key": "id"},
}


def test_collector_deployment_optional():
    p = Collector.from_dict(_PIPELINE_BASE)
    assert p.deployment is None


def test_collector_deployment_parsed():
    data = {**_PIPELINE_BASE, "deployment": {"schedule": "0 8 * * *"}}
    p = Collector.from_dict(data)
    assert p.deployment is not None
    assert p.deployment.schedule == "0 8 * * *"
    assert p.deployment.paused is False


def test_collector_deployment_invalid_cron_raises():
    data = {**_PIPELINE_BASE, "deployment": {"schedule": "not a cron"}}
    with pytest.raises(ValidationError) as exc_info:
        Collector.from_dict(data)
    assert "valid cron expression" in str(exc_info.value)
