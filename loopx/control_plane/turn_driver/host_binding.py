"""Credential-resolved default Turn host binding and managed executor readback.

The default host for ``loopx turn plan`` and ``loopx turn run-once`` is decided
by what the operator configured, not by the harness alone:

- a configured operator model credential selects the DeepSeek Harness host
  (``dsh``), so the bounded Turn runs on the operator-supplied endpoint instead
  of any individual's CLI subscription;
- with no operator credential configured the default stays the Codex CLI host
  (``codex-cli``).

Resolution is a pure function of the environment so the command defaults, the
Turn plan readback, and tests quote one rule instead of drifting apart.

``managed_executor_binding`` turns the same facts into the readback a caller can
act on before a Turn runs: which executor the plan would use, whether that
executor is bound to an operator credential or to an individual CLI host, and
whether the managed host can actually launch here. An executor LoopX can prove
cannot launch is reported as unavailable so the Turn fails closed instead of
drifting onto another executor.
"""

from __future__ import annotations

import importlib.util
import os
from collections.abc import Mapping
from typing import Any, Callable

from ..operator_credential import (
    OPERATOR_CREDENTIAL_ENV_VARS,
    OPERATOR_ENDPOINT_ENV_VAR,
    configured_operator_credential,
)

HOST_WITH_OPERATOR_CREDENTIAL = "dsh"
HOST_WITHOUT_OPERATOR_CREDENTIAL = "codex-cli"

MANAGED_EXECUTOR_BINDING_SCHEMA_VERSION = "managed_executor_binding_v0"
# Executor kinds name where a Turn's model work is billed and bounded rather
# than which adapter is launched: a managed executor runs on an
# operator-supplied credential, an individual executor on one person's own CLI
# login, and a generic executor on a caller-supplied adapter command.
EXECUTOR_KIND_MANAGED = "managed"
EXECUTOR_KIND_INDIVIDUAL = "individual"
EXECUTOR_KIND_GENERIC = "generic"
INDIVIDUAL_CLI_HOSTS = frozenset({"codex-cli", "claude-code"})
MANAGED_HOST = HOST_WITH_OPERATOR_CREDENTIAL

# The built-in dsh host launches the DeepSeek Harness runtime unless the caller
# supplies the explicit runner hook, so that module being importable is the
# launchability fact this projection checks without side effects.
DSH_RUNTIME_MODULE = "deepseek_harness"
DSH_RUNTIME_UNAVAILABLE = "dsh_runtime_unavailable"


def resolve_default_turn_host(environ: Mapping[str, str] | None = None) -> str:
    """Return the shipped default Turn host for this operator environment."""

    if configured_operator_credential(environ) is not None:
        return HOST_WITH_OPERATOR_CREDENTIAL
    return HOST_WITHOUT_OPERATOR_CREDENTIAL


def _configured_env_name(name: str, environ: Mapping[str, str] | None) -> str | None:
    source = os.environ if environ is None else environ
    return name if str(source.get(name, "") or "").strip() else None


def dsh_runtime_importable(
    module_probe: Callable[[str], bool] | None = None,
) -> bool:
    """Whether the DeepSeek Harness runtime the built-in dsh host launches exists."""

    if module_probe is not None:
        return bool(module_probe(DSH_RUNTIME_MODULE))
    try:
        return importlib.util.find_spec(DSH_RUNTIME_MODULE) is not None
    except (ImportError, ValueError):
        return False


def managed_executor_binding(
    host: str,
    *,
    environ: Mapping[str, str] | None = None,
    dsh_runner_configured: bool = False,
    module_probe: Callable[[str], bool] | None = None,
) -> dict[str, Any]:
    """Project the executor one planned Turn would run on.

    ``available`` is ``False`` only when LoopX can prove the planned executor
    cannot launch here, which is what a caller has to fail closed on. ``None``
    records that this projection does not probe that executor kind, so it makes
    no claim rather than an unproven ``True``.
    """

    if host == MANAGED_HOST:
        launchable = bool(
            dsh_runner_configured or dsh_runtime_importable(module_probe)
        )
        return {
            "schema_version": MANAGED_EXECUTOR_BINDING_SCHEMA_VERSION,
            "executor": host,
            "executor_kind": EXECUTOR_KIND_MANAGED,
            "credential_env": configured_operator_credential(environ),
            "endpoint_env": _configured_env_name(OPERATOR_ENDPOINT_ENV_VAR, environ),
            "available": launchable,
            "unavailable_reason": None if launchable else DSH_RUNTIME_UNAVAILABLE,
        }
    return {
        "schema_version": MANAGED_EXECUTOR_BINDING_SCHEMA_VERSION,
        "executor": host,
        "executor_kind": (
            EXECUTOR_KIND_INDIVIDUAL
            if host in INDIVIDUAL_CLI_HOSTS
            else EXECUTOR_KIND_GENERIC
        ),
        "credential_env": None,
        "endpoint_env": None,
        "available": None,
        "unavailable_reason": None,
    }
