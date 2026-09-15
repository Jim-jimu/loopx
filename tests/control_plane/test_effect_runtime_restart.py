"""A reused managed runtime keeps its own Node; operators need a restart path."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

from loopx.cli import build_parser
from loopx.cli_commands.doctor import handle_doctor_command
from loopx.control_plane import effect_runtime
from loopx.doctor import render_doctor_markdown


def _runtime_info_path() -> Path:
    return effect_runtime._runtime_info_path(effect_runtime._runtime_fingerprint())


def _isolate_runtime(tmp_path: Path, monkeypatch) -> Path:
    runtime_dir = tmp_path / "runtime"
    monkeypatch.setattr(effect_runtime, "_runtime_dir", lambda: runtime_dir)
    monkeypatch.setenv("LOOPX_EFFECT_RUNTIME_IDLE_MS", "60000")
    return runtime_dir


def test_restart_reports_not_running_without_a_serving_runtime(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _isolate_runtime(tmp_path, monkeypatch)
    result = effect_runtime.restart_effect_runtime()
    assert result["schema_version"] == "loopx_effect_runtime_restart_v0"
    assert result["status"] == "not_running"
    assert result["stopped"] is False
    assert result["previous_runtime_identity"] is None


def test_restart_stops_the_runtime_that_carries_the_serving_identity(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _isolate_runtime(tmp_path, monkeypatch)
    started = effect_runtime.effect_runtime_result("runtime.ping", {})
    readiness = effect_runtime.collect_effect_runtime_readiness()
    assert readiness["runtime_lifecycle"]["state"] == "running"
    identity = readiness["runtime_identity"]
    assert isinstance(identity, dict), readiness
    assert identity["schema_version"] == "loopx_sqlite_runtime_identity_v0"
    assert identity["node_version"]
    assert isinstance(identity["sqlite_authority_qualified"], bool)

    restarted = effect_runtime.restart_effect_runtime()
    assert restarted["status"] == "stopped", restarted
    assert restarted["stopped"] is True
    assert restarted["previous_runtime_identity"] == identity

    stopped = effect_runtime.collect_effect_runtime_readiness()
    assert stopped["runtime_lifecycle"]["state"] == "stopped"
    assert stopped["runtime_identity"] is None
    assert effect_runtime.restart_effect_runtime()["status"] == "not_running"
    replacement = effect_runtime.effect_runtime_result("runtime.ping", {})
    assert int(replacement["pid"]) != int(started["pid"])
    effect_runtime.effect_runtime_result("runtime.shutdown", {}, retry_safe=False)


def test_unqualified_serving_runtime_is_reported_with_a_restart_action(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """The defect: the serving runtime keeps its own Node, so PATH alone cannot fix it."""

    _isolate_runtime(tmp_path, monkeypatch)
    effect_runtime.effect_runtime_result("runtime.ping", {})
    info_path = _runtime_info_path()
    info = json.loads(info_path.read_text(encoding="utf-8"))
    fresh_identity = info["runtime_identity"]
    info["runtime_identity"] = {
        "schema_version": "loopx_sqlite_runtime_identity_v0",
        "node_version": "v25.5.0",
        "sqlite_available": True,
        "sqlite_version": "3.51.2",
        "sqlite_source_id": "2025-08-01",
        "synchronous_statement_finalization": True,
        "sqlite_authority_qualified": False,
        "unavailable_reason": None,
    }
    info_path.write_text(json.dumps(info), encoding="utf-8")

    readiness = effect_runtime.collect_effect_runtime_readiness()
    assert readiness["ready"] is True
    assert readiness["runtime_lifecycle"]["state"] == "running"
    assert readiness["runtime_identity"]["node_version"] == "v25.5.0"
    assert readiness["runtime_identity"]["sqlite_authority_qualified"] is False
    action = readiness["recommended_action"]
    assert "loopx doctor --restart-runtime" in action, action
    rendered = render_doctor_markdown({"ok": True, "typescript_control_plane": readiness})
    assert "runtime_identity" in rendered
    assert "v25.5.0" in rendered and "3.51.2" in rendered

    assert effect_runtime.restart_effect_runtime()["status"] == "stopped"
    effect_runtime.effect_runtime_result("runtime.ping", {})
    restarted = effect_runtime.collect_effect_runtime_readiness()
    # The replacement runtime re-probes the Node it was started from, so a
    # restart is what makes an installed qualified Node take effect.
    assert restarted["runtime_identity"] == fresh_identity
    effect_runtime.effect_runtime_result("runtime.shutdown", {}, retry_safe=False)


def test_deep_readiness_reports_the_identity_of_the_runtime_it_started(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Reading identity before the probe would hide the pair serving later requests."""

    _isolate_runtime(tmp_path, monkeypatch)
    readiness = effect_runtime.collect_effect_runtime_readiness(deep=True)
    assert readiness["semantic_probe"] == "passed", readiness
    identity = readiness["runtime_identity"]
    assert isinstance(identity, dict), readiness
    path_node_version = subprocess.run(
        ["node", "--version"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert identity["node_version"] == path_node_version
    assert identity["sqlite_available"] is True
    effect_runtime.effect_runtime_result("runtime.shutdown", {}, retry_safe=False)


def test_doctor_registers_the_restart_flag_and_reports_its_result(
    tmp_path: Path,
    monkeypatch,
) -> None:
    args = build_parser().parse_args(["doctor", "--restart-runtime"])
    assert args.restart_runtime is True
    assert build_parser().parse_args(["doctor"]).restart_runtime is False

    _isolate_runtime(tmp_path, monkeypatch)
    effect_runtime.effect_runtime_result("runtime.ping", {})
    captured: dict[str, object] = {}
    args = SimpleNamespace(
        deep=False,
        agent_type=None,
        installation_only=True,
        restart_runtime=True,
        subcommand_format="json",
        format="json",
    )
    exit_code = handle_doctor_command(
        args,
        lambda payload, _format, _render: captured.update(payload),
    )
    assert exit_code in {0, 1}
    restart = captured.get("effect_runtime_restart")
    assert isinstance(restart, dict), captured
    assert restart["status"] == "stopped", restart
    rendered = render_doctor_markdown({**captured, "ok": True})
    assert "## Effect Runtime Restart" in rendered
    assert "- status: `stopped`" in rendered
    assert "stopped_runtime: Node" in rendered
