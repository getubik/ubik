"""Trigger one full Daemon.run_audit_cycle() and exit.

Used to smoke-test the autonomous loop without waiting for daily_at.
Safe to run while the systemd daemon is up — the live daemon keeps
polling for callbacks; this oneshot just publishes proposals.

Args:
  --repo PATH         repo to audit (e.g. /opt/ubik or /opt/gyibb-watch)
  --notebook PATH     notebook root (e.g. /opt/ubik/research/self)
  --min-severity STR  floor for proposals (low/medium/high/critical)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from ubik.core.config import load as load_config
from ubik.core.daemon import Daemon, DaemonConfig


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True, type=Path)
    ap.add_argument("--notebook", required=True, type=Path)
    ap.add_argument(
        "--min-severity", default="medium", choices=["low", "medium", "high", "critical"]
    )
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s · %(name)s · %(levelname)s · %(message)s",
    )

    cfg = load_config(None, repo_path=args.repo)
    daemon = Daemon(
        config=cfg,
        notebook_root=args.notebook,
        daemon_config=DaemonConfig(
            daily_at="09:00",  # not used in oneshot
            min_proposal_severity=args.min_severity,
        ),
    )

    print(f"[oneshot] running run_audit_cycle for {args.repo}")
    await daemon.run_audit_cycle()
    print("[oneshot] done")


if __name__ == "__main__":
    asyncio.run(main())
