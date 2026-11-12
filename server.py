"""Read/write-neutral MCP transport bridge to the existing Meta Cognition service.

All authentication, OAuth consent, workspace access, RLS and memory operations
remain in the original Meta Cognition application. This service stores nothing.
"""
import os
from urllib.parse import urlsplit

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response, JSONResponse
from starlette.routing import Route

UPSTREAM = os.environ.get("META_COGNITION_UPSTREAM", "").rstrip("/")
if not UPSTREAM or urlsplit(UPSTREAM).scheme != "https" or not urlsplit(UPSTREAM).hostname:
    raise RuntimeError("Set META_COGNITION_UPSTREAM to the existing HTTPS origin")
if urlsplit(UPSTREAM).path or urlsplit(UPSTREAM).query or urlsplit(UPSTREAM).fragment:
    raise RuntimeError("META_COGNITION_UPSTREAM must be an origin, not an endpoint")

ALLOWED_PATHS = {
    "/mcp", "/mcp/oauth", "/.well-known/oauth-protected-resource",
    "/.well-known/oauth-protected-resource/mcp",
    "/.well-known/oauth-protected-resource/mcp/oauth",
    "/.well-known/oauth-authorization-server",
    "/oauth/register", "/oauth/authorize", "/oauth/token",
}
ALLOWED_METHODS = {"GET", "POST", "DELETE"}
REQUEST_HEADERS = {
    "authorization", "accept", "content-type", "mcp-protocol-version",
    "mcp-session-id", "last-event-id", "origin", "user-agent",
}
RESPONSE_HEADERS = {
    "content-type", "www-authenticate", "allow", "mcp-session-id",
    "mcp-protocol-version", "location", "cache-control", "retry-after",
}

async def health(request: Request):
    return JSONResponse({"ok": True, "mode": "proxy-only"})

async def forward(request: Request):
    path = request.url.path
    if path not in ALLOWED_PATHS or request.method not in ALLOWED_METHODS:
        return JSONResponse({"error": "Not found"}, status_code=404)
    if request.headers.get("content-length", "0").isdigit() and int(request.headers.get("content-length", "0")) > 24000:
        return JSONResponse({"error": "Request too large"}, status_code=413)
    body = await request.body()
    if len(body) > 24000:
        return JSONResponse({"error": "Request too large"}, status_code=413)
    headers = {k: v for k, v in request.headers.items() if k.lower() in REQUEST_HEADERS}
    async with httpx.AsyncClient(timeout=httpx.Timeout(30, read=90), follow_redirects=False) as client:
        try:
            upstream = await client.request(
                request.method, httpx.URL(UPSTREAM + path).copy_with(query=request.scope["query_string"]),
                headers=headers, content=body,
            )
        except httpx.HTTPError:
            return JSONResponse({"error": "Upstream unavailable"}, status_code=502)
    out_headers = {k: v for k, v in upstream.headers.items() if k.lower() in RESPONSE_HEADERS}
    out_headers["Cache-Control"] = "no-store"
    return Response(upstream.content, status_code=upstream.status_code, headers=out_headers)

app = Starlette(routes=[Route("/healthz", health, methods=["GET"])] + [
    Route(p, forward, methods=["GET", "POST", "DELETE"]) for p in sorted(ALLOWED_PATHS)
])
