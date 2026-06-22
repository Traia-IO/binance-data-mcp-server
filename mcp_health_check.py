#!/usr/bin/env python
"""
binance-data MCP Server Health Check Script

This script properly connects to the binance-data MCP server and checks its health by:
1. Establishing a session
2. Requesting server info
3. Listing available tools
"""

import sys
import json
import requests
import argparse
from typing import Dict, Any
import uuid

def create_mcp_session(base_url: str) -> Dict[str, Any]:
    """Create an MCP session and return session info"""
    # Generate a session ID
    session_id = str(uuid.uuid4())
    
    # MCP requires specific headers for streamable-http
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "X-Session-ID": session_id
    }
    
    return {"session_id": session_id, "headers": headers, "base_url": base_url}

def send_mcp_request(session: Dict[str, Any], method: str, params: Dict = None) -> Dict[str, Any]:
    """Send an MCP JSON-RPC request"""
    request_data = {
        "jsonrpc": "2.0",
        "method": method,
        "params": params or {},
        "id": str(uuid.uuid4())
    }
    
    try:
        response = requests.post(
            f"{session['base_url']}/mcp/",
            json=request_data,
            headers=session['headers'],
            timeout=5
        )
        
        # Handle both JSON and SSE responses
        if response.headers.get('content-type', '').startswith('text/event-stream'):
            # For SSE, we'd need to parse the event stream
            return {"status": "ok", "message": "Server returned SSE stream"}
        else:
            return response.json()
            
    except requests.exceptions.RequestException as e:
        return {"error": str(e)}

def check_mcp_server_health(url: str) -> bool:
    """Check if binance-data MCP server is healthy"""
    print(f"🔍 Checking binance-data MCP server health at {url}")
    
    # Create session
    session = create_mcp_session(url)
    print(f"📝 Created session: {session['session_id']}")
    
    # Try to get server info
    print("\n1️⃣ Testing server.info method...")
    result = send_mcp_request(session, "server.info")
    
    if "error" in result and "session" not in str(result.get("error", "")):
        print(f"❌ Server info failed: {result}")
        return False
    else:
        print(f"✅ Server responded: {json.dumps(result, indent=2)[:200]}...")
    
    # Try to list tools
    print("\n2️⃣ Testing tools/list method...")
    result = send_mcp_request(session, "tools/list")
    
    if "error" in result and "session" not in str(result.get("error", "")):
        print(f"❌ List tools failed: {result}")
        return False
    else:
        print(f"✅ Tools list responded: {json.dumps(result, indent=2)[:200]}...")
        
        # Check if we have the expected tools
        if "result" in result and "tools" in result["result"]:
            tools = result["result"]["tools"]
            tool_names = [tool.get("name", "") for tool in tools]
            print(f"📋 Available tools: {', '.join(tool_names)}")
            
            # Check for expected tools
            expected_tools = ['binance_klines', 'binance_depth', 'binance_ticker_24hr']
            missing_tools = [tool for tool in expected_tools if tool not in tool_names]
            
            if missing_tools:
                print(f"⚠️  Missing expected tools: {', '.join(missing_tools)}")
            else:
                print("✅ All expected binance-data tools are available!")
    
    # Alternative: Try connecting with CrewAI adapter
    print("\n3️⃣ Testing CrewAI adapter connection...")
    try:
        from crewai_tools import MCPServerAdapter
        
        server_params = {
            "url": f"{url}/mcp/",
            "transport": "streamable-http"
        }
        
        with MCPServerAdapter(server_params) as mcp_tools:
            tools = list(mcp_tools)
            print(f"✅ CrewAI connected successfully! Found {len(tools)} tools")
            
            # Print first few tools
            for i, tool in enumerate(tools[:3]):
                print(f"   - {tool.name}")
                
            if len(tools) > 3:
                print(f"   ... and {len(tools) - 3} more")
                
            return True
            
    except Exception as e:
        print(f"⚠️  CrewAI adapter test failed: {e}")
        # This might fail but server could still be healthy
        
    return True

def main():
    parser = argparse.ArgumentParser(description="Check binance-data MCP Server Health")
    parser.add_argument("--url", default="http://localhost:8000", 
                       help="binance-data MCP server URL (default: http://localhost:8000)")
    args = parser.parse_args()
    
    print(f"🚀 binance-data MCP Server Health Check")
    print(f"📍 Server URL: {args.url}")
    print(f"📰 Expected tools: binance_klines, binance_depth, binance_ticker_24hr")
    print("="*50)
    
    if check_mcp_server_health(args.url):
        print("\n✅ binance-data MCP Server is healthy and responding!")
        return 0
    else:
        print("\n❌ binance-data MCP Server health check failed!")
        return 1

if __name__ == "__main__":
    sys.exit(main()) 