"""Operator-supplied model credential facts shared by LoopX host surfaces.

More than one host surface decides its default from what the operator
configured rather than from one individual's CLI login:

- ``loopx turn plan`` / ``loopx turn run-once`` select the default Turn host;
- the steward (manager) chat channel selects its default executor endpoint and
  model.

Both quote the credential facts from here so the rule cannot drift between the
Turn surface and the chat channel. Presence of a configured credential env var
is the whole signal: LoopX never invents a credential, never reads its value,
and never silently falls back to a personal subscription once one is present.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

# Credential env vars the operator-supplied provider already reads. Only the
# variable name is ever reported back; values stay in the process environment.
OPERATOR_CREDENTIAL_ENV_VARS = ("DEEPSEEK_API_KEY",)
OPERATOR_ENDPOINT_ENV_VAR = "DEEPSEEK_BASE_URL"


def env_text(name: str, environ: Mapping[str, str] | None = None) -> str | None:
    """Return a stripped env value, or ``None`` when it is unset or blank."""

    source = os.environ if environ is None else environ
    value = str(source.get(name, "") or "").strip()
    return value or None


def configured_operator_credential(
    environ: Mapping[str, str] | None = None,
) -> str | None:
    """Return the configured operator credential env var name, else ``None``."""

    for name in OPERATOR_CREDENTIAL_ENV_VARS:
        if env_text(name, environ) is not None:
            return name
    return None


def operator_credential_configured(
    environ: Mapping[str, str] | None = None,
) -> bool:
    """Whether any operator model credential is configured for this process."""

    return configured_operator_credential(environ) is not None
