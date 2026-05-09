"""Verifier adapters — push the executor's branch and open a PR."""
from .base import Verifier, VerifyOutcome, VerifyResult, VerifyTask
from .github import GitHubVerifier, GitHubVerifierConfig

__all__ = [
    "Verifier",
    "VerifyOutcome",
    "VerifyResult",
    "VerifyTask",
    "GitHubVerifier",
    "GitHubVerifierConfig",
]
