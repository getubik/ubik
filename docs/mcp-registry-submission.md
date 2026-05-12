# Publishing Ubik to the official MCP Registry

The Smithery descriptor at the repo root (`smithery.yaml`) covers the
Smithery community registry. This document covers the **official**
MCP Registry at [github.com/modelcontextprotocol/registry](https://github.com/modelcontextprotocol/registry)
— a separate, stricter listing governed by the MCP spec authors.

## What you need

- A GitHub account that owns `github.com/getubik/ubik` (i.e. has push access
  to the `getubik` org). The registry validates namespace ownership via
  GitHub OAuth — only the org admin can publish under `io.github.getubik/`.
- The `mcp-publisher` CLI. Two install paths:
  1. **Pre-built binary** from the registry's GitHub releases
     (https://github.com/modelcontextprotocol/registry/releases). Pick
     the right OS/arch tarball, extract, put on PATH.
  2. **Build from source** (needs Go):
     ```bash
     git clone https://github.com/modelcontextprotocol/registry
     cd registry
     make publisher
     # binary lands at ./bin/mcp-publisher
     ```

## What's already in this repo

`server.json` at the repo root — the registry's required manifest.
Schema: `https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json`.

Key fields:

- `name`: `io.github.getubik/ubik` (the GitHub-OAuth namespace convention)
- `version`: tracks `ubik.__version__` — bump on each release
- `packages[0].registryType`: `pypi`, identifier `psssst`, transport stdio
  (so the publisher knows users install via `pip install psssst` and
  launch the MCP via the `ubik mcp` console script)

## Publish (every release)

From the Ubik repo root with the CLI on PATH:

```bash
mcp-publisher login github
# OAuth pop-up; pick the GitHub account that owns getubik/
mcp-publisher publish
# reads server.json, signs the submission, posts it
```

The registry validates that the GitHub identity matches the namespace
prefix (`io.github.getubik/`). Once accepted, the entry appears in the
official registry index within a few minutes.

## Keep `server.json.version` in sync

Whenever we cut a new `psssst` release on PyPI, bump `version` and
`packages[0].version` in `server.json` to match, then re-run
`mcp-publisher publish`. The registry treats each version as an
immutable record — you can't replace, only add.

A future improvement: add a `mcp-publish.yml` GitHub Actions workflow
that runs `mcp-publisher publish` on tag push via GitHub OIDC, the
same way `publish.yml` ships to PyPI. The registry's OIDC support is
listed in the auth methods but the exact action wiring will land in a
follow-up.
