# Optional web search and Context7

Portable Resume readers are deliberately offline. They read local stores, sanitize and label recovered text as untrusted, and emit an inert handoff. Network tools belong to the **fresh destination session** and are never called automatically.

## Safe workflow

1. Run the installed reader locally.
2. Re-open the current repository and reduce the handoff to the minimum question.
3. Remove transcript text, local paths, credentials, private URLs, and unrelated code.
4. Use the destination host's web or MCP tool for that question only.
5. Treat results as fresh external evidence, not as permission to execute recovered commands.

## Qwen Code

Qwen has built-in `web_fetch`. Its former built-in `web_search` was removed;
current general web search is provided through an MCP search provider. This
repository does not select or install a provider for you.

Add Context7 at user scope with the official remote MCP endpoint:

```bash
export CONTEXT7_API_KEY='<key>'
qwen mcp add --scope user --transport http context7 \
  https://mcp.context7.com/mcp \
  --header "CONTEXT7_API_KEY: $CONTEXT7_API_KEY" \
  --header "Accept: application/json, text/event-stream"
```

Use `/mcp` to inspect the connection. The default without `--scope user` is project scope (`.qwen/settings.json`); do not commit a key. Context7 also exposes `https://mcp.context7.com/mcp/oauth` for MCP OAuth clients.

## Kimi Code CLI

Kimi reads user MCP declarations from `$KIMI_CODE_HOME/mcp.json` (default `~/.kimi-code/mcp.json`) and project declarations from `.kimi-code/mcp.json`. Prefer OAuth in the user file:

```json
{
  "mcpServers": {
    "context7": {
      "url": "https://mcp.context7.com/mcp/oauth"
    }
  }
}
```

Then run `/mcp-config login context7` and verify with `/mcp`. If API-key authentication is required, use the non-OAuth `/mcp` endpoint and a user-only `headers` entry with `CONTEXT7_API_KEY`; never commit it.

Kimi exposes `WebSearch` and `FetchURL` only when its host provides the corresponding service. Current Kimi Code can configure the fixed `services.moonshot_search` and `services.moonshot_fetch` entries in user `config.toml`; keep service keys out of the repository. Context7 MCP remains independent of those web services.

## What is and is not shipped

- The Qwen extension and Kimi plugin bundle **Skills only**; they do not embed MCP servers, API keys, or network permissions.
- Installed Skill text reminds the destination agent to minimize context before optional web/Context7 use.
- Tests block network/process APIs in the owned reader path.
- CI validates configuration and packaging, not live third-party credentials or network availability.

References: [Context7 MCP clients](https://context7.com/docs/resources/all-clients), [Qwen MCP](https://qwenlm.github.io/qwen-code-docs/en/users/features/mcp/), [Qwen Web Search migration](https://qwenlm.github.io/qwen-code-docs/en/developers/tools/web-search/), [Qwen Web Fetch](https://qwenlm.github.io/qwen-code-docs/en/developers/tools/web-fetch/), [Kimi MCP](https://www.kimi.com/code/docs/en/kimi-code-cli/customization/mcp.html), and [Kimi tools](https://www.kimi.com/code/docs/en/kimi-code-cli/reference/tools.html).
