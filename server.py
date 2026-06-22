#!/usr/bin/env python3
"""
binance-data MCP Server - FastMCP with D402 Transport Wrapper

Uses FastMCP from official MCP SDK with D402MCPTransport wrapper for HTTP 402.

Architecture:
- FastMCP for tool decorators and Context objects
- D402MCPTransport wraps the /mcp route for HTTP 402 interception
- Proper HTTP 402 status codes (not JSON-RPC wrapped)

Generated from OpenAPI: https://data-api.binance.vision

Environment Variables:
- SERVER_ADDRESS: Payment address (IATP wallet contract)
- MCP_OPERATOR_PRIVATE_KEY: Operator signing key
- D402_TESTING_MODE: Skip facilitator (default: true)
"""

import os
import logging
import sys
from typing import Any, Dict, List, Optional
from datetime import datetime

import requests
from retry import retry
from dotenv import load_dotenv
import uvicorn

load_dotenv()

# Configure logging
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('binance-data_mcp')

# FastMCP from official SDK
from mcp.server.fastmcp import FastMCP, Context
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware
from starlette.routing import Route

# D402 payment protocol - using Starlette middleware
from traia_iatp.d402.starlette_middleware import D402PaymentMiddleware
from traia_iatp.d402.mcp_middleware import require_payment_for_tool, get_active_api_key
from traia_iatp.d402.payment_introspection import extract_payment_configs_from_mcp
from traia_iatp.d402.types import TokenAmount, TokenAsset, EIP712Domain

# Configuration
STAGE = os.getenv("STAGE", "MAINNET").upper()
PORT = int(os.getenv("PORT", "8000"))
SERVER_ADDRESS = os.getenv("SERVER_ADDRESS")
if not SERVER_ADDRESS:
    raise ValueError("SERVER_ADDRESS required for payment protocol")

API_KEY = None

logger.info("="*80)
logger.info(f"binance-data MCP Server (FastMCP + D402 Wrapper)")
logger.info(f"API: https://data-api.binance.vision")
logger.info(f"Payment: {SERVER_ADDRESS}")
logger.info("="*80)

# Create FastMCP server
mcp = FastMCP("binance-data MCP Server", host="0.0.0.0")

logger.info(f"✅ FastMCP server created")

# ============================================================================
# TOOL IMPLEMENTATIONS
# ============================================================================
# Add or edit tools only inside this region.
# Keep the middleware and app setup below unchanged.
# START_CUSTOM_TOOLS
@mcp.tool()
@require_payment_for_tool(
    price=TokenAmount(
        amount="0",
        asset=TokenAsset(
            address="0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
            decimals=6,
            network="arbitrum_one",
            eip712=EIP712Domain(name="IATPWallet", version="1")
        )
    ),
    description="Kline/candlestick bars for a symbol.",
)
async def binance_klines(
    context: Context,
    path_params: Optional[Dict[str, Any]] = None,
    query_params: Optional[Dict[str, Any]] = None,
) -> Any:
    """
    Kline/candlestick bars for a symbol.

    Args:
        context: MCP context object
        path_params: Values used to replace path parameters in the endpoint path
        query_params: Query string values for the upstream GET request
    """
    base_url = "https://data-api.binance.vision"
    endpoint_path = "/api/v3/klines"
    method = "GET"
    headers = {}
    try:
        url = base_url + endpoint_path
        for key, value in (path_params or {}).items():
            url = url.replace("{" + key + "}", str(value))

        request_kwargs = {
            "headers": headers,
            "timeout": 30,
        }
        if query_params:
            request_kwargs["params"] = query_params
        response = requests.request(method, url, **request_kwargs)
        response.raise_for_status()

        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            return response.json()

        return {
            "status_code": response.status_code,
            "text": response.text,
        }
    except Exception as e:
        logger.error(f"Error in binance_klines: {e}")
        return {"error": str(e), "endpoint": endpoint_path}


@mcp.tool()
@require_payment_for_tool(
    price=TokenAmount(
        amount="0",
        asset=TokenAsset(
            address="0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
            decimals=6,
            network="arbitrum_one",
            eip712=EIP712Domain(name="IATPWallet", version="1")
        )
    ),
    description="Order book depth for a symbol.",
)
async def binance_depth(
    context: Context,
    path_params: Optional[Dict[str, Any]] = None,
    query_params: Optional[Dict[str, Any]] = None,
) -> Any:
    """
    Order book depth for a symbol.

    Args:
        context: MCP context object
        path_params: Values used to replace path parameters in the endpoint path
        query_params: Query string values for the upstream GET request
    """
    base_url = "https://data-api.binance.vision"
    endpoint_path = "/api/v3/depth"
    method = "GET"
    headers = {}
    try:
        url = base_url + endpoint_path
        for key, value in (path_params or {}).items():
            url = url.replace("{" + key + "}", str(value))

        request_kwargs = {
            "headers": headers,
            "timeout": 30,
        }
        if query_params:
            request_kwargs["params"] = query_params
        response = requests.request(method, url, **request_kwargs)
        response.raise_for_status()

        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            return response.json()

        return {
            "status_code": response.status_code,
            "text": response.text,
        }
    except Exception as e:
        logger.error(f"Error in binance_depth: {e}")
        return {"error": str(e), "endpoint": endpoint_path}


@mcp.tool()
@require_payment_for_tool(
    price=TokenAmount(
        amount="0",
        asset=TokenAsset(
            address="0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
            decimals=6,
            network="arbitrum_one",
            eip712=EIP712Domain(name="IATPWallet", version="1")
        )
    ),
    description="24hr rolling window price change statistics.",
)
async def binance_ticker_24hr(
    context: Context,
    path_params: Optional[Dict[str, Any]] = None,
    query_params: Optional[Dict[str, Any]] = None,
) -> Any:
    """
    24hr rolling window price change statistics.

    Args:
        context: MCP context object
        path_params: Values used to replace path parameters in the endpoint path
        query_params: Query string values for the upstream GET request
    """
    base_url = "https://data-api.binance.vision"
    endpoint_path = "/api/v3/ticker/24hr"
    method = "GET"
    headers = {}
    try:
        url = base_url + endpoint_path
        for key, value in (path_params or {}).items():
            url = url.replace("{" + key + "}", str(value))

        request_kwargs = {
            "headers": headers,
            "timeout": 30,
        }
        if query_params:
            request_kwargs["params"] = query_params
        response = requests.request(method, url, **request_kwargs)
        response.raise_for_status()

        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            return response.json()

        return {
            "status_code": response.status_code,
            "text": response.text,
        }
    except Exception as e:
        logger.error(f"Error in binance_ticker_24hr: {e}")
        return {"error": str(e), "endpoint": endpoint_path}



# Example tool pattern:
#
# @mcp.tool()
# @require_payment_for_tool(
#     price=TokenAmount(
#         amount="10000",
#         asset=TokenAsset(
#             address=os.getenv("DEFAULT_SETTLEMENT_TOKEN"),
#             decimals=6,
#             network=os.getenv("DEFAULT_SETTLEMENT_NETWORK", "arbitrum_one"),
#             eip712=EIP712Domain(name="IATPWallet", version="1"),
#         ),
#     ),
#     description="Describe what this tool does",
# )
# async def example_tool(
#     context: Context,
#     query_params: Optional[Dict[str, Any]] = None,
# ) -> Any:
#     """
#     Replace this sample with your own tool logic.
#     Add more tools in this same region and keep the rest of the file unchanged.
#     """
#     # For upstream APIs that need auth:
#     # api_key = get_active_api_key(context)
#     # headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
#     return {"message": "replace this example with your MCP tool logic"}

# END_CUSTOM_TOOLS

# ============================================================================
# APPLICATION SETUP WITH STARLETTE MIDDLEWARE
# ============================================================================

def create_app_with_middleware():
    """
    Create Starlette app with d402 payment middleware.

    Strategy:
    1. Get FastMCP's Starlette app via streamable_http_app()
    2. Extract payment configs from @require_payment_for_tool decorators
    3. Add Starlette middleware with extracted configs
    4. Single source of truth - no duplication!
    """
    logger.info("🔧 Creating FastMCP app with middleware...")

    # Get FastMCP's Starlette app
    app = mcp.streamable_http_app()
    logger.info(f"✅ Got FastMCP Starlette app")

    # Extract payment configs from decorators (single source of truth!)
    tool_payment_configs = extract_payment_configs_from_mcp(mcp, SERVER_ADDRESS)
    logger.info(f"📊 Extracted {len(tool_payment_configs)} payment configs from @require_payment_for_tool decorators")

    # D402 Configuration
    facilitator_url = os.getenv("FACILITATOR_URL") or os.getenv("D402_FACILITATOR_URL")
    operator_key = os.getenv("MCP_OPERATOR_PRIVATE_KEY")
    network = os.getenv("NETWORK") or os.getenv("DEFAULT_SETTLEMENT_NETWORK", "arbitrum_one")
    testing_mode = os.getenv("D402_TESTING_MODE", "true").lower() == "true"

    # Log D402 configuration with prominent facilitator info
    logger.info("="*60)
    logger.info("D402 Payment Protocol Configuration:")
    logger.info(f"  Server Address: {SERVER_ADDRESS}")
    logger.info(f"  Network: {network}")
    logger.info(f"  Operator Key: {'✅ Set' if operator_key else '❌ Not set'}")
    logger.info(f"  Testing Mode: {'⚠️  ENABLED (verification without settlement)' if testing_mode else '✅ DISABLED (uses facilitator and settlement)'}")
    logger.info("="*60)

    if not facilitator_url and not testing_mode:
        logger.error("❌ FACILITATOR_URL required when testing_mode is disabled!")
        raise ValueError("Set FACILITATOR_URL or enable D402_TESTING_MODE=true")

    if facilitator_url:
        logger.info(f"🌐 FACILITATOR: {facilitator_url}")
        if "localhost" in facilitator_url or "127.0.0.1" in facilitator_url or "host.docker.internal" in facilitator_url:
            logger.info(f"   📍 Using LOCAL facilitator for development")
        else:
            logger.info(f"   🌍 Using REMOTE facilitator for production")
    else:
        logger.warning("⚠️  D402 Testing Mode - Facilitator bypassed")
    logger.info("="*60)

    # Add CORS middleware first (processes before other middleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Allow all origins
        allow_credentials=True,
        allow_methods=["*"],  # Allow all methods
        allow_headers=["*"],  # Allow all headers
        expose_headers=["mcp-session-id"],  # Expose custom headers to browser
    )
    logger.info("✅ Added CORS middleware (allow all origins, expose mcp-session-id)")

    # Add D402 payment middleware with extracted configs
    app.add_middleware(
        D402PaymentMiddleware,
        tool_payment_configs=tool_payment_configs,
        server_address=SERVER_ADDRESS,
        requires_auth=False,  # Only checks payment
        internal_api_key=None,  # No API key needed for public APIs
        testing_mode=testing_mode,
        facilitator_url=facilitator_url,
        facilitator_api_key=os.getenv("D402_FACILITATOR_API_KEY"),
        server_name="binance-data-mcp-server"  # MCP server ID for tracking
    )
    logger.info("✅ Added D402PaymentMiddleware")
    logger.info("   - Payment-only mode")

    # Add health check endpoint (bypasses middleware).
    # Note: app.route() decorator was removed in Starlette >= 0.21.
    # Define the function then register it via app.router.routes.append().
    async def health_check(request: Request) -> JSONResponse:
        """Health check endpoint for container orchestration."""
        return JSONResponse(
            content={
                "status": "healthy",
                "service": "binance-data-mcp-server",
                "timestamp": datetime.now().isoformat()
            }
        )
    app.router.routes.append(Route("/health", health_check, methods=["GET"]))
    logger.info("✅ Added /health endpoint")

    return app

if __name__ == "__main__":
    logger.info("="*80)
    logger.info(f"Starting binance-data MCP Server")
    logger.info("="*80)
    logger.info("Architecture:")
    logger.info("  1. D402PaymentMiddleware intercepts requests")
    logger.info("     - Checks payment → HTTP 402 if missing")
    logger.info("  2. FastMCP processes valid requests with tool decorators")
    logger.info("="*80)

    # Create app with middleware
    app = create_app_with_middleware()

    # Run with uvicorn
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=PORT,
        log_level=os.getenv("LOG_LEVEL", "info").lower()
    )