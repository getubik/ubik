---
slug: 2026-05-09-pssst-audit-gyibb
kind: audit
project: gyibb
title: "Pssst! Audit · GYIBB"
tags: ["audit", "single-shot"]
created_at: 2026-05-09T17:15:51.840026+00:00
---
# Pssst! Audit · GYIBB

## TL;DR

- The Ambassador container mounts the Docker socket — any code-execution vulnerability in that service is an instant host takeover.
- Three gateway implementations coexist in `anots_gateway/` with no deprecation markers; two are dead code that will confuse the next contributor.
- Runtime logs, circuit-breaker cache files (hundreds), and synthesized data are tracked in git — the repo will bloat forever.
- The web Dockerfile ships the full `node_modules` tree and a pile of debug `echo` statements to production.

## What I read

I read 20 provided files across 771 total (Python, Astro/TSX/JSX, JSON, YAML, shell, Markdown) at commit `966e50e`, representing a multi-agent content pipeline with 9 Docker services coordinated via Redis.

## Findings

### 1. Remove the Docker socket mount from Ambassador · critical
**Evidence**: `docker-compose.yml`, line in `node_5_ambassador` service:
```yaml
- /var/run/docker.sock:/var/run/docker.sock:ro  # Docker socket for real status
```
**Why it matters**: Read-only on the Docker socket still lets the container list all containers, inspect their env vars (including secrets from `.env`), pull images, and on many Docker versions execute arbitrary commands via `docker run`. A single vulnerability in the Ambassador FastAPI code — or any transitive dependency — becomes full host compromise.
**Proposed fix**: Remove the socket mount. If Ambassador needs container health, have it call the Gateway's `/api/v1/nodes` endpoint instead, or expose a dedicated health endpoint on each container that Shepherd aggregates.
**Risk**: low — this is a removal, not a refactor. Verify nothing in `node_5_ambassador/main.py` or `node_5_ambassador/mcp_server.py` actually calls the Docker API first.
**ETA**: 1 hour (read the code, remove the mount, verify container status still flows through Gateway).

### 2. Purge stale gateway implementations or mark deprecated · high
**Evidence**: Three files in `anots_gateway/`:
- `gateway.py` — in-memory asyncio queue, routing table uses old event names (`scrape_complete`, `synthesis_complete`). Never connects to Redis.
- `enhanced_gateway.py` — Redis pub/sub based. 750 lines. Uses `create_event_gateway` alias via import.
- `event_gateway.py` — Redis Streams based. The actual transport `gateway_server.py` imports from here.

The server (`gateway_server.py`, line ~28) does:
```python
from anots_gateway.event_gateway import create_event_gateway as create_enhanced_anots_gateway
```
So `gateway.py` and `enhanced_gateway.py` are dead code. But `enhanced_gateway.py` is 750 lines of plausible-looking infrastructure that will absolutely catch someone mid-debug.

**Why it matters**: A developer debugging event delivery will open `enhanced_gateway.py`, read 750 lines of pub/sub logic, and not realize the system is actually using Streams. This already-required an alias (`create_enhanced_anots_gateway`) that papered over the rename.

**Proposed fix**: Delete `gateway.py` and `enhanced_gateway.py`. If they're kept for reference, move them to `archive/` and strip the import alias in `gateway_server.py`.
**Risk**: low — dead code removal. Grep for any other imports of these modules first.
**ETA**: 30 minutes.

### 3. Stop tracking runtime data and logs in git · high
**Evidence**:
- `logs/gyibb.log`, `logs/gyibb.log.1`, `logs/gyibb.log.2`
- `data/circuit_breaker_cache/` — directory listing shows 50+ JSON files (the tree was truncated, likely hundreds)
- `data/raw_ugc_data.json`, `data/synthesized_content.json`
- `data/probe_tp.log`, `data/probe_tp.py`

**Why it matters**: Every pipeline run generates new cache files and log rotations. These are already committed. The circuit-breaker cache files have SHA-256 filenames suggesting they're keyed by URL — they'll grow without bound as new products are scraped. Log files will rotate in perpetuity. The repo will monotonically increase in size; `git clone` will slow to unusability.

**Proposed fix**: Add to `.gitignore`:
```
logs/
data/circuit_breaker_cache/
data/raw_ugc_data.json
data/synthesized_content.json
data/probe_tp.*
```
Then `git rm --cached` the tracked files. Consider a `.gitkeep` in `data/circuit_breaker_cache/` only if the directory must exist at checkout.
**Risk**: low — removing tracked generated files. Ensure Docker volumes mount correctly without these files pre-existing.
**ETA**: 30 minutes.

### 4. Fix the production web Dockerfile · medium
**Evidence**: `gyibb-web/Dockerfile`:
```dockerfile
# Runtime stage copies entire node_modules
COPY --from=builder /app/node_modules ./node_modules

# Nine debug echo blocks like:
RUN echo "=== Verifying copied files ===" && \
    ls -la && \
    echo "=== Checking src/lib/admin/ ===" && ...
```
**Why it matters**: The runtime image includes `devDependencies` (TypeScript, `@types/react`, etc.) — probably ~100 MB of unnecessary packages. The debug echoes are noisy, add build time, and mask real failures in CI logs.

**Proposed fix**: In the builder stage, after `npm run build`, run `npm prune --production` before copying `node_modules` to the runtime stage. Remove all `RUN echo "=== ...` diagnostic blocks, or gate them behind a `ARG DEBUG=false` build flag.
**Risk**: low — standard Docker optimization. Verify `npm prune --production` doesn't break Astro's SSR entry point (it shouldn't, since Astro bundles server code into `dist/`).
**ETA**: 1 hour.

### 5. Tighten the default ADMIN_PASSWORD and credential handling · high
**Evidence**: Multiple locations:
- `gyibb-web/.env.example`: `ADMIN_PASSWORD=change_me_before_deploy`
- `gyibb-web/Dockerfile`: `ARG ADMIN_PASSWORD=changeme`
- `docker-compose.yml`: `env_file: - .env` on every service (which means every container gets SMTP passwords, API keys, etc.)
- `.env.example` contains `HETZNER_VPS_IP=157.180.38.49` — a real IP in the example file

**Why it matters**: `changeme` as a Dockerfile default means a forgetful deploy exposes the admin panel. Every container receiving the full `.env` means a compromised Scout container (which scrapes untrusted web content) can read SMTP credentials and API keys. The Hetzner IP in the example file isn't a credential, but it signals the example was copied from a real deployment.

**Proposed fix**: (a) Remove the Dockerfile `ARG ADMIN_PASSWORD` default or set it to an empty string that fails fast. (b) Create per-service env files or use `environment:` blocks with only the variables each container needs. (c) Scrub the Hetzner IP from `.env.example`.
**Risk**: medium — refactoring env var delivery touches every service definition and requires testing each container starts correctly.
**ETA**: 2–3 hours.

### 6. Remove bogus `asyncio` dependency from requirements.txt · low
**Evidence**: `requirements.txt`, line ~12: `asyncio>=3.4.3`
**Why it matters**: `asyncio` is part of the Python standard library since 3.4. The PyPI `asyncio` package is a deprecated stub that hasn't been updated since 2014 and installs nothing useful. It's noise that suggests copy-paste from a template.
**Proposed fix**: Delete the line from both `requirements.txt` and `node_0_trendhunter/requirements.txt`.
**Risk**: low — it's a no-op dependency.
**ETA**: 5 minutes.

### 7. Address Redis OOM risk with volatile-lru policy · medium
**Evidence**: `docker-compose.yml`:
```yaml
command: redis-server --appendonly yes --maxmemory 2gb --maxmemory-policy volatile-lru
```
The comment says "critical state (evergreen cursors, product_queue) is TTL-less and therefore safe" — but that's the problem. Under memory pressure, Redis won't evict TTL-less keys. It will OOM and reject writes.

**Why it matters**: Circuit-breaker cache entries, product queue, node registrations, trend hunter state — these all grow with usage. If the 2 GB cap is hit, the pipeline silently stops accepting new data. The `volatile-lru` policy protects TTL-less keys *by refusing to evict them*, which means Redis just returns OOM errors on writes.

**Proposed fix**: Either (a) set `maxmemory-policy allkeys-lru` and accept that old state gets evicted (acceptable if nodes re-register and re-scrape), or (b) increase the cap and add monitoring, or (c) add TTLs to all non-critical keys. Option (a) is simplest. Add a Prometheus/exporter or at least a cron health check that alerts when Redis memory usage exceeds 80%.
**Risk**: medium — changing eviction policy could evict active state under pressure. Test with a full pipeline cycle.
**ETA**: 2 hours.

### 8. Fix schema.py incomplete validator · low
**Evidence**: `schema.py`, truncated at line ~500, `BrandData.validate_official_url`:
```python
@field_validator('official_url')
@classmethod
def validate_official_url(cls, v: str) -> str:
    """Brand site URL must be absolute."""
    if not v.startswith(('http://', 'https://')):
```
The method body is cut off. If it truly ends without a `raise` or `return`, Pydantic will call it successfully but do nothing — the validator is a no-op.

**Why it matters**: Malformed URLs in `official_url` would pass validation and propagate downstream to the editor and publisher nodes, potentially breaking Astro builds or generating broken links.
**Proposed fix**: Complete the validator:
```python
if not v.startswith(('http://', 'https://')):
    raise ValueError(f"Brand URL must be absolute: {v}")
return v
```
**Risk**: low — adding validation only rejects data that was already broken.
**ETA**: 5 minutes.

## What looks Healthy

- **Event-driven architecture is well-reasoned.** The move from pub/sub to Redis Streams (`event_gateway.py`) with consumer groups, DLQ, and retry logic shows operational maturity. The design doc in `ARCHITECTURE.md` matches the implementation.
- **Schema validation is thorough where complete.** `schema.py` uses Pydantic v2 with field validators, model validators, literal types for event discrimination, and sensible constraints (max lengths, value ranges). The `VideoData` auto-generating embed/thumbnail URLs is a nice touch.
- **Circuit breaker pattern is properly applied.** Per-URL SHA-256 keyed cache files, configurable thresholds and recovery timeouts, integrated into the harvester layer.
- **Infrastructure-as-code discipline.** Multiple `docker-compose.*.yml` files for staging/Hetzner/Coolify, a Caddyfile, per-node Dockerfiles — the deployment surface is explicit and versioned.
- **Recent commit hygiene.** Conventional commit prefixes (`feat:`, `fix:`, `refactor:`), scoped to node names, with concise descriptions. The 20 commits across 2 days show focused, incremental delivery.

## Open questions

1. **Is `node_0_trendhunter` and `node_1_scraper` actually running on a separate Forge machine via Tailscale?** The docker-compose comment says they do, but their Dockerfiles and service definitions still exist in the compose file. Are they started locally during development?

2. **Are any of the 50+ circuit-breaker cache files in `data/` committed on purpose, or is this an accidental `git add .`?** If intentional, they should be documented — they appear to be per-URL failure state.

3. **What is the current active LLM provider?** `.env.example` shows `LLM_PROVIDER=z.ai` with `Z_AI_MODEL=glm-5.1`, but the prompts directory has `_tr.yaml` and `_en.yaml` variants. Is the system running Turkish content, English, or both? This matters for the Writer node's prompt selection logic.

4. **The `review.rejected` event type exists in the schema but isn't mentioned in the architecture docs.** Is there a quality gate in Node 3 (Editor) that rejects and re-triggers synthesis? What happens to rejected reviews — do they retry, or are they lost?
