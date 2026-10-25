import importlib.util
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

spec = importlib.util.spec_from_file_location(
    "gcp_demo", Path(__file__).resolve().parents[1] / "scripts/gcp_demo.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
Demo, DemoError, validate_plan = module.Demo, module.DemoError, module.validate_plan
PROJECT = "mds-lifecycle-test"


def change(address, actions, before=None, after=None):
    return {"address": address, "change": {"actions": actions, "before": before, "after": after}}


@pytest.fixture
def demo(tmp_path):
    infra = tmp_path / "infra/gcp-ai"
    infra.mkdir(parents=True)
    (infra / "deploy.auto.tfvars.json").write_text(
        json.dumps({"project_id": PROJECT, "region": "europe-west1"})
    )
    return Demo(tmp_path)


@pytest.mark.parametrize(
    "address,actions",
    [
        ("google_service_account.caller[0]", ["delete"]),
        ("google_project_iam_member.vertex[0]", ["update"]),
        ("google_project.ai", ["delete", "create"]),
        ("google_artifact_registry_repository.images[0]", ["delete", "create"]),
        ("google_storage_bucket.unrelated", ["create"]),
    ],
)
def test_plan_guard_preserves_free_foundation_and_rejects_unowned_work(address, actions):
    with pytest.raises(DemoError, match="Plan rejected"):
        validate_plan({"resource_changes": [change(address, actions)]}, PROJECT, "deploy")


def test_guard_allows_billing_only_project_update_but_rejects_project_drift():
    before = {"project_id": PROJECT, "billing_account": None}
    after = {"project_id": PROJECT, "billing_account": "private-account"}
    validate_plan(
        {"resource_changes": [change("google_project.ai", ["update"], before, after)]},
        PROJECT,
        "bootstrap",
    )
    with pytest.raises(DemoError):
        validate_plan(
            {
                "resource_changes": [
                    change("google_project.ai", ["update"], before, {**after, "name": "changed"})
                ]
            },
            PROJECT,
            "bootstrap",
        )


def test_guard_rejects_wrong_project_and_delete_during_start():
    address = "google_artifact_registry_repository.images[0]"
    with pytest.raises(DemoError):
        validate_plan(
            {"resource_changes": [change(address, ["create"], after={"project": "other"})]},
            PROJECT,
            "bootstrap",
        )
    with pytest.raises(DemoError):
        validate_plan(
            {"resource_changes": [change(address, ["delete"], before={"project": PROJECT})]},
            PROJECT,
            "bootstrap",
        )


def test_stop_resets_local_first_deletes_runtime_then_unlinks_billing(demo):
    events = []
    demo.compose = lambda cloud: events.append(("compose", cloud))
    demo.state = Mock(side_effect=[dict.fromkeys(module.RUNTIME), {}])
    demo.billing = Mock(side_effect=[True, False])
    demo.apply = lambda phase, **kwargs: events.append((phase, kwargs["billing"]))
    demo.stop()
    assert events == [("compose", False), ("remove-runtime", True), ("unlink-billing", False)]


def test_stop_already_parked_never_relinks_billing(demo):
    demo.compose = Mock()
    demo.state = Mock(return_value={})
    demo.billing = Mock(return_value=False)
    demo.apply = Mock()
    demo.stop()
    demo.apply.assert_called_once_with(
        "unlink-billing", billing=False, runtime=False, gateway=False
    )


@pytest.mark.parametrize(
    "error", [DemoError("Docker unavailable"), module.subprocess.TimeoutExpired("docker", 900)]
)
def test_cloud_cleanup_continues_when_local_app_is_unavailable(demo, error):
    demo.compose = Mock(side_effect=error)
    demo.state = Mock(side_effect=[dict.fromkeys(module.RUNTIME), {}])
    demo.billing = Mock(side_effect=[True, False])
    demo.apply = Mock()
    with pytest.raises(DemoError, match="Cloud cleanup succeeded"):
        demo.stop()
    assert [call.args[0] for call in demo.apply.call_args_list] == [
        "remove-runtime",
        "unlink-billing",
    ]


def test_stop_keeps_billing_linked_when_runtime_deletion_fails(demo):
    demo.compose = Mock()
    demo.state = Mock(return_value=dict.fromkeys(module.RUNTIME))
    demo.billing = Mock(return_value=True)
    demo.apply = Mock(side_effect=DemoError("Artifact deletion failed"))
    with pytest.raises(DemoError, match="Artifact deletion failed"):
        demo.stop()
    demo.apply.assert_called_once_with("remove-runtime", billing=True, runtime=False, gateway=False)


def test_start_fails_before_billing_when_adc_missing(demo):
    demo.adc = Mock(side_effect=DemoError("ADC missing"))
    demo.apply = Mock()
    with pytest.raises(DemoError, match="ADC missing"):
        demo.start()
    demo.apply.assert_not_called()


def test_start_bootstraps_pushes_pinned_image_then_connects_local_app(demo, tmp_path):
    events = []
    demo.adc = Mock(return_value=tmp_path)
    demo.run = Mock(return_value="version")
    demo.state = Mock(
        side_effect=[
            {},
            {
                "google_cloud_run_v2_service.judge[0]": {"uri": "https://judge.run.app"},
                "google_service_account.caller[0]": {"email": "caller@example.test"},
            },
        ]
    )
    demo.billing = Mock(return_value=True)
    demo.apply = lambda phase, **kwargs: events.append((phase, kwargs))
    demo.image = lambda: "image@sha256:" + "a" * 64
    demo.compose = lambda *args: events.append(("compose", args))
    demo.start()
    assert [e[0] for e in events] == ["bootstrap", "deploy", "compose"]
    assert events[1][1]["image"].endswith("a" * 64)
    assert not any("judge" == arg for call in demo.run.call_args_list for arg in call.args)


def test_failed_apply_never_persists_success_flags(demo):
    def tf(*args):
        if args[0] == "show":
            return '{"resource_changes": []}'
        if args[0] == "apply":
            raise DemoError("Failed apply")
        return ""

    demo.tf = tf
    with pytest.raises(DemoError):
        demo.apply("bootstrap", billing=True, runtime=True, gateway=False)
    assert not (demo.infra / "zz-demo.auto.tfvars.json").exists()


def test_saved_plan_is_checked_before_apply(demo):
    demo.tf = Mock(
        side_effect=[
            "",
            json.dumps(
                {"resource_changes": [change("google_service_account.caller[0]", ["delete"])]}
            ),
        ]
    )
    with pytest.raises(DemoError):
        demo.apply("remove-runtime", billing=True, runtime=False, gateway=False)
    assert len(demo.tf.call_args_list) == 2


def test_status_does_not_enable_billing_to_list_artifacts(demo):
    demo.state = Mock(return_value={"google_project.ai": {}})
    demo.billing = Mock(return_value=False)
    demo.cloud = Mock(side_effect=[{"lifecycleState": "ACTIVE"}, []])
    demo.local = Mock(return_value={"local": True, "gcp_ai": False})
    result = demo.status()
    assert result["mode"] == "parked"
    assert result["artifact_repositories"] is None
    assert not any("artifacts" in call.args for call in demo.cloud.call_args_list)


def test_concurrent_lifecycle_commands_are_blocked(demo):
    with module.lifecycle_lock(demo.infra):
        with pytest.raises(DemoError, match="Another lifecycle"):
            with module.lifecycle_lock(demo.infra):
                pytest.fail("Lock must not allow second writer")
    assert not (demo.infra / ".demo-command.lock").exists()


def test_registry_credentials_are_temporary_and_sent_only_on_stdin(demo):
    captured = []
    image = f"europe-west1-docker.pkg.dev/{PROJECT}/judgement/gateway"
    digest = image + "@sha256:" + "b" * 64

    def run(*args, **kwargs):
        captured.append((args, kwargs))
        if args[:3] == ("docker", "context", "inspect"):
            return "unix:///var/run/docker.sock"
        if args[:3] == ("gcloud", "auth", "print-access-token"):
            return "private-token"
        if args[:3] == ("docker", "image", "inspect"):
            return json.dumps([digest])
        return ""

    demo.run = run
    assert demo.image() == digest
    login = next(call for call in captured if call[0][:2] == ("docker", "login"))
    assert login[1]["stdin"] == "private-token\n"
    assert all("private-token" not in arg for args, _ in captured for arg in args)
    temporary_config = Path(login[1]["env"]["DOCKER_CONFIG"])
    assert not temporary_config.exists()


def test_existing_gateway_start_does_not_rebuild_or_redeploy(demo, tmp_path):
    demo.adc = Mock(return_value=tmp_path)
    demo.run = Mock()
    demo.state = Mock(
        return_value={
            "google_cloud_run_v2_service.judge[0]": {"uri": "https://judge.run.app"},
            "google_service_account.caller[0]": {"email": "caller@example.test"},
        }
    )
    demo.billing = Mock(return_value=True)
    demo.apply = Mock()
    demo.image = Mock()
    demo.compose = Mock()
    demo.start()
    demo.apply.assert_not_called()
    demo.image.assert_not_called()
    demo.compose.assert_called_once()
