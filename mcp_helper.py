from google.oauth2 import service_account
from googleapiclient.discovery import build
import os
import json
import datetime
import requests
from datetime import datetime
import base64 

# =============================================================================
# Variables
# =============================================================================

# Google Cloud service key as base64 string
gsc_base64_key = os.getenv('SEARCH_CONSOLE_KEY')

# Update your GSC domain here
site_url = 'sc-domain:www.yourdomain.ai'

# =============================================================================
# MCP Protocol Request Routing
# =============================================================================

def handle_request(method, params):
    """
    Main request router for MCP (Model Context Protocol) JSON-RPC methods.
    Supported:
      - initialize
      - tools/list
      - tools/call
    Notifications (notifications/*) are handled in app.py (204 No Content).
    """
    if method == "initialize":
        return handle_initialize()
    elif method == "tools/list":
        return handle_tools_list()
    elif method == "tools/call":
        return handle_tool_call(params)
    else:
        # Let app.py wrap unknown methods into a proper JSON-RPC error
        raise ValueError(f"Method not found: {method}")


# =============================================================================
# MCP Protocol Handlers
# =============================================================================

def handle_initialize():
    """
    JSON-RPC initialize response.
    Keep protocolVersion consistent with your current implementation.
    """
    return {
        "protocolVersion": "2024-11-05",
        "serverInfo": {
            "name": "search_console_mcp",
            "version": "0.1.0"
        },
        "capabilities": {
            "tools": {}
        }
    }


def handle_tools_list():
    """
    JSON-RPC tools/list result.
    IMPORTANT: For JSON-RPC MCP, schema field is camelCase: inputSchema
    """
    return {
        "tools": [
            {
                "name": "search_console_query",
                "description": "a tool that helps translate natural language user requests into Google Search Console API requests",
                "annotations": {"read_only": False},
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The full natural language query from the user requesting data from Google Search Console."
                        }
                    },
                    "required": ["query"],
                    "additionalProperties": False
                }
            }
        ]
    }



def handle_tool_call(params):
    tool_name = params.get("name")
    arguments = params.get("arguments", {})

    # Decode string args if needed
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except Exception:
            return {
                "isError": True,
                "content": [{"type": "text", "text": "Invalid arguments: expected object or JSON string."}]
            }

    if tool_name != "search_console_query":
        return {"isError": True, "content": [{"type": "text", "text": f"Tool not found: {tool_name}"}]}

    try:
        result = get_search_console_data(arguments)
    except Exception as e:
        return {"isError": True, "content": [{"type": "text", "text": f"Tool error (search_console_query): {str(e)}"}]}

    # Text-only output to isolate client parsing
    text_value = result.get("api_response", "")
    if not isinstance(text_value, str):
        try:
            text_value = json.dumps(text_value, ensure_ascii=False)
        except Exception:
            text_value = str(text_value)

    return {"content": [{"type": "text", "text": text_value}]}




# =============================================================================
# Search Console Functions
# =============================================================================

def get_search_console_data(arguments):
    """
    Call Gemini API to search through chat summaries using RPG framework
    
    This function sends the query and chat summaries to Gemini API with a system prompt
    using the RPG framework (Role, Problem, Guidance).
    
    Args:
        query (str): The search query        
    
    Returns:
        dict: Search results from Gemini API
    
    Raises:
        Exception: If Gemini API call fails
    """

    # Extract chat summary from arguments
    query = arguments.get('query')

    # Validate required parameter
    if not query:
        raise ValueError("query is required")
    
    # Get Gemini API key from environment variable
    gemini_api_key = os.getenv('GEMINI_API_KEY')
    if not gemini_api_key:
        raise ValueError("GEMINI_API_KEY environment variable is not set")
    
    # Prepare the system prompt using RPG framework
    system_prompt = gsc_system_prompt()
    
    # Prepare the user message with query and chat summaries
    user_message = f"""{query}"""
    
    # Prepare the request payload for Gemini API
    payload = {
        "system_instruction": {
                "parts": [
                    {
                        "text": system_prompt
                    }
                ]
        },
        "contents": [            
            {
                "role": "user",
                "parts": [
                    {
                        "text": f"{user_message}"
                    }
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.1,
            "topK": 40,
            "topP": 0.95,
            "maxOutputTokens": 2048,
        }
    }
    
    # Make the API request to Gemini
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={gemini_api_key}"
    
    try:
        response = requests.post(url, json=payload, timeout=30)
        response.raise_for_status()
        
        result = response.json()
        
        # Extract the generated text from the response
        if 'candidates' in result and len(result['candidates']) > 0:
            
            # The GSC request obj to send to the GSC API
            generated_api_query = result['candidates'][0]['content']['parts'][0]['text']

            # Clean api query to ensure no additional markdown
            clean_api_query = clean_query(generated_api_query)

            # Convert generated_api_query to json
            api_query_obj = json.loads(clean_api_query)

            # Get start and end dates for the user's query
            start_date = api_query_obj['startDate']
            end_date = api_query_obj['endDate']

            # Create GSC service obj
            service = create_gsc_service_obj(gsc_base64_key)

            # Make GSC API Requst and return a response
            api_response = make_gsc_api_request(service, site_url, api_query_obj)

            # format response for LLM or Agent requesting this data
            llm_response = format_search_console_data(api_response, query, start_date, end_date, api_query_obj)

            return {
                "api_response": llm_response,
                "api_query": generated_api_query,
                "user_query": query,                
                "status": "success"
            }
        else:
            return {
                "api_query": "No results generated from Gemini API",
                "query": query,                
                "status": "no_results"
            }
            
    except requests.exceptions.RequestException as e:
        raise Exception(f"Gemini API request failed: {str(e)}")
    except Exception as e:
        raise Exception(f"Error processing Gemini API response: {str(e)}")


def clean_query(generated_api_query):

    """
    Background: This function checks to see if the api query contains any invalid strings such as ```json or ```
    
    """

    search_string = "```json"
    search_string_2 = "```"
    clean_response_once = generated_api_query.replace(search_string,"")
    clean_response_final = generated_api_query.replace(search_string_2,"")

    return clean_response_final


def gsc_system_prompt():

    """
    Background: This function returns the system prompt for generating the appropriate search console api query
    
    """
    
    system_prompt = f"""You are an expert AI assistant specializing in the Google Search Console API. Your sole function is to act as a precise natural language-to-API translator. You receive user prompts in plain English and your only output is a perfectly structured, valid JSON payload for the searchanalytics.query endpoint.

The current time for this request is: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
The current property being analyzed is: https://{site_url.split(":")[1]}

# P (Problem):

Users will provide unstructured, conversational requests for search analytics data. These requests will use relative dates (e.g., "last month"), imprecise terms, and imply complex filtering. Your task is to meticulously parse the user's intent, identify all relevant parameters, and convert their request into a machine-readable JSON object that strictly conforms to the API's requirements.

# G (Guidance):

## Parameter Identification:
Scan the prompt for the following parameters and map them to the corresponding JSON keys.

1.  **Dates**: Convert terms like "yesterday," "last 7 days," "this month," "September 2024" into `YYYY-MM-DD` format for `startDate` and `endDate`.
2.  **Dimensions**: These are the fields the user wants to group the data by.
    - "queries", "keywords" -> "query"
    - "pages", "URLs" -> "page"
    - "dates", "daily" -> "date"
    - "countries" -> "country"
    - "devices" -> "device"
    - "search appearance" -> "searchAppearance"
3.  **Filters**: This is critical. Filters narrow the results. A dimension can be used as a filter without being in the `dimensions` array.
    - **Implicit Filters**: If a user asks for results "in the UK" or "on mobile," these are filters. They should be placed in the `dimensionFilterGroups`. Do NOT add them to the `dimensions` array unless the user explicitly asks to group by them (e.g., "show me clicks by country").
    - **Country Filters**: Use the 3-letter ISO 3166-1 alpha-3 code (e.g., "UK" -> "GBR", "United States" -> "USA").
    - **Device Filters**: Use API constants: "DESKTOP", "MOBILE", "TABLET".
    - **Page Filter Nuance**: When filtering by `page`, be strategic. If the user provides a full URL with "https://", use the `equals` operator. If the user provides only a URL path AND uses the Equal operator (e.g., page equals "/dashboards" or page equals "blog/my-post"), you MUST add the full domain name to the URL (e.g., "https://{site_url.split(":")[1]}/dashboards" or "https://{site_url.split(":")[1]}/blog/my-post").
    - **Operators**:
        - "for the page", "on the URL" -> `dimension: 'page', operator: 'equals'`
        - "containing", "with the word" -> `dimension: 'query', operator: 'contains'`
        - "excluding", "but not" -> `dimension: 'query', operator: 'notContains'`
        - "matches regex", "matches pattern" -> `operator: 'includingRegex'`
        - "doesn't match regex", "excluding pattern" -> `operator: 'excludingRegex'`
        - If no operator is specified for a filter, default to `'equals'`.
4.  **Search Type**: Look for mentions of specific search surfaces.
    - "Google Discover" -> `"type": "discover"`
    - "Google News" -> `"type": "googleNews"`
    - "Image Search" -> `"type": "image"`
    - If unspecified, default to `"web"`.
5.  **Limits & Pagination**:
    - "top 10", "25 results" -> `rowLimit`
    - "starting at row 50" -> `startRow`
6.  **Logical Inference for Date Trends (Critical Rule)**:
    - If the user asks to trend data by `date` (e.g., "show me daily data", "trended over X days"), you MUST ensure the `rowLimit` is at least equal to the number of days in the requested date range.
    - For example, a request for "the last 90 days" trended daily covers 91 data points (inclusive of the start and end dates). Therefore, the `rowLimit` MUST be set to 91 or higher. Do not use the default `rowLimit` in this scenario.

## Default Values:
-   `startDate`, `endDate`: If no date range is specified, default to the last 28 days.
-   `dimensions`: If no dimensions are specified, default to `["query"]`.
-   `rowLimit`: If no limit is specified, default to 25. 
-   `startRow`: If no pagination is mentioned, default to 0.
-   `aggregationType`: Default to `"auto"` unless the user specifies aggregation by "page" or "property".

## Output Format:
Your output must be **only** the JSON object. Do not include any conversational text, explanations, or markdown formatting such as ```json or ```.

# Examples for Guidance:

## Example 1: Simple Prompt
User Prompt:
Show me my top 25 queries from last month

AI Assistant Output:
{{
    "startDate": "2025-09-01",
    "endDate": "2025-09-30",
    "dimensions": ["query"],
    "rowLimit": 25,
    "startRow": 0
}}

## Example 2: Simple Trended Date Prompt 
User Prompt:
show me the avg position of my site trended over the last 90 days by date

AI Assistant Output:
{{
    "startDate": "2025-08-05",
    "endDate": "2025-11-03",
    "dimensions": ["date"],
    "rowLimit": 91,
    "startRow": 0
}}

## Example 3: Prompt with Filtering (Corrected Logic)
User Prompt:
What were my top pages in the UK on mobile for the last 7 days?

AI Assistant Output:
{{
    "startDate": "2025-10-24",
    "endDate": "2025-10-31",
    "dimensions": ["page"],
    "dimensionFilterGroups": [
        {{
            "filters": [
                {{
                    "dimension": "country",
                    "expression": "GBR"
                }},
                {{
                    "dimension": "device",
                    "expression": "MOBILE"
                }}
            ]
        }}
    ],
    "rowLimit": 25
}}

## Example 4: Complex Prompt with Multiple Filters
User Prompt:
I need to see all queries containing 'ai assistant' but not 'free', specifically for the page 'https://{site_url.split(":")[1]}/blog/ai-tools'.

AI Assistant Output:
{{
    "startDate": "2025-10-03",
    "endDate": "2025-10-31",
    "dimensions": ["query"],
    "rowLimit": 100,
    "startRow": 0,
    "dimensionFilterGroups": [
        {{
            "groupType": "and",
            "filters": [
                {{
                    "dimension": "query",
                    "operator": "contains",
                    "expression": "ai assistant"
                }},
                {{
                    "dimension": "query",
                    "operator": "notContains",
                    "expression": "free"
                }},
                {{
                    "dimension": "page",
                    "operator": "equals",
                    "expression": "https://{site_url.split(":")[1]}/blog/ai-tools"
                }}
            ]
        }}
    ]
}}

## Example 5: Prompt with Regex Filtering
User Prompt:
Show me pages that match the regex '/products/.*' but exclude queries matching the regex 'sale|discount'.

AI Assistant Output:
{{
    "startDate": "2025-10-03",
    "endDate": "2025-10-31",
    "rowLimit": 25,
    "dimensions": ["page"],
    "dimensionFilterGroups": [
        {{
            "groupType": "and",
            "filters": [
                {{
                    "dimension": "page",
                    "operator": "includingRegex",
                    "expression": "/products/.*"
                }},
                {{
                    "dimension": "query",
                    "operator": "excludingRegex",
                    "expression": "sale|discount"
                }}
            ]
        }}
    ]
}}

Final note:
The current time for this request is: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
The current property being analyzed is: https://{site_url.split(":")[1]}
"""

    return system_prompt




def credentials_from_base64_env(base64_key, scopes):
    """
    Decode a Base64-encoded JSON service key from an environment variable
    and return Google service account credentials.
    """
    # Get the Base64-encoded string from the environment variable
    encoded_key = gsc_base64_key      
    
    if not encoded_key:
        raise ValueError(f"Environment variable '{encoded_key}' not found or is empty.")
    
    # Decode the Base64 string into JSON
    decoded_bytes = base64.b64decode(encoded_key)
    key_info = json.loads(decoded_bytes.decode('utf-8'))
    
    # Build credentials using the JSON data
    credentials = service_account.Credentials.from_service_account_info(
        key_info,
        scopes=scopes
    )
    
    return credentials


def create_gsc_service_obj(base64_key):
    """Create a connection to the Google Search Console API and return service object.
    
    Args:
        key (string): Google Search Console JSON client secrets path.
    
    Returns:
        service (object): Google Search Console service object.
    """

    base64_key = gsc_base64_key
    
    scope = ['https://www.googleapis.com/auth/webmasters.readonly']
    
    # Load credentials from base 64 string
    credentials = credentials_from_base64_env(base64_key, scope)
    
    # build service object
    service = build(
        'webmasters',
        'v3',
        credentials=credentials
    )
    
    return service


def make_gsc_api_request(service, site_url, payload):
    """Run a query on the Google Search Console API and return a dataframe of results.
    
    Args:
        service (object): Service object from connect()
        site_url (string): URL of Google Search Console property
        payload (dict): API query payload dictionary
    
    Return:
        df (dataframe): Pandas dataframe containing requested data. 
    
    """
    # Make request
    response = service.searchanalytics().query(siteUrl=site_url, body=payload).execute()    
    
    # List for cleaned results
    results = []
    
    for row in response['rows']:    
        data = {}
        
        for i in range(len(payload['dimensions'])):
            data[payload['dimensions'][i]] = row['keys'][i]

        data['clicks'] = row['clicks']
        data['impressions'] = row['impressions']
        data['ctr'] = round(row['ctr'] * 100, 2)
        data['position'] = round(row['position'], 2)        
        results.append(data)    

    return response


def format_search_console_data(data, query, start_date, end_date, api_query_obj):
    """Formats the GSC response in an LLM friendly format to be sent to the requesting agent.
    
    Args:
        data (object): GSC Data
        query (string): the user's natural language query
        start_date (string): the start date of the query in YYYY-MM-DD format
        end_date (string): the end date of the query in YYYY-MM-DD format
        api_query_obj (dict): API query payload dictionary
    
    Return:
        formatted_output (string): The final formatted response for the Agent requesting GSC Data.
    
    """
    # Get the current timestamp for when the query was requested
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Calculate totals and averages
    total_clicks = sum(row["clicks"] for row in data["rows"])
    total_impressions = sum(row["impressions"] for row in data["rows"])
    avg_ctr = (sum(row["ctr"] for row in data["rows"]) / len(data["rows"])) * 100
    avg_position = sum(row["position"] for row in data["rows"]) / len(data["rows"])

    # Build summary section
    summary_section = (
        f"Summary of metrics across selected period:\n"
        f"  - Total Impressions: {total_impressions}\n"
        f"  - Total Clicks: {total_clicks}\n"
        f"  - Average CTR: {avg_ctr:.2f}%\n"
        f"  - Average Rank: {avg_position:.2f}\n"
    )

    # Create the data table section
    table_header = "Date | Clicks | Impressions | CTR (%) | Average Position"
    table_divider = "-" * len(table_header)

    table_rows = []
    for row in data["rows"]:
        date = row["keys"][0]
        clicks = row["clicks"]
        impressions = row["impressions"]
        ctr = round(row["ctr"] * 100, 2)
        position = round(row["position"], 2)
        table_rows.append(f"{date} | {clicks} | {impressions} | {ctr}% | {position}")

    table_body = "\n".join(table_rows)

    # Compose final formatted report
    formatted_output = f"""
### Search Console Data ###

This data set helps businesses understand how they are showing up on Google Search. 

GSC data typically contains information about the following metrics:
- Search Impressions
- Search Clicks
- CTR (Click-Through Rate)
- Average Rank (Search Position)

and can be segemented across the following dimensions:
- Date
- Country
- Page
- Query
- Device

The following query has been requested by the user on {timestamp} for the date range {start_date} to {end_date}:    
{query}

The data presented below has been pulled to help answer the user's question using this API payload object:
{api_query_obj}

Please review this data in detail and finalize the user's request with an analysis of the facts presented below:

{summary_section}

{table_header}
{table_divider}
{table_body}

"""
    return formatted_output



