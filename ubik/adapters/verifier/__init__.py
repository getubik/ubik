"""Verifier adapters — push the executor's branch and open a PR/MR."""
from __future__ import annotations

from typing import TYPE_CHECKING

from .base import Verifier, VerifyOutcome, VerifyResult, VerifyTask
from .github import GitHubVerifier, GitHubVerifierConfig
from .gitlab import GitLabVerifier, GitLabVerifierConfig

if TYPE_CHECKING:
    from ubik.core.config import UbikConfig

__all__ = [
    "Verifier",
    "VerifyOutcome",
    "VerifyResult",
    "VerifyTask",
    "GitHubVerifier",
    "GitHubVerifierConfig",
    "GitLabVerifier",
    "GitLabVerifierConfig",
    "verifier_from_config",
]


def verifier_from_config(cfg: "UbikConfig") -> Verifier:
    """Resolve a Verifier from ``UbikConfig.verifier.pr.provider``."""
    provider = cfg.verifier.pr.provider
    if provider == "github":
        return GitHubVerifier()
    if provider == "gitlab":
        return GitLabVerifier()
    raise RuntimeError(
        f"verifier.pr.provider={provider!r} reached the factory but is "
        "not in the supported set. Loader bug — see "
        "SUPPORTED_VERIFIER_PROVIDERS."
    )
