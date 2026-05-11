"""
Config loader — reads ubik.yaml (when present) or falls back to env-only defaults.

The schema here is the *contract* with users. Every field declared in
``ubik.example.yaml`` MUST round-trip through this loader; if the loader
ignores it, the example is lying. (See Slice 1 audit.)

Currently supported blocks:
    project, researcher.llm, researcher.schedule,
    executor.{type,sandbox,guardrails}, bridge.{type,rate_limit},
    verifier, notebook, cost.

Unsupported-but-roadmapped blocks are documented in docs/roadmap.md and
deliberately absent from ubik.example.yaml.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

SUPPORTED_EXECUTOR_TYPES = {"aider", "claude_agent_sdk"}
SUPPORTED_BRIDGE_TYPES = {"telegram"}
SUPPORTED_VERIFIER_PROVIDERS = {"github", "gitlab"}


class ConfigError(ValueError):
    """Raised on schema violations users can act on (bad type, unknown enum)."""


@dataclass(slots=True)
class LLMConfig:
    provider: str = "openai_compatible"
    base_url: str | None = "https://api.z.ai/api/coding/paas/v4"
    api_key_env: str = "Z_AI_API_KEY"
    model: str = "glm-5.1"
    thinking: bool = True
    max_tokens: int = 8000

    def to_litellm_dict(self) -> dict[str, Any]:
        return {
            "base_url": self.base_url,
            "api_key_env": self.api_key_env,
            "model": self.model,
        }


@dataclass(slots=True)
class ScheduleConfig:
    daily_at: str = "09:00"
    pulse_every_minutes: int = 0


@dataclass(slots=True)
class ExecutorSandboxConfig:
    worktree_dir: str = "./.ubik-worktrees"
    cost_cap_usd: float = 5.0
    time_cap_minutes: int = 15


@dataclass(slots=True)
class ExecutorGuardrailsConfig:
    cannot_push_to: list[str] = field(default_factory=lambda: ["main", "master", "production"])
    require_tests: bool = True
    require_pr_review: bool = True


@dataclass(slots=True)
class ExecutorConfig:
    type: str = "aider"
    sandbox: ExecutorSandboxConfig = field(default_factory=ExecutorSandboxConfig)
    guardrails: ExecutorGuardrailsConfig = field(default_factory=ExecutorGuardrailsConfig)


@dataclass(slots=True)
class BridgeRateLimitConfig:
    max_pushes_per_hour: int = 5
    cooldown_minutes_per_proposal: int = 60


@dataclass(slots=True)
class BridgeConfig:
    type: str = "telegram"
    token_env: str = "TELEGRAM_BOT_TOKEN"
    chat_id_env: str = "TELEGRAM_CHAT_ID"
    approver_chat_ids: list[int] = field(default_factory=list)
    rate_limit: BridgeRateLimitConfig = field(default_factory=BridgeRateLimitConfig)


@dataclass(slots=True)
class VerifierPRConfig:
    provider: str = "github"
    repo: str = ""
    base_branch: str = "main"
    auto_create: bool = True


@dataclass(slots=True)
class VerifierConfig:
    test_command: str | None = None
    build_command: str | None = None
    smoke_command: str | None = None
    pr: VerifierPRConfig = field(default_factory=VerifierPRConfig)


@dataclass(slots=True)
class NotebookConfig:
    storage: str = "filesystem"
    path: str = "./research"


@dataclass(slots=True)
class ProjectConfig:
    name: str = ""
    repo_path: str = "."
    default_branch: str = "main"


@dataclass(slots=True)
class CostConfig:
    """Global spend ceiling. ``track_only`` flips the kill switch into pure telemetry mode."""

    daily_usd_cap: float = 15.0
    alert_at_percent: int = 80
    track_only: bool = False
    max_proposals_per_day: int = 20


@dataclass(slots=True)
class UbikConfig:
    project: ProjectConfig = field(default_factory=ProjectConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    schedule: ScheduleConfig = field(default_factory=ScheduleConfig)
    executor: ExecutorConfig = field(default_factory=ExecutorConfig)
    bridge: BridgeConfig = field(default_factory=BridgeConfig)
    verifier: VerifierConfig = field(default_factory=VerifierConfig)
    notebook: NotebookConfig = field(default_factory=NotebookConfig)
    cost: CostConfig = field(default_factory=CostConfig)


def _validate_enum(value: str, allowed: set[str], field_name: str) -> str:
    if value not in allowed:
        raise ConfigError(
            f"{field_name}={value!r} is not supported. "
            f"Allowed: {sorted(allowed)}. "
            f"(Roadmap entries are documented in docs/roadmap.md.)"
        )
    return value


def load(path: Path | str | None = None, *, repo_path: Path | str | None = None) -> UbikConfig:
    """Load ubik.yaml or return defaults.

    Resolution order for the config path:
      1. Explicit ``path`` argument
      2. ``UBIK_CONFIG`` env var
      3. ``./ubik.yaml`` in ``repo_path`` (default: cwd)
    """
    if path is None:
        env_path = os.environ.get("UBIK_CONFIG")
        if env_path:
            path = Path(env_path)
        else:
            base = Path(repo_path or Path.cwd())
            candidate = base / "ubik.yaml"
            path = candidate if candidate.exists() else None

    cfg = UbikConfig()
    if repo_path is not None:
        cfg.project.repo_path = str(Path(repo_path).resolve())
        cfg.project.name = Path(repo_path).resolve().name

    if path is None:
        return cfg

    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}

    # Project ----------------------------------------------------------------
    if proj := raw.get("project"):
        cfg.project.name = proj.get("name", cfg.project.name)
        cfg.project.repo_path = str(Path(proj.get("repo_path", cfg.project.repo_path)).resolve())
        cfg.project.default_branch = proj.get("default_branch", cfg.project.default_branch)

    # Researcher -> LLM + schedule ------------------------------------------
    if researcher := raw.get("researcher"):
        if llm := researcher.get("llm"):
            cfg.llm.provider = llm.get("provider", cfg.llm.provider)
            cfg.llm.base_url = llm.get("base_url", cfg.llm.base_url)
            cfg.llm.api_key_env = llm.get("api_key_env", cfg.llm.api_key_env)
            cfg.llm.model = llm.get("model", cfg.llm.model)
            cfg.llm.thinking = llm.get("thinking", cfg.llm.thinking)
            cfg.llm.max_tokens = llm.get("max_tokens", cfg.llm.max_tokens)

        if sched := researcher.get("schedule"):
            cfg.schedule.daily_at = sched.get("daily_at", cfg.schedule.daily_at)
            cfg.schedule.pulse_every_minutes = sched.get(
                "pulse_every_minutes", cfg.schedule.pulse_every_minutes
            )

    # Executor --------------------------------------------------------------
    if execr := raw.get("executor"):
        cfg.executor.type = _validate_enum(
            execr.get("type", cfg.executor.type),
            SUPPORTED_EXECUTOR_TYPES,
            "executor.type",
        )
        if sb := execr.get("sandbox"):
            cfg.executor.sandbox.worktree_dir = sb.get(
                "worktree_dir", cfg.executor.sandbox.worktree_dir
            )
            cfg.executor.sandbox.cost_cap_usd = float(
                sb.get("cost_cap_usd", cfg.executor.sandbox.cost_cap_usd)
            )
            cfg.executor.sandbox.time_cap_minutes = int(
                sb.get("time_cap_minutes", cfg.executor.sandbox.time_cap_minutes)
            )
        if gr := execr.get("guardrails"):
            blocked = gr.get("cannot_push_to", cfg.executor.guardrails.cannot_push_to)
            cfg.executor.guardrails.cannot_push_to = list(blocked or [])
            cfg.executor.guardrails.require_tests = bool(
                gr.get("require_tests", cfg.executor.guardrails.require_tests)
            )
            cfg.executor.guardrails.require_pr_review = bool(
                gr.get("require_pr_review", cfg.executor.guardrails.require_pr_review)
            )

    # Bridge ----------------------------------------------------------------
    if br := raw.get("bridge"):
        cfg.bridge.type = _validate_enum(
            br.get("type", cfg.bridge.type),
            SUPPORTED_BRIDGE_TYPES,
            "bridge.type",
        )
        cfg.bridge.token_env = br.get("token_env", cfg.bridge.token_env)
        cfg.bridge.chat_id_env = br.get("chat_id_env", cfg.bridge.chat_id_env)
        # YAML lists with only comments parse as None — treat as empty.
        approvers = br.get("approver_chat_ids", cfg.bridge.approver_chat_ids)
        cfg.bridge.approver_chat_ids = list(approvers or [])
        if rl := br.get("rate_limit"):
            cfg.bridge.rate_limit.max_pushes_per_hour = int(
                rl.get("max_pushes_per_hour", cfg.bridge.rate_limit.max_pushes_per_hour)
            )
            cfg.bridge.rate_limit.cooldown_minutes_per_proposal = int(
                rl.get(
                    "cooldown_minutes_per_proposal",
                    cfg.bridge.rate_limit.cooldown_minutes_per_proposal,
                )
            )

    # Verifier --------------------------------------------------------------
    if vr := raw.get("verifier"):
        cfg.verifier.test_command = vr.get("test_command", cfg.verifier.test_command)
        cfg.verifier.build_command = vr.get("build_command", cfg.verifier.build_command)
        cfg.verifier.smoke_command = vr.get("smoke_command", cfg.verifier.smoke_command)
        if pr := vr.get("pr"):
            cfg.verifier.pr.provider = _validate_enum(
                pr.get("provider", cfg.verifier.pr.provider),
                SUPPORTED_VERIFIER_PROVIDERS,
                "verifier.pr.provider",
            )
            cfg.verifier.pr.repo = pr.get("repo", cfg.verifier.pr.repo)
            cfg.verifier.pr.base_branch = pr.get("base_branch", cfg.verifier.pr.base_branch)
            cfg.verifier.pr.auto_create = bool(pr.get("auto_create", cfg.verifier.pr.auto_create))

    # Notebook --------------------------------------------------------------
    if nb := raw.get("notebook"):
        cfg.notebook.storage = nb.get("storage", cfg.notebook.storage)
        cfg.notebook.path = nb.get("path", cfg.notebook.path)

    # Cost ------------------------------------------------------------------
    if cost := raw.get("cost"):
        cfg.cost.daily_usd_cap = float(cost.get("daily_usd_cap", cfg.cost.daily_usd_cap))
        cfg.cost.alert_at_percent = int(cost.get("alert_at_percent", cfg.cost.alert_at_percent))
        cfg.cost.track_only = bool(cost.get("track_only", cfg.cost.track_only))
        cfg.cost.max_proposals_per_day = int(
            cost.get("max_proposals_per_day", cfg.cost.max_proposals_per_day)
        )

    return cfg
