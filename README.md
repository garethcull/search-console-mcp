# Google Search Console MCP Server

A Model Context Protocol (MCP) server that exposes Google Search Console (GSC) data as tools consumable by an MCP Client such as OpenAI Responses API, Cursor or the prototypr.ai MCP Client. 

This MCP Server was built as a Flask application and is deployable to Google Cloud Run or your own infrastructure.

# MCP Features

This Google Search Console MCP Server features one MCP tool:
search_console_query

This MCP tool helps users request Google Search Console data using natural language.

It is a protected server, which requires the server operator to add an authorization token to gain access to the service. This auth token (MCP_TOKEN) is an environment variable that needs to be set. 

Natural language requests are turned into API request payloads using Google Gemini 2.5 Flash, which is then used to fetch the requested data from the GSC API. 

Response data is then fed back to the requesting user or agent as a string detailing:

- What GSC data is
- How GSC data is used
- The timeframe of the request
- The request object as a set of parameters
- The response data formatted as a table

The structure for this response context was developed using the FACT context engineering framework. 

More information about how I approached context engineering for this project can be found in the following blog post:
https://www.prototypr.ai/blog/context-engineering-for-ai-agents-a-developers-guide

# MCP Architecture

This MCP server contains two files:
1. app.py - main python file which authenticates and delegates requests to mcp_helper.py
2. mcp_helper.py - supporting helper functions to fulfill user requests.

### app.py
Flask app with POST /mcp
Handles JSON-RPC notifications by returning 204 No Content
Delegates to mcp_helper for MCP method logic

### mcp_helper.py
handle_request routes initialize, tools/list, tools/call
handle_tool_call decodes arguments, dispatches to tools, and returns MCP-shaped results
get_search_console_data handles Gemini prompt → GSC API → formatted text

# Endpoints and Protocol
JSON-RPC MCP (preferred by this server)
POST /mcp
Content-Type: application/json
Auth: Authorization: Bearer MCP_TOKEN
Methods
initialize → returns protocolVersion, serverInfo, capabilities
tools/list → returns tools with inputSchema (camelCase)
tools/call → returns result with content array
notifications/initialized → must NOT return a JSON-RPC body; respond 204

# Environment Variables

This MCP server has environment variables that need to be set in order for it to work. They are:

MCP_TOKEN: Shared secret for Authorization header
SEARCH_CONSOLE_KEY: Base64-encoded Google service account JSON key for GSC
GEMINI_API_KEY: API key for Gemini (used to translate natural language to GSC query JSON)

Note: The search console key will need to be encoded as a base64 string. You will need to do this for the mcp server to work.

# Local Setup
Python environment

## Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

## Install dependencies
pip install -r requirements.txt
Environment variables (example)
export MCP_TOKEN="your-shared-token"
export GEMINI_API_KEY="your-gemini-api-key"
export SEARCH_CONSOLE_KEY="your-service-key-as-a-base64-string"

## Run locally
export FLASK_APP=app.py
flask run --host 0.0.0.0 --port 8080

## Quick JSON-RPC Tests
Use Python requests to verify initialize, notifications/initialized, tools/list, and tools/call. Replace the base URL and token.

```python
import requests, json

BASE = "https://<your-cloud-run-host>/mcp"
AUTH = "Bearer <your-mcp-token>"

def rpc(method, params, id_):
    payload = {"jsonrpc":"2.0","id":id_, "method":method, "params":params}
    r = requests.post(BASE, headers={"Authorization": AUTH, "Content-Type":"application/json"}, data=json.dumps(payload))
    print(method, r.status_code)
    print(r.text[:600])
    return r

# 1) initialize
rpc("initialize", {}, "1")

# 2) tools/list
rpc("tools/list", {}, "2")

# 3) tools/call
rpc("tools/call", {
    "name":"search_console_query",
    "arguments":{"query":"Show me the top 10 queries by clicks over the past 30 days."}
}, "3")
```

# OpenAI Responses API Tool Configuration

This MCP tool was initially designed to use the OpenAI Responses API. For more details about OpenAI's Responses API and MCP, please check out this cookbook: 
https://cookbook.openai.com/examples/mcp/mcp_tool_guide

Configure an MCP tool in your Responses API request. Point server_url to your /mcp endpoint and include the Authorization header.

```python
tools = [
  {
    "type": "mcp",
    "server_label": "search-console-mcp",
    "server_url": "https://<your-cloud-run-host>/mcp",
    "headers": { "Authorization": "Bearer <your-mcp-token>" },
    "require_approval": "never"
  }
]
```

# Adding New Tools
1) Register the tool in tools/list (JSON-RPC uses inputSchema, camelCase).


```python
def handle_tools_list():
    return {
        "tools": [
            {
                "name": "search_console_query",
                "description": "",
                "annotations": {"read_only": False},
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Natural language query for GSC"}
                    },
                    "required": ["query"],
                    "additionalProperties": False
                }
            },
            {
                "name": "new_tool_goes_here",
                "description": "describe what this tool does",
                "annotations": {"read_only": False},
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type":"string","description":"a user request"}                         
                    },
                    "required": ["query"],
                    "additionalProperties": False
                }
            }
        ]
    }
```

You will then need to call it using the handle_tool_call function. 


# Security Considerations

Always require Authorization: Bearer MCP_TOKEN on /mcp
Keep tool outputs reasonable in size and fully UTF‑8

# Deploying to Google Cloud Run

I initially built this MCP server to be deployed on Google Cloud Run. 
Google Cloud Run is a serverless environment that can scale and is easy to deploy to. 

I found the following sources extremely helpful for getting this server deployed and running properly in Google Cloud. 

Since Google Cloud Run is a paid service, you'll need to ensure your project is set and billing enabled. 

You will also need to add the Environment Variables to your instance.

Here is a link to an article that helped me deploy this MCP Server to Google Cloud Run: 
https://docs.cloud.google.com/run/docs/quickstarts/build-and-deploy/deploy-python-service


# License
MIT.

# Contributions & Support
Feedback, issues and PRs welcome. Due to bandwidth constraints, I can't offer any timelines for free updates to this codebase. 

If you need help customizing this MCP server, I'm available for paid consulting and freelance projects. Feel free to reach out and connect w/ me on LinkedIn:
https://www.linkedin.com/in/garethcull/

Thanks for checking out this Google Search Console MCP Server! I hope it helps you and your team.

Happy Analyzing!
