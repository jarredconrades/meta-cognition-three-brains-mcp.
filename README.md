# Meta Cognition MCP forwarding bridge

This is a proxy to the **existing** authenticated Meta Cognition MCP endpoint. It does not directly connect to Supabase, implement Three-Brains reasoning, or store memory.

Render: Python Web Service, build `pip install -r requirements.txt`, start `uvicorn server:app --host 0.0.0.0 --port $PORT`.

Set `META_COGNITION_UPSTREAM` to the verified existing HTTPS service **origin** (without `/mcp`). Do not set Supabase service-role keys or database passwords.

**Limitation:** OAuth discovery and authorization URLs remain those of the original application, and the new proxy is not independently verified as a ChatGPT-connectable OAuth resource. Validate authorization, redirect/audience handling, MCP initialize, tools/list, and an authorized memory read before using this in production. If the original endpoint is already connectable, prefer it directly.
