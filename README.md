# Meta Cognition MCP forwarding bridge

This is a proxy to the **existing** authenticated Meta Cognition MCP endpoint. It does not directly connect to Supabase, implement Three-Brains reasoning, or store memory.

Render: Python Web Service, build `pip install -r requirements.txt`, start `uvicorn server:app --host 0.0.0.0 --port $PORT`.

Set `META_COGNITION_UPSTREAM` to the verified existing HTTPS service **origin** (without `/mcp`). Do not set Supabase service-role keys or database passwords.

ChatGPT can use the resource-specific endpoint at `/mcp/oauth`. Set
`HOSTED_CHATGPT_BRIDGE_RESOURCE` on the existing upstream service to the full
public HTTPS bridge URL ending in `/mcp/oauth`. The upstream serves metadata at
`/.well-known/oauth-protected-resource/mcp/oauth` through the bridge and remains
the authorization issuer. The existing `/mcp` route continues to forward as before.

Deploy the upstream change before the bridge and verify discovery, ChatGPT
consent, code exchange and one authorized read. The bridge has no new secrets
or storage.
