# DNS setup for `psssst.dev`

5 minutes total. Cloudflare → GitHub Pages, no proxying.

## 1. Enable GitHub Pages

In `getubik/ubik` repo:

1. **Settings → Pages**
2. **Source:** "Deploy from a branch"
3. **Branch:** `main`, folder `/docs`
4. **Save**

GitHub will start a build. The default URL is
`https://getubik.github.io/ubik/`. Don't open it yet — we want
the custom domain bound first so it serves at the apex.

## 2. Cloudflare DNS records

In Cloudflare → `psssst.dev` → DNS → Records, add:

| Type | Name | Content | Proxy | TTL |
|------|------|---------|-------|-----|
| A | @ | `185.199.108.153` | DNS only | Auto |
| A | @ | `185.199.109.153` | DNS only | Auto |
| A | @ | `185.199.110.153` | DNS only | Auto |
| A | @ | `185.199.111.153` | DNS only | Auto |
| AAAA | @ | `2606:50c0:8000::153` | DNS only | Auto |
| AAAA | @ | `2606:50c0:8001::153` | DNS only | Auto |
| AAAA | @ | `2606:50c0:8002::153` | DNS only | Auto |
| AAAA | @ | `2606:50c0:8003::153` | DNS only | Auto |
| CNAME | www | `getubik.github.io.` | DNS only | Auto |

> **Important:** keep the proxy switch OFF (gray cloud, "DNS only").
> GitHub Pages issues its own Let's Encrypt certificate — Cloudflare
> proxying breaks the cert challenge and you'll get a TLS error for
> 24-48 hours.

## 3. Bind the custom domain in GitHub

Back in **Settings → Pages**:

1. **Custom domain:** `psssst.dev` → Save
2. Wait 1–5 minutes for DNS check ✅
3. Tick **Enforce HTTPS** once GitHub provisions the cert

The CNAME file at `docs/CNAME` is already committed, so GitHub knows
which domain to bind on every push.

## 4. Verify

```bash
curl -I https://psssst.dev
# expect: HTTP/2 200, server: GitHub.com

curl -s https://psssst.dev/.well-known/mcp-server-card | head
# expect: { "$schema": "...", "name": "ubik", ... }

dig psssst.dev +short
# expect: 4 GitHub Pages IPs
```

## 5. (Optional) Cloudflare proxy later

Once GitHub's cert is provisioned and HTTPS works, you *can* flip
the proxy on (orange cloud) for:

- **DDoS protection** (rare on a static landing, but free)
- **Analytics** (Cloudflare Web Analytics, no cookies)
- **Faster CDN** for international visitors

If you do, set Cloudflare SSL/TLS mode to **"Full (strict)"**,
not "Flexible" — the latter creates infinite redirect loops with
GitHub Pages.

## Migration plan when Sprint 2 lands

This whole setup is GitHub Pages serving a static landing + a
placeholder `mcp-server-card.json`. When the Python MCP server ships
in Sprint 2, we move:

- Landing page → either stays on GitHub Pages OR migrates to a
  small Astro/Next.js app deployed on the same Hetzner box
- `mcp-server-card` → served live from the running MCP server at
  `https://psssst.dev/.well-known/mcp-server-card`
- HTTPS endpoint at `psssst.dev/mcp` for Streamable HTTP transport
  with OAuth 2.1

DNS won't change — same `psssst.dev` apex, just a different upstream
(Hetzner instead of GitHub Pages). Cloudflare DNS swap is a 30-second
record edit.
