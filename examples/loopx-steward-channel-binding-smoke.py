#!/usr/bin/env python3
"""Prove the steward channel binds its executor and model to the operator credential."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from loopx.chat_manager import (  # noqa: E402
    MANAGER_ENDPOINT_TRANSPORT_UNSUPPORTED,
    MANAGER_MODEL_SOURCE_ENV_OVERRIDE,
    MANAGER_MODEL_SOURCE_OPERATOR_CREDENTIAL,
    MANAGER_MODEL_SOURCE_VENDOR_DEFAULT,
    manager_channel_binding,
    manager_model_config,
    open_manager_session,
)
from loopx.chat_agent import CodexChatAgentError  # noqa: E402
from loopx.chat_runtime import (  # noqa: E402
    MANAGED_HOST_CHAT_TRANSPORT_UNSUPPORTED,
    ChatRuntimeController,
)
from loopx.chat_store import ChatSessionStore  # noqa: E402


CREDENTIAL_ENV = "DEEPSEEK_API_KEY"
CREDENTIAL_VALUE = "fixture-operator-credential"


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"steward channel binding smoke failed: {message}")


def main() -> int:
    without_credential = manager_channel_binding({})
    _assert(
        without_credential["executor_endpoint"] == "codex",
        "no credential must keep the shipped chat endpoint",
    )
    _assert(
        without_credential["model"] == "gpt-6-astra"
        and without_credential["model_source"] == MANAGER_MODEL_SOURCE_VENDOR_DEFAULT,
        "no credential must keep the vendor model default",
    )

    with_credential = manager_channel_binding({CREDENTIAL_ENV: CREDENTIAL_VALUE})
    _assert(
        with_credential["model"] == "deepseek-flash"
        and with_credential["model_source"] == MANAGER_MODEL_SOURCE_OPERATOR_CREDENTIAL,
        "a configured credential must bind the steward model to the operator provider",
    )
    _assert(
        with_credential["credential_env_var"] == CREDENTIAL_ENV,
        "the binding must report the credential variable name",
    )
    _assert(
        CREDENTIAL_VALUE not in json.dumps(with_credential),
        "the binding must never echo a credential value",
    )
    _assert(
        with_credential["executor_endpoint_source"] == "operator_credential"
        and with_credential["executor_transport_reason"]
        == MANAGER_ENDPOINT_TRANSPORT_UNSUPPORTED,
        "the chat transport limit must be reported as a typed reason",
    )
    _assert(
        manager_model_config(
            {CREDENTIAL_ENV: CREDENTIAL_VALUE, "LOOPX_MANAGER_MODEL": "fixture-model"}
        )["model"]
        == "fixture-model"
        and manager_channel_binding(
            {CREDENTIAL_ENV: CREDENTIAL_VALUE, "LOOPX_MANAGER_MODEL": "fixture-model"}
        )["model_source"]
        == MANAGER_MODEL_SOURCE_ENV_OVERRIDE,
        "an explicit model override must win over the credential default",
    )

    opened: list[dict[str, object]] = []

    class _Controller:
        def open_session(self, **kwargs):
            opened.append(kwargs)
            return {"session_id": "fixture-session"}, False

    controller = _Controller()
    with tempfile.TemporaryDirectory() as work_dir:
        ambient = os.environ.pop(CREDENTIAL_ENV, None)
        try:
            open_manager_session(
                controller=controller,
                goal_id="loopx-steward-binding-fixture",
                work_dir=Path(work_dir),
            )
        finally:
            if ambient is not None:
                os.environ[CREDENTIAL_ENV] = ambient
        _assert(
            opened[-1]["agent_id"] == without_credential["executor_endpoint"],
            "without a configured credential the manager session must open the shipped endpoint",
        )

        os.environ[CREDENTIAL_ENV] = CREDENTIAL_VALUE
        try:
            open_manager_session(
                controller=controller,
                goal_id="loopx-steward-binding-fixture",
                work_dir=Path(work_dir),
            )
        finally:
            os.environ.pop(CREDENTIAL_ENV, None)
        _assert(
            opened[-1]["agent_id"] == with_credential["executor_endpoint"],
            "with a configured credential the manager session must open the resolved endpoint",
        )
        _assert(
            opened[-1]["agent_id"] != "dsh"
            or with_credential["executor_transport_reason"] == "",
            "the manager session must not open an endpoint without a chat transport",
        )

    print(
        json.dumps(
            {
                "ok": True,
                "without_credential": without_credential,
                "with_credential": with_credential,
                "opened_endpoint": opened[-1]["agent_id"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _assert_typed_transport_gate(root: Path) -> None:
    """A managed host without a chat transport must fail as a typed gate."""

    runtime = ChatRuntimeController(
        store=ChatSessionStore(root / "store"), codex_bin="fixture-codex"
    )
    try:
        try:
            runtime.open_session(
                goal_id="loopx-steward-binding-fixture",
                agent_id="dsh",
                work_dir=root,
                objective="fixture",
                mode="new",
            )
        except CodexChatAgentError as exc:
            _assert(
                exc.error_code == MANAGED_HOST_CHAT_TRANSPORT_UNSUPPORTED,
                "the managed host without a chat transport must report its own error code",
            )
            _assert(
                exc.gate.get("kind") == "host_tool_gate",
                "the managed host gate must stay a host tool gate",
            )
        else:
            raise SystemExit(
                "steward channel binding smoke failed: dsh opened an interactive session"
            )
    finally:
        runtime.close()


if __name__ == "__main__":
    exit_code = main()
    with tempfile.TemporaryDirectory() as gate_root:
        _assert_typed_transport_gate(Path(gate_root))
    raise SystemExit(exit_code)
