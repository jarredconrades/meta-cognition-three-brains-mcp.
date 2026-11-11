"""Independent, read-only Meta Cognition MCP backed by existing Supabase mc tables.
No proxy, service-role key, database mutations, or OAuth token minting.
Requires a real Supabase user JWT and the existing restricted mc_runtime DB login.
"""
import json
import os
import re
from contextlib import asynccontextmanager
from urllib.parse import urlparse
from uuid import UUID

import asyncpg
import httpx
import jwt
from jwt import PyJWK
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

PROJECT = os.environ.get("SUPABASE_URL", "").rstrip("/")
DATABASE_URL = os.environ.get("DATABASE_URL", "")
DB_PASSWORD = os.environ.get("DATABASE_PASSWORD", "")
if not re.fullmatch(r"https://[a-z0-9]{20}\.supabase\.co", PROJECT):
    raise RuntimeError("SUPABASE_URL must be the canonical project origin")
dburl = urlparse(DATABASE_URL)
if dburl.scheme not in ("postgres", "postgresql") or not re.fullmatch(r"mc_runtime(?:\.[a-z0-9]+)?", dburl.username or ""):
    raise RuntimeError("DATABASE_URL must use the existing restricted mc_runtime role")
if not (DB_PASSWORD or dburl.password):
    raise RuntimeError("DATABASE_PASSWORD or URL password required")
ISSUER = PROJECT + "/auth/v1"
JWKS = ISSUER + "/.well-known/jwks.json"
TOOLS = [
    {"name": "memory_workspaces", "description": "List accessible workspaces",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "memory_records", "description": "Read existing goal/evidence records for one authorized workspace",
     "inputSchema": {"type": "object", "properties": {"workspace_id": {"type": "string"}}, "required": ["workspace_id"], "additionalProperties": False}},
    {"name": "memory_adaptive_snapshot", "description": "Read the existing adaptive user/business memory document for one authorized workspace",
     "inputSchema": {"type": "object", "properties": {"workspace_id": {"type": "string"}}, "required": ["workspace_id"], "additionalProperties": False}},
]
def error(message, status=401):
    return JSONResponse({"error": message}, status_code=status, headers={"Cache-Control": "no-store"})

async def identity(request):
    authorization = request.headers.get("authorization", "")
    if not re.fullmatch(r"Bearer [A-Za-z0-9._~-]{20,8192}", authorization):
        raise PermissionError("Supabase user bearer token required")
    token = authorization[7:]
    header = jwt.get_unverified_header(token)
    if header.get("alg") not in ("ES256", "RS256") or not isinstance(header.get("kid"), str):
        raise PermissionError("Unsupported JWT signing algorithm")
    async with httpx.AsyncClient(timeout=8) as client:
        response = await client.get(JWKS)
        response.raise_for_status()
        keys = response.json().get("keys", [])
    key = next((k for k in keys if k.get("kid") == header["kid"] and k.get("alg", header["alg"]) == header["alg"]), None)
    if key is None:
        raise PermissionError("Unknown JWT signing key")
    claims = jwt.decode(token, PyJWK.from_dict(key).key, algorithms=[header["alg"]],
                        audience="authenticated", issuer=ISSUER,
                        options={"require": ["exp", "iat", "sub", "session_id", "aal", "iss", "aud"]},
                        leeway=30)
    if claims.get("role") != "authenticated" or claims.get("is_anonymous") or claims.get("aal") != "aal2":
        raise PermissionError("Authenticated MFA session required")
    return str(UUID(claims["sub"])), str(UUID(claims["session_id"]))

async def query_memory(request, name, args):
    user, session = await identity(request)
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        async with conn.transaction(readonly=True):
            await conn.execute("select set_config('mc.user_id',$1,true), set_config('mc.session_id',$2,true)", user, session)
            active = await conn.fetchval("select mc.session_active()")
            if not active:
                raise PermissionError("Supabase session revoked or expired")
            if name == "memory_workspaces":
                rows = await conn.fetch("select w.id,w.name,m.role from mc.workspaces w join mc.memberships m on m.workspace_id=w.id order by w.name limit 100")
                return [dict(r) for r in rows]
            workspace = str(UUID(args["workspace_id"]))
            member = await conn.fetchrow("select role from mc.memberships where workspace_id=$1", UUID(workspace))
            if member is None:
                raise PermissionError("Workspace membership denied")
            paused = await conn.fetchval("select paused from mc.operator_controls where id=1")
            controls = await conn.fetchrow("select paused,access_status,access_until from mc.workspace_controls where workspace_id=$1", UUID(workspace))
            if paused is not False or not controls or controls["paused"] or controls["access_status"] != "staging" or controls["access_until"] is None:
                raise PermissionError("Workspace unavailable")
            from datetime import datetime, timezone
            if controls["access_until"] <= datetime.now(timezone.utc):
                raise PermissionError("Workspace access expired")
            if name == "memory_records":
                rows = await conn.fetch("select id,kind,title,body,version,updated_at from mc.records where workspace_id=$1 order by updated_at desc limit 100", UUID(workspace))
                return [dict(r) for r in rows]
            if name == "memory_adaptive_snapshot":
                document = await conn.fetchval("select document from mc.automation_state where workspace_id=$1", UUID(workspace))
                return (json.loads(document) if isinstance(document, str) else (document or {})).get("business", {}).get("adaptive_user_business_memory")
            raise ValueError("Unknown tool")

async def mcp(request):
    if request.method != "POST":
        return error("POST required", 405)
    if int(request.headers.get("content-length", "0") or 0) > 24000:
        return error("Request too large", 413)
    raw = await request.body()
    if len(raw) > 24000:
        return error("Request too large", 413)
    try:
        body = json.loads(raw)
        if not isinstance(body, dict) or body.get("jsonrpc") != "2.0":
            return error("Invalid JSON-RPC", 400)
        method, params = body.get("method"), body.get("params") or {}
        if method == "initialize":
            result = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}},
                      "serverInfo": {"name": "Meta Cognition independent read-only", "version": "0.1.0"}}
        elif method == "notifications/initialized":
            return JSONResponse({}, status_code=202)
        else:
            # Require valid identity even for tool discovery.
            if method == "tools/list":
                await identity(request)
                result = {"tools": TOOLS}
            elif method == "tools/call":
                name = params.get("name")
                args = params.get("arguments") or {}
                if name not in {t["name"] for t in TOOLS} or not isinstance(args, dict):
                    return error("Invalid tool", 400)
                if name != "memory_workspaces" and set(args) != {"workspace_id"}:
                    return error("workspace_id required", 400)
                data = await query_memory(request, name, args)
                result = {"content": [{"type": "text", "text": json.dumps(data, default=str)}]}
            else:
                return error("Unknown MCP method", 404)
        return JSONResponse({"jsonrpc": "2.0", "id": body.get("id"), "result": result},
                            headers={"Cache-Control": "no-store"})
    except (PermissionError, jwt.PyJWTError, ValueError, KeyError) as exc:
        return error(str(exc) if isinstance(exc, PermissionError) else "Invalid credentials or request", 401)
    except Exception:
        return error("Service unavailable", 503)

async def health(request):
    return JSONResponse({"ok": True, "mode": "independent-read-only", "database": "not-probed"})

@asynccontextmanager
async def lifespan(app):
    app.state.pool = await asyncpg.create_pool(dsn=DATABASE_URL, password=DB_PASSWORD or None,
                                               ssl="require", min_size=1, max_size=3, command_timeout=10)
    try:
        async with app.state.pool.acquire() as c:
            role = await c.fetchrow("select current_user as name,rolsuper,rolbypassrls from pg_roles where rolname=current_user")
            if not role or role["name"] != "mc_runtime" or role["rolsuper"] or role["rolbypassrls"]:
                raise RuntimeError("Restricted mc_runtime role required")
        yield
    finally:
        await app.state.pool.close()

app = Starlette(routes=[Route("/healthz", health, methods=["GET"]),
                        Route("/mcp", mcp, methods=["POST"])], lifespan=lifespan)
