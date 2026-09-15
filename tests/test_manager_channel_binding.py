"""The steward channel binds its executor and model to the operator credential."""

from __future__ import annotations

import json

import pytest

from loopx.chat_agent import CodexChatAgentError
from loopx.capabilities.manager_runtime import manager_runtime_capability_projection
from loopx.chat_manager import (
    MANAGER_ENDPOINT_TRANSPORT_UNSUPPORTED,
    MANAGER_MODEL_SOURCE_ENV_OVERRIDE,
    MANAGER_MODEL_SOURCE_OPERATOR_CREDENTIAL,
    MANAGER_MODEL_SOURCE_VENDOR_DEFAULT,
    manager_channel_binding,
    manager_executor_endpoint_default,
    manager_model_config,
    open_manager_session,
)
from loopx.chat_runtime import (
    MANAGED_HOST_CHAT_TRANSPORT_UNSUPPORTED,
    ChatRuntimeController,
)
from loopx.chat_store import ChatSessionStore


def test_no_operator_credential_keeps_the_shipped_chat_defaults():
    binding = manager_channel_binding({})

    assert binding["executor_endpoint"] == "codex"
    assert binding["executor_endpoint_source"] == "no_operator_credential"
    assert binding["executor_transport_reason"] == ""
    assert binding["model"] == "gpt-6-astra"
    assert binding["model_source"] == MANAGER_MODEL_SOURCE_VENDOR_DEFAULT
    assert binding["credential_env_var"] == ""


def test_configured_operator_credential_binds_the_steward_model():
    binding = manager_channel_binding({"DEEPSEEK_API_KEY": "fixture"})

    assert binding["model"] == "deepseek-flash"
    assert binding["model_source"] == MANAGER_MODEL_SOURCE_OPERATOR_CREDENTIAL
    assert binding["credential_env_var"] == "DEEPSEEK_API_KEY"
    # The steward channel still needs a transport that can hold an interactive
    # session, so the resolved endpoint names that reason instead of hiding it.
    assert binding["executor_endpoint"] == "codex"
    assert binding["executor_endpoint_source"] == "operator_credential"
    assert (
        binding["executor_transport_reason"]
        == MANAGER_ENDPOINT_TRANSPORT_UNSUPPORTED
    )
    assert "fixture" not in json.dumps(binding)


def test_blank_or_missing_credential_stays_on_the_vendor_default():
    assert (
        manager_channel_binding({"DEEPSEEK_API_KEY": "   "})["model"]
        == "gpt-6-astra"
    )
    assert manager_channel_binding({})["model"] == "gpt-6-astra"


def test_explicit_model_override_wins_with_and_without_credential():
    overridden = manager_channel_binding(
        {"DEEPSEEK_API_KEY": "fixture", "LOOPX_MANAGER_MODEL": "fixture-model"}
    )
    assert overridden["model"] == "fixture-model"
    assert overridden["model_source"] == MANAGER_MODEL_SOURCE_ENV_OVERRIDE

    without_credential = manager_model_config({"LOOPX_MANAGER_MODEL": "fixture-model"})
    assert without_credential == {"model": "fixture-model", "reasoning_effort": "high"}


def test_manager_model_config_reads_the_process_environment(monkeypatch):
    monkeypatch.delenv("LOOPX_MANAGER_MODEL", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fixture")

    assert manager_model_config()["model"] == "deepseek-flash"


def test_open_manager_session_resolves_the_endpoint_only_when_unset(tmp_path):
    calls: list[dict[str, object]] = []

    class Controller:
        def open_session(self, **kwargs):
            calls.append(kwargs)
            return {"session_id": "fixture"}, False

    controller = Controller()
    open_manager_session(controller=controller, goal_id="g", work_dir=tmp_path)
    assert calls[-1]["agent_id"] == manager_executor_endpoint_default()

    open_manager_session(
        controller=controller,
        goal_id="g",
        work_dir=tmp_path,
        executor_endpoint_id="claude-code",
    )
    assert calls[-1]["agent_id"] == "claude-code"


def test_managed_host_without_a_chat_transport_raises_a_typed_gate(tmp_path):
    runtime = ChatRuntimeController(
        store=ChatSessionStore(tmp_path / "store"), codex_bin="fixture-codex"
    )
    try:
        with pytest.raises(CodexChatAgentError) as raised:
            runtime.open_session(
                goal_id="fixture-goal",
                agent_id="dsh",
                work_dir=tmp_path,
                objective="fixture",
                mode="new",
            )
    finally:
        runtime.close()

    assert raised.value.error_code == MANAGED_HOST_CHAT_TRANSPORT_UNSUPPORTED
    assert raised.value.gate["kind"] == "host_tool_gate"
    assert "loopx turn" in raised.value.gate["next_action"]


def test_unknown_endpoint_keeps_the_untyped_lookup_error(tmp_path):
    runtime = ChatRuntimeController(
        store=ChatSessionStore(tmp_path / "store"), codex_bin="fixture-codex"
    )
    try:
        with pytest.raises(ValueError, match="unknown Agent endpoint"):
            runtime.open_session(
                goal_id="fixture-goal",
                agent_id="not-a-registered-endpoint",
                work_dir=tmp_path,
                objective="fixture",
                mode="new",
            )
    finally:
        runtime.close()


def test_manager_capability_projection_carries_the_channel_binding():
    projection = manager_runtime_capability_projection(
        object(),
        {"model": "deepseek-flash", "reasoning_effort": "high"},
        channel_binding=manager_channel_binding({"DEEPSEEK_API_KEY": "fixture"}),
    )

    binding = projection["channel_binding"]
    assert projection["scope"] == "owner_global"
    assert binding["executor_endpoint"] == "codex"
    assert binding["executor_transport_reason"] == MANAGER_ENDPOINT_TRANSPORT_UNSUPPORTED
    assert binding["model"] == "deepseek-flash"
    assert binding["model_source"] == MANAGER_MODEL_SOURCE_OPERATOR_CREDENTIAL
    assert binding["operator_credential_configured"] is True
    assert "fixture" not in json.dumps(projection)


def test_manager_capability_projection_stays_unchanged_without_a_binding():
    projection = manager_runtime_capability_projection(
        object(), {"model": "gpt-6-astra", "reasoning_effort": "high"}
    )

    assert "channel_binding" not in projection
    assert projection["model"] == "gpt-6-astra"
