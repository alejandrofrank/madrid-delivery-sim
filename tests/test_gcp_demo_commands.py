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


def test_vertex_start_guard_allows_only_its_native_identity_and_billing():
    validate_plan(
        {
            "resource_changes": [
                change(
                    "google_service_account.restaurant",
                    ["create"],
                    after={"project": PROJECT, "account_id": "restaurant-adk"},
                )
            ]
        },
        PROJECT,
        "vertex-enable",
    )
    for address in (
        "google_artifact_registry_repository.images[0]",
        "google_cloud_run_v2_service.judge[0]",
        "google_storage_bucket.other",
    ):
        with pytest.raises(DemoError):
            validate_plan(
                {
                    "resource_changes": [
                        change(
                            address,
                            ["create"],
                            after={"project": PROJECT},
                        )
                    ]
                },
                PROJECT,
                "vertex-enable",
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
    "address",
    [
        "google_bigquery_dataset.observability[0]",
        'google_bigquery_table.observability["orders"]',
        "google_project_iam_member.trace_writer[0]",
        'google_project_iam_member.runtime_trace_writer["restaurant"]',
        'google_bigquery_dataset_iam_member.runtime_analytics_writer["judge"]',
    ],
)
def test_stop_preserves_observability_data_and_billing_for_explicit_retirement(demo, address):
    demo.compose = Mock()
    demo.state = Mock(return_value={address: {"project": PROJECT}})
    demo.apply = Mock()
    with pytest.raises(DemoError, match="export/back up retained analytics"):
        demo.stop()
    demo.compose.assert_not_called()
    demo.apply.assert_not_called()


def test_stop_rejects_configured_analytics_before_first_apply(demo):
    demo.config["enable_analytics"] = True
    demo.compose = Mock()
    demo.state = Mock(return_value={})
    demo.apply = Mock()
    with pytest.raises(DemoError, match="Cloud observability remains configured"):
        demo.stop()
    demo.apply.assert_not_called()


def test_unlink_plan_rejects_retained_analytics_even_when_unchanged():
    with pytest.raises(DemoError, match="retire cloud observability"):
        validate_plan(
            {
                "resource_changes": [
                    change(
                        "google_bigquery_dataset.observability[0]",
                        ["no-op"],
                        before={"project": PROJECT},
                        after={"project": PROJECT},
                    )
                ]
            },
            PROJECT,
            "unlink-billing",
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


def test_status_reports_analytics_storage_even_with_billing_disabled(demo):
    demo.state = Mock(return_value={"google_bigquery_dataset.observability[0]": {}})
    demo.billing = Mock(return_value=False)
    demo.cloud = Mock(side_effect=[{"lifecycleState": "ACTIVE"}, []])
    demo.local = Mock(return_value={"local": True, "gcp_ai": False})
    result = demo.status()
    assert result["mode"] == "optional-components-retained"
    assert result["analytics_retained"] is True
    assert result["observability_in_state"] == ["google_bigquery_dataset.observability[0]"]
    assert result["foundation_resources"] == 0


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


def test_vertex_start_enables_billing_without_deploying_a_gateway(demo, tmp_path):
    demo.adc = Mock(return_value=tmp_path)
    demo.state = Mock(return_value={})
    demo.billing = Mock(return_value=True)
    demo.apply = Mock()
    demo.compose = Mock()
    demo.vertex_start()
    demo.apply.assert_called_once_with("vertex-enable", billing=True, runtime=False, gateway=False)
    demo.compose.assert_not_called()


def test_native_launcher_keeps_adc_outside_ui_mounts_and_cleans_it(
    demo, tmp_path, monkeypatch, capsys
):
    import sys

    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    import run_adk_vertex as launcher

    source = tmp_path / "operator-adc"
    source.mkdir()
    (source / "application_default_credentials.json").write_text(
        json.dumps(
            {
                "type": "authorized_user",
                "client_id": "fake-client",
                "client_secret": "fake-secret",
                "refresh_token": "synthetic-test-refresh",
            }
        )
    )
    demo.adc = Mock(return_value=source)
    demo.state = Mock(
        return_value={
            "google_service_account.restaurant": {
                "email": f"restaurant-adk@{PROJECT}.iam.gserviceaccount.com",
            }
        }
    )
    demo.billing = Mock(return_value=True)
    mounts = []

    def run(*args, **kwargs):
        mounted = Path(args[args.index("-v") + 1].split(":/adk-credentials")[0])
        assert mounted.parent == tmp_path and mounted.name.startswith(".env.adk-adc-")
        assert not mounted.is_relative_to(tmp_path / "artifacts")
        credentials = json.loads((mounted / "adc.json").read_text())
        assert credentials["type"] == "impersonated_service_account"
        assert credentials["service_account_impersonation_url"].endswith(
            f"restaurant-adk@{PROJECT}.iam.gserviceaccount.com:generateAccessToken"
        )
        assert all("synthetic-test-refresh" not in arg for arg in args)
        mounts.append(mounted)
        return "comparison completed"

    demo.run = run
    monkeypatch.setattr(launcher, "Demo", lambda: demo)
    monkeypatch.setattr(sys, "argv", ["run_adk_vertex.py", "--paid"])
    launcher.main()
    assert mounts and not mounts[0].exists()
    assert "synthetic-test-refresh" not in capsys.readouterr().out


@pytest.mark.parametrize(
    "address",
    [
        'google_bigquery_table.analytics["run_receipts"]',
        "google_bigquery_dataset.analytics[0]",
        "google_service_account.analytics[0]",
        "google_project_iam_custom_role.analytics_jobs[0]",
        'google_project_service.telemetry["cloudtrace.googleapis.com"]',
        'google_project_iam_member.telemetry["roles/telemetry.tracesWriter"]',
    ],
)
def test_stop_requires_optional_cleanup_before_any_mutations(demo, address):
    demo.state = Mock(return_value={**dict.fromkeys(module.RUNTIME), address: {}})
    demo.compose = Mock()
    demo.billing = Mock()
    demo.apply = Mock()
    with pytest.raises(DemoError, match="explicit cleanup") as error:
        demo.stop()
    assert "-var=enable_bigquery=false" in str(error.value)
    assert "-var=enable_telemetry=false" in str(error.value)
    assert "preserve the current runtime flags" in str(error.value)
    demo.compose.assert_not_called()
    demo.billing.assert_not_called()
    demo.apply.assert_not_called()


def test_stop_validates_state_before_resetting_the_local_app(demo):
    demo.state = Mock(side_effect=DemoError("Unexpected project state"))
    demo.compose = Mock()
    demo.apply = Mock()
    with pytest.raises(DemoError, match="Unexpected project state"):
        demo.stop()
    demo.compose.assert_not_called()
    demo.apply.assert_not_called()


@pytest.mark.parametrize("billing", [False, True])
def test_status_exposes_retained_optional_components_without_claiming_parked(demo, billing):
    analytics = 'google_bigquery_table.analytics["run_kpis"]'
    telemetry = "google_service_account.telemetry[0]"
    demo.state = Mock(return_value={"google_project.ai": {}, analytics: {}, telemetry: {}})
    demo.billing = Mock(return_value=billing)
    demo.cloud = Mock(side_effect=[{"lifecycleState": "ACTIVE"}, []] + ([[]] if billing else []))
    demo.local = Mock(return_value={"local": True, "gcp_ai": False})
    result = demo.status()
    assert result["analytics_in_state"] == [analytics]
    assert result["telemetry_in_state"] == [telemetry]
    assert result["mode"] == ("cloud-enabled" if billing else "optional-components-retained")


@pytest.mark.parametrize("component", module.OPTIONAL_COMPONENTS.values())
def test_optional_resource_detection_covers_partial_iam_and_storage(component):
    state = {f"{address}[0]": {} for address in component}
    found = module.optional_resources(state)
    assert set().union(*map(set, found.values())) == set(state)
    assert not any(module.optional_resources({"google_service_account.restaurant": {}}).values())


def test_plan_guard_still_rejects_optional_resource_deletion():
    for address in (
        'google_bigquery_table.analytics["run_receipts"]',
        "google_service_account.telemetry[0]",
    ):
        with pytest.raises(DemoError, match="Plan rejected"):
            validate_plan(
                {"resource_changes": [change(address, ["delete"], before={"project": PROJECT})]},
                PROJECT,
                "remove-runtime",
            )


@pytest.mark.parametrize("phase", ["remove-runtime", "unlink-billing"])
def test_parking_cannot_recreate_optionals_from_stale_opt_in_flags(demo, phase):
    demo.config.update(enable_bigquery=True, enable_telemetry=True)
    demo.tf = Mock(side_effect=["", '{"resource_changes": []}', ""])
    demo.apply(phase, billing=phase == "remove-runtime", runtime=False, gateway=False)
    planned = demo.tf.call_args_list[0].args
    assert "-var=enable_bigquery=false" in planned
    assert "-var=enable_telemetry=false" in planned
    assert "-var=enable_analytics=false" in planned
    assert "-var=enable_cloud_trace=false" in planned
    parked = json.loads((demo.infra / "zz-demo.auto.tfvars.json").read_text())
    assert parked["enable_bigquery"] is False and parked["enable_telemetry"] is False
    assert parked["enable_analytics"] is False and parked["enable_cloud_trace"] is False
