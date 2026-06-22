# binance-data MCP Server

This repository contains a `d402`-enabled MCP server for binance-data.

## Local Testing

### 1. Review the environment file

The generated `.env` file contains the server wallet and operator values required to start the MCP server.


### 2. Start with Docker

```bash
./run_local_docker.sh
```

The MCP endpoint will be available at:

```text
http://localhost:8000/mcp
```

### 3. Run directly

```bash
uv run python server.py
```

## Runtime Notes

- `D402_TESTING_MODE=true` is the fastest way to test the payment flow locally
- set `D402_TESTING_MODE=false` to use the facilitator-backed flow
- the server exposes `/mcp` and `/health`

## Health Check

```bash
python mcp_health_check.py --url http://localhost:8000
```

## Next Step

Call the server with `d402HttpxClient` after it starts. The first paid `tools/call` request should return HTTP `402`, then retry automatically with payment.

## Deploy and Register

After local testing passes:

1. Deploy the server to a public URL.
2. Test every endpoint against the deployed URL:

   ```bash
   traia-iatp test-mcp \
     --base-url "https://your-deployed-server.com" \
     --tool-name "your_tool" \
     --arguments '{}'
   ```

3. Register the deployed server on d402.net once all endpoints are confirmed working.
   You need a d402.net account — sign up at [https://d402.net](https://d402.net) first.

   ```bash
   traia-iatp register-mcp \
     --email "you@example.com" \
     --name "binance-data MCP Server" \
     --description "Binance public market data (klines, depth, 24hr ticker)." \
     --url "https://your-deployed-server.com/mcp" \
     --server-address "$SERVER_ADDRESS" \
     --operator-address "$MCP_OPERATOR_ADDRESS" \
     --no-requires-auth \
     --token-symbol USDC \
     --endpoints-file ./endpoints.json
   ```

   `--server-address` and `--operator-address` are the **MCP server's** IATP wallet addresses
   — the values from the `create-mcp` output, not your personal wallet.

   See the IATP docs at `deployment-reference/mongodb-registration.md` for the full guide.