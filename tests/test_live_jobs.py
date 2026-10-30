from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi import BackgroundTasks, HTTPException

from delivery.live_jobs import execute, schedule, submit_job


def test_live_submission_uses_fixed_job_authenticated_session_and_bounded_overrides(monkeypatch):
    monkeypatch.setenv("DELIVERY_CLOUD_RUN_JOB",
                       "projects/test/locations/europe-west1/jobs/mds-shift")
    session = Mock()
    session.post.return_value.json.return_value = {
        "name": "projects/test/locations/eu/operations/1"
    }
    run = str(uuid4())
    assert submit_job("orders", run, session=session).endswith("/1")
    request = session.post.call_args
    assert request.args[0].endswith("/jobs/mds-shift:run")
    assert request.kwargs["json"]["overrides"]["containerOverrides"][0]["env"][1]["value"] == run


def test_live_never_launches_untracked_background_thread_and_returns_run_on_failure(monkeypatch):
    tasks, callback = BackgroundTasks(), Mock()
    monkeypatch.setenv("DELIVERY_RUNTIME", "live")
    monkeypatch.setattr("delivery.live_jobs.submit_job", Mock(side_effect=RuntimeError("private")))
    run = str(uuid4())
    with pytest.raises(HTTPException) as error:
        schedule(tasks, callback, "orders", run)
    assert error.value.status_code == 503 and error.value.detail["run_id"] == run
    assert "private" not in str(error.value.detail) and not tasks.tasks


def test_local_preserves_existing_background_arguments(monkeypatch):
    monkeypatch.setenv("DELIVERY_RUNTIME", "local")
    tasks, callback = BackgroundTasks(), Mock()
    schedule(tasks, callback, "delivery", "run", 12)
    assert tasks.tasks[0].args == ("run", 12)


@pytest.mark.parametrize("kind,run,seconds", [("arbitrary", str(uuid4()), 0),
                                              ("orders", "bad-id", 0),
                                              ("orders", str(uuid4()), 121)])
def test_invalid_job_never_reaches_cloud(kind, run, seconds):
    session = Mock()
    with pytest.raises(ValueError):
        submit_job(kind, run, seconds, session=session)
    session.post.assert_not_called()
    with pytest.raises(ValueError):
        execute(kind, run, seconds)
