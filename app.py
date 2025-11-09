from flask import Flask, request, jsonify, render_template
import mcp_helper
import os
import json
import logging

# =============================================================================
# About this MCP Server
#
# Author: Gareth Cull
# This is a free and open source MCP server that helps support SEO and marketing
# teams with pulling Google Search Console data from the API.
# It was developed in Toronto using LLMs on www.prototypr.ai. If you use this 
# server, please consider linking back to this repo and giving a star on Github.
# Thank you!
#
# License: MIT
# =============================================================================


# Initialize Flask application
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

@app.route('/mcp', methods=['POST'])
def mcp_endpoint():
    """
    Main MCP endpoint to handle JSON-RPC requests
    Implements:
      - initialize
      - tools/list
      - tools/call
      - notifications/* (no-op; MUST NOT return JSON-RPC body)
    """
    request_id = None

    # Robust JSON parse
    try:
        data = request.get_json(force=True)
    except Exception as e:
        app.logger.exception("Parse error in /mcp")
        return jsonify({
            "jsonrpc": "2.0",
            "error": { "code": -32700, "message": f"Parse error: {str(e)}" },
            "id": None
        }), 200

    method = data.get("method")
    params = data.get("params", {})
    request_id = data.get("id")

    app.logger.info("MCP request: method=%s id=%s", method, request_id)

    # AUTH
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return jsonify({
            "jsonrpc": "2.0",
            "error": {
                "code": -32000,
                "message": "Unauthorized: Missing or invalid Authorization header"
            },
            "id": request_id
        }), 401

    token = auth_header.split(' ')[1]
    if token != os.getenv('MCP_TOKEN'):
        return jsonify({
            "jsonrpc": "2.0",
            "error": {
                "code": -32000,
                "message": "Unauthorized: Invalid MCP Auth token"
            },
            "id": request_id
        }), 401

    # Handle JSON-RPC notifications: id is None. MUST NOT send a JSON-RPC response body.
    if request_id is None:
        # Known MCP notification after initialize
        if method == "notifications/initialized" or (isinstance(method, str) and method.startswith("notifications/")):
            app.logger.info("Handled notification: %s (no response body)", method)
            return ("", 204)  # No Content
        # If it's a notification but not recognized, still do not respond with a JSON-RPC body.
        app.logger.info("Unknown notification: %s (no response body)", method)
        return ("", 204)

    try:
        # Delegate to the MCP helper for normal request-response methods
        result = mcp_helper.handle_request(method, params)

        # Optional: log previews for debugging
        if method in ("tools/list", "tools/call"):
            try:
                preview = json.dumps(result, ensure_ascii=False)[:300]
            except Exception:
                preview = str(result)[:300]
            app.logger.info("%s result preview: %s", method, preview)

        return jsonify({
            "jsonrpc": "2.0",
            "result": result,
            "id": request_id
        }), 200

    except Exception as e:
        app.logger.exception("Unhandled error in /mcp for method=%s id=%s", method, request_id)
        # For tool execution failures, return tool-level MCP result to keep client happy
        if method == "tools/call":
            return jsonify({
                "jsonrpc": "2.0",
                "result": {
                    "isError": True,
                    "content": [
                        {"type": "text", "text": f"Internal tool error: {str(e)}"}
                    ]
                },
                "id": request_id
            }), 200

        # Protocol-level fallback
        return jsonify({
            "jsonrpc": "2.0",
            "error": { "code": -32603, "message": f"Internal error: {str(e)}" },
            "id": request_id
        }), 200

if __name__ == "__main__":
    # Run Flask development server
    app.run()