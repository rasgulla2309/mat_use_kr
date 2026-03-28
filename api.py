"""
LeakOsint API Wrapper
Endpoint: GET /fetch?key=<API_KEY>&q=<search_query>&limit=100&lang=en
Returns valid JSON only (Content-Type: application/json; charset=utf-8)
"""
from flask import Flask, request, Response
import requests, json, logging

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# === CONFIG ===
API_KEY = "yourkey123"          # Change this to your custom API key
LEAKOSINT_TOKEN = "YOUR_LEAKOSINT_TOKEN_HERE"  # Token from /api command in bot
TARGET_URL = "https://leakosintapi.com/"
SOURCE_NAME = "@YourUsername"   # Your name/username
REQUEST_TIMEOUT = 30
# ==============

def make_json_response(payload_dict, status=200):
    """Return compact JSON response with proper headers."""
    compact = json.dumps(payload_dict, separators=(",", ":"), ensure_ascii=False)
    headers = {"X-Source-Developer": SOURCE_NAME}
    return Response(compact, status=status, mimetype="application/json; charset=utf-8", headers=headers)

def call_leakosint(query, limit=100, lang="en"):
    """Call LeakOsint upstream API and return parsed response."""
    data = {
        "token": LEAKOSINT_TOKEN,
        "request": query,
        "limit": int(limit),
        "lang": lang
    }
    resp = requests.post(TARGET_URL, json=data, timeout=REQUEST_TIMEOUT)
    return resp.json()

@app.route("/fetch", methods=["GET"])
def fetch():
    provided_key = request.args.get("key", "").strip()
    query        = request.args.get("q", "").strip()
    limit        = request.args.get("limit", 100)
    lang         = request.args.get("lang", "en").strip()

    # Validate API key
    if not provided_key or provided_key != API_KEY:
        return make_json_response({"ok": False, "error": "Invalid or missing API key."}, status=401)

    # Validate query
    if not query:
        return make_json_response({"ok": False, "error": "Missing ?q= parameter. Provide a search query."}, status=400)

    # Validate limit
    try:
        limit = int(limit)
        if limit < 100 or limit > 10000:
            raise ValueError
    except ValueError:
        return make_json_response({"ok": False, "error": "limit must be between 100 and 10000."}, status=400)

    # Call LeakOsint
    try:
        upstream = call_leakosint(query, limit, lang)
    except Exception as e:
        logging.exception("Upstream request failed")
        return make_json_response({"ok": False, "error": f"Upstream request failed: {str(e)}"}, status=502)

    # Handle upstream errors
    if "Error code" in upstream:
        return make_json_response({"ok": False, "error": upstream["Error code"]}, status=502)

    # Build clean response
    results = {}
    if "List" in upstream:
        for db_name, db_data in upstream["List"].items():
            results[db_name] = {
                "info": db_data.get("InfoLeak", ""),
                "data": db_data.get("Data", [])
            }

    payload = {
        "ok": True,
        "query": query,
        "total_databases": len(results),
        "results": results,
        "source_developer": SOURCE_NAME
    }
    return make_json_response(payload, status=200)

@app.route("/", methods=["GET"])
def index():
    info = {
        "service": "LeakOsint API Wrapper",
        "developer": SOURCE_NAME,
        "endpoints": {
            "/fetch": {
                "method": "GET",
                "params": {
                    "key":   "Your API key (required)",
                    "q":     "Search query - name, email, phone, etc. (required)",
                    "limit": "Number of results: 100-10000 (default: 100)",
                    "lang":  "Language code (default: en)"
                },
                "example": "/fetch?key=yourkey123&q=test@gmail.com&limit=100&lang=en"
            }
        }
    }
    compact = json.dumps(info, separators=(",", ":"), ensure_ascii=False)
    return Response(compact, status=200, mimetype="application/json; charset=utf-8")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
