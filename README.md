# Independent Meta Cognition read-only MCP

Replaces the old proxy with a **direct** connection to the existing Supabase `mc` schema. Does not create tables or modify memory. Requires an existing restricted `mc_runtime` PostgreSQL account; service-role keys are forbidden. Every memory request validates the Supabase JWT, MFA assurance, active Auth session, RLS membership and workspace pause/expiry gates.

Render Python build: `pip install -r requirements.txt`; start: `uvicorn server:app --host 0.0.0.0 --port $PORT`.

Required Render environment: `SUPABASE_URL` (canonical Supabase project origin), `DATABASE_URL` (restricted mc_runtime Postgres connection), `DATABASE_PASSWORD` (existing restricted role password, stored only in Render secrets). Never commit credentials.

**Not yet ChatGPT OAuth ready:** This server validates existing Supabase access tokens but does not issue OAuth grants, implement PKCE or advertise OAuth discovery. It must not be represented as a completed ChatGPT connector. Existing staging service remains unchanged. Read-only MCP tools: `memory_workspaces`, `memory_records`, `memory_adaptive_snapshot`.

Deploy only after secrets are configured and validate negative tests (invalid JWT, expired/revoked session, unauthorized workspace, paused workspace) plus positive authorized read. No writes are implemented.
