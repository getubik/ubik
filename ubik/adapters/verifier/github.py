"""
GitHub verifier — pushes the executor's branch and opens a PR.

Two paths, same outcome:
  1. **gh CLI** (preferred when on PATH) — handles auth, repo
     resolution, draft flag, body-from-stdin all with one subprocess.
  2. **Direct REST API** (fallback) — used if `gh` isn't installed
     and a `GITHUB_TOKEN` env var is present.

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

import httpx

from .base import VerifyOutcome, VerifyResult, VerifyTask, Verifier

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class GitHubVerifierConfig:
    """Configuration for the GitHub verifier."""

    gh_binary: str = "gh"
    token_env: str = "GITHUB_TOKEN"
    """Used by the REST fallback. gh CLI uses its own auth context."""

    push_remote: str = "origin"


_REPO_SLUG_RE = re.compile(r"github\.com[:/](?P<slug>[^/]+/[^/.]+)(?:\.git)?$")


class GitHubVerifier(Verifier):
    """Push + open-PR via gh CLI, with REST fallback."""

    name = "github"

    def __init__(self, config: GitHubVerifierConfig | None = None) -> None:
        self.config = config or GitHubVerifierConfig()

    async def verify(self, task: VerifyTask) -> VerifyResult:
        # 1. Push the branch
        push_ok, push_notes = await self._push(task)
        if not push_ok:
            return VerifyResult(
                outcome=VerifyOutcome.PUSH_FAILED,
                proposal_id=task.proposal_id,
                branch=task.branch,
                notes=push_notes,
            )

        # 2. Resolve repo slug
        slug = task.repo_slug or self._detect_repo_slug(task)
        if not slug:
            return VerifyResult(
                outcome=VerifyOutcome.PR_FAILED,
                proposal_id=task.proposal_id,
                branch=task.branch,
                notes=(
                    "Could not infer repo slug (e.g. 'getubik/ubik') from "
                    "`git remote get-url origin`. Pass repo_slug explicitly."
                ),
            )

        # 3. Open PR — gh CLI first, REST fallback.
        if shutil.which(self.config.gh_binary):
            url, num, notes = await self._pr_via_gh(task, slug)
        else:
            url, num, notes = await self._pr_via_rest(task, slug)

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
        """git push -u origin <branch> from the worktree path."""
        cmd = [
            "git", "push", "--set-upstream", self.config.push_remote, task.branch,
        ]
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
        """Look at `origin` URL and pull `org/repo` out of it."""
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

    async def _pr_via_gh(
        self, task: VerifyTask, slug: str,
    ) -> tuple[str | None, int | None, str]:
        cmd = [
            self.config.gh_binary, "pr", "create",
            "--repo", slug,
            "--head", task.branch,
            "--base", task.base_branch,
            "--title", task.title or f"Ubik · {task.branch}",
            "--body-file", "-",
        ]
        if task.draft:
            cmd.append("--draft")

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(task.worktree_path),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            stdout, _ = await asyncio.wait_for(
                proc.communicate(input=(task.body or "").encode("utf-8")),
                timeout=60,
            )
        except asyncio.TimeoutError:
            return None, None, "gh pr create hit 60-second cap"
        except OSError as e:
            return None, None, f"gh pr create could not start: {e}"

        text = (stdout or b"").decode("utf-8", errors="replace").strip()
        if proc.returncode != 0:
            return None, None, f"gh pr create failed (rc={proc.returncode}): {text[-800:]}"

        # gh prints the PR URL as the last line on success.
        url = next(
            (line for line in reversed(text.splitlines()) if line.startswith("https://")),
            None,
        )
        if not url:
            return None, None, f"gh succeeded but PR URL not in output: {text[-400:]}"

        num_match = re.search(r"/pull/(\d+)", url)
        num = int(num_match.group(1)) if num_match else None
        return url, num, "via gh CLI"

    async def _pr_via_rest(
        self, task: VerifyTask, slug: str,
    ) -> tuple[str | None, int | None, str]:
        token = os.environ.get(self.config.token_env)
        if not token:
            return None, None, (
                f"gh CLI not on PATH and {self.config.token_env} env var "
                "not set — cannot open PR. Install gh or set the token."
            )

        url = f"https://api.github.com/repos/{slug}/pulls"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        payload = {
            "title": task.title or f"Ubik · {task.branch}",
            "head": task.branch,
            "base": task.base_branch,
            "body": task.body or "",
            "draft": task.draft,
        }

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(url, headers=headers, json=payload)
        if resp.status_code not in (200, 201):
            return None, None, f"REST create PR failed ({resp.status_code}): {resp.text[:600]}"

        data = resp.json()
        return data.get("html_url"), data.get("number"), "via REST"
