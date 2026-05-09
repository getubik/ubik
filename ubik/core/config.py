"""
Config loader — reads ubik.yaml (when present) or falls back to env-only defaults.

Sprint 1 only needs the `researcher.llm` block; later sprints add
`executor`, `bridge`, `verifier`, `notebook`, `mcp`, `observability`.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(slots=True)
class LLMConfig:
    """Subset of researcher.llm needed for Sprint 1."""

    provider: str = "openai_compatible"
    base_url: str | None = "https://api.z.ai/api/coding/paas/v4"
    api_key_env: str = "Z_AI_API_KEY"
    model: str = "glm-5.1"
    thinking: bool = True
    max_tokens: int = 8000

    def to_litellm_dict(self) -> dict[str, Any]:
        """Shape that `llm_from_config` (in adapters.llm) consumes."""
        return {
            "base_url": self.base_url,
            "api_key_env": self.api_key_env,
            "model": self.model,
        }


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
class UbikConfig:
    """Top-level config. Defaults work for an env-only invocation."""

    project: ProjectConfig = field(default_factory=ProjectConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    notebook: NotebookConfig = field(default_factory=NotebookConfig)


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

    # Researcher -> LLM ------------------------------------------------------
    if researcher := raw.get("researcher"):
        if llm := researcher.get("llm"):
            cfg.llm.provider = llm.get("provider", cfg.llm.provider)
            cfg.llm.base_url = llm.get("base_url", cfg.llm.base_url)
            cfg.llm.api_key_env = llm.get("api_key_env", cfg.llm.api_key_env)
            cfg.llm.model = llm.get("model", cfg.llm.model)
            cfg.llm.thinking = llm.get("thinking", cfg.llm.thinking)
            cfg.llm.max_tokens = llm.get("max_tokens", cfg.llm.max_tokens)

    # Notebook ---------------------------------------------------------------
    if nb := raw.get("notebook"):
        cfg.notebook.storage = nb.get("storage", cfg.notebook.storage)
        cfg.notebook.path = nb.get("path", cfg.notebook.path)

    return cfg
