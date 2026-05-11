"""
GitLab verifier — pushes the executor's branch and opens a Merge Request.

Mirror of github.py adapted to GitLab's terminology and REST API:

  • "pull request" → "merge request"
  • slug "owner/repo" → URL-encoded project path "owner%2Frepo"
  • REST endpoint: POST /api/v4/projects/<id>/merge_requests
  • CLI: ``glab`` (preferred when on PATH) — handles auth + URL output

Two paths, same outcome:
  1. **glab CLI** (preferred when on PATH)
  2. **Direct REST API** (fallback) — used if ``glab`` isn't installed
     and a ``GITLAB_TOKEN`` env var is present.

We never auto-merge. Always returns a URL for the human to review.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from urllib.parse import quote

import httpx

from .base import VerifyOutcome, VerifyResult, VerifyTask, Verifier

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class GitLabVerifierConfig:
    """Configuration for the GitLab verifier."""

    glab_binary: str = "glab"
    token_env: str = "GITLAB_TOKEN"
    """Used by the REST fallback. glab CLI uses its own auth context."""

    api_base: str = "https://gitlab.com/api/v4"
    """Override for self-hosted GitLab instances."""

    push_remote: str = "origin"


_REPO_SLUG_RE = re.compile(
    r"gitlab\.com[:/](?P<slug>[^/]+(?:/[^/.]+)+?)(?:\.git)?$"
)


class GitLabVerifier(Verifier):
    """Push + open-MR via glab CLI, with REST fallback."""

    name = "gitlab"

    def __init__(self, config: GitLabVerifierConfig | None = None) -> None:
        self.config = config or GitLabVerifierConfig()

    async def verify(self, task: VerifyTask) -> VerifyResult:
        push_ok, push_notes = await self._push(task)
        if not push_ok:
            return VerifyResult(
                outcome=VerifyOutcome.PUSH_FAILED,
                proposal_id=task.proposal_id,
                branch=task.branch,
                notes=push_notes,
            )

        slug = task.repo_slug or self._detect_repo_slug(task)
        if not slug:
            return VerifyResult(
                outcome=VerifyOutcome.PR_FAILED,
                proposal_id=task.proposal_id,
                branch=task.branch,
                notes=(
                    "Could not infer GitLab project slug from "
                    "`git remote get-url origin`. Pass repo_slug "
                    "explicitly (use the full path, e.g. 'group/sub/repo')."
                ),
            )

        if shutil.which(self.config.glab_binary):
            url, num, notes = await self._mr_via_glab(task, slug)
        else:
            url, num, notes = await self._mr_via_rest(task, slug)

        if not url:
            return VerifyResult(
                outcome=VerifyOutcome.PR_FAILED,
                proposal_id=task.proposal_id,
                branch=task.branch,
                notes=notes,
            )

        return VerifyResult(
            outcome=VerifyOutcome.OPENED,
            proposal_id=task.proposal_id,
            branch=task.branch,
            pr_url=url,
            pr_number=num,
            notes=notes,
        )

    # ── internals ───────────────────────────────────────────────────────

    async def _push(self, task: VerifyTask) -> tuple[bool, str]:
        cmd = ["git", "push", "--set-upstream", self.config.push_remote, task.branch]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(task.worktree_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=120)
        except asyncio.TimeoutError:
            return False, "git push hit 2-minute cap"
        except OSError as e:
            return False, f"git push could not start: {e}"

        text = (stdout or b"").decode("utf-8", errors="replace")
        if proc.returncode != 0:
            return False, f"git push failed (rc={proc.returncode}): {text[-1000:]}"
        return True, ""

    def _detect_repo_slug(self, task: VerifyTask) -> str | None:
        try:
            out = subprocess.run(
                ["git", "remote", "get-url", self.config.push_remote],
                cwd=str(task.repo_path),
                capture_output=True, text=True, timeout=5, check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        url = (out.stdout or "").strip()
        m = _REPO_SLUG_RE.search(url)
        return m.group("slug") if m else None

    async def _mr_via_glab(
        self, task: VerifyTask, slug: str,
    ) -> tuple[str | None, int | None, str]:
        cmd = [
            self.config.glab_binary, "mr", "create",
            "--repo", slug,
            "--source-branch", task.branch,
            "--target-branch", task.base_branch,
            "--title", task.title or f"Ubik · {task.branch}",
            "--description", task.body or "",
            "--yes",  # don't prompt
        ]
        if task.draft:
            cmd.append("--draft")

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(task.worktree_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
        except asyncio.TimeoutError:
            return None, None, "glab mr create hit 60-second cap"
        except OSError as e:
            return None, None, f"glab mr create could not start: {e}"

        text = (stdout or b"").decode("utf-8", errors="replace").strip()
        if proc.returncode != 0:
            return None, None, f"glab mr create failed (rc={proc.returncode}): {text[-800:]}"

        url = next(
            (line for line in reversed(text.splitlines()) if line.startswith("https://")),
            None,
        )
        if not url:
            return None, None, f"glab succeeded but MR URL not in output: {text[-400:]}"

        # GitLab MR URLs end in /merge_requests/<n>
        num_match = re.search(r"/merge_requests/(\d+)", url)
        num = int(num_match.group(1)) if num_match else None
        return url, num, "via glab CLI"

    async def _mr_via_rest(
        self, task: VerifyTask, slug: str,
    ) -> tuple[str | None, int | None, str]:
        token = os.environ.get(self.config.token_env)
        if not token:
            return None, None, (
                f"glab CLI not on PATH and {self.config.token_env} env var "
                "not set — cannot open MR. Install glab or set the token."
            )

        # GitLab projects can be referenced by URL-encoded path.
        project_id = quote(slug, safe="")
        url = f"{self.config.api_base}/projects/{project_id}/merge_requests"
        headers = {
            "PRIVATE-TOKEN": token,
            "Content-Type": "application/json",
        }
        payload = {
            "source_branch": task.branch,
            "target_branch": task.base_branch,
            "title": task.title or f"Ubik · {task.branch}",
            "description": task.body or "",
        }
        if task.draft:
            payload["title"] = f"Draft: {payload['title']}"

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(url, headers=headers, json=payload)
        if resp.status_code not in (200, 201):
            return None, None, f"REST create MR failed ({resp.status_code}): {resp.text[:600]}"

        data = resp.json()
        return data.get("web_url"), data.get("iid"), "via REST"
