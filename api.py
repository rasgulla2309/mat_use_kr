"""
LeakOsint API Wrapper
  GET /fetch?key=<KEY>&num=<phone>     → exactly 10 digit (91 auto-added)
  GET /fetch?key=<KEY>&adhar=<number>  → exactly 12 digit (any starting digits)
  GET /fetch?key=<KEY>&email=<email>   → valid email
"""
from flask import Flask, request, Response
import requests, json, logging, re, math

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# === CONFIG ===
API_KEY         = "TU_NHI_MANEGA"
LEAKOSINT_TOKEN = "8393353246:2MBq29zI"
TARGET_URL      = "https://leakosintapi.com/"
SOURCE_NAME     = "@your_father"
REQUEST_TIMEOUT = 30
LIMIT           = 100
# ==============

def validate_num(raw):
    clean = re.sub(r"[\s\-\.\(\)\+]", "", raw)
    if re.match(r"^[6-9]\d{9}$", clean):
        return "91" + clean, None
    return None, "Format not supported"

def validate_adhar(raw):
    clean = re.sub(r"\D", "", raw)
    if re.match(r"^\d{12}$", clean):
        return clean, None
    return None, "Format not supported"

def validate_email(raw):
    s = raw.strip()
    if re.match(r"^[\w.+\-]+@[\w\-]+\.[a-zA-Z]{2,}$", s):
        return s.lower(), None
    return None, "Format not supported"

def make_json_response(payload, status=200):
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    return Response(body, status=status,
                    mimetype="application/json; charset=utf-8",
                    headers={"X-Source-Developer": SOURCE_NAME})

def estimate_cost():
    return round(0.0002 * (5 + math.sqrt(LIMIT * 1)), 5)

def call_leakosint(query):
    data = {"token": LEAKOSINT_TOKEN, "request": query, "limit": LIMIT, "lang": "en"}
    resp = requests.post(TARGET_URL, json=data, timeout=REQUEST_TIMEOUT)
    return resp.json()

def build_results(upstream, search_type, query):
    """
    Build results but only include data that actually matches the search query
    """
    results = {}
    
    if "List" not in upstream:
        return results
    
    for db_name, db_data in upstream["List"].items():
        filtered_data = []
        
        # Get all data entries for this database
        data_entries = db_data.get("Data", [])
        
        # Filter entries that contain the search query
        for entry in data_entries:
            # Convert entry to string for case-insensitive search
            entry_str = str(entry).lower()
            query_str = str(query).lower()
            
            # Check if query exists in this entry
            if query_str in entry_str:
                filtered_data.append(entry)
        
        # Only add database if it has matching data
        if filtered_data:
            results[db_name] = {
                "info": db_data.get("InfoLeak", ""),
                "data": filtered_data,
                "total_found": len(filtered_data),
                "total_in_db": len(data_entries)
            }
    
    return results

@app.route("/fetch", methods=["GET"])
def fetch():
    key = request.args.get("key", "").strip()
    if not key or key != API_KEY:
        return make_json_response({"ok": False, "error": "Invalid or missing API key."}, 401)

    num   = request.args.get("num",   "").strip()
    adhar = request.args.get("adhar", "").strip()
    email = request.args.get("email", "").strip()

    provided = [p for p in [num, adhar, email] if p]

    if len(provided) == 0:
        return make_json_response({"ok": False, "error": "No search parameter provided. Use num, adhar, or email."}, 400)

    if len(provided) > 1:
        return make_json_response({"ok": False, "error": "Only one search parameter allowed at a time."}, 400)

    if num:
        query, err = validate_num(num)
        search_type = "phone"
    elif adhar:
        query, err = validate_adhar(adhar)
        search_type = "aadhaar"
    else:
        query, err = validate_email(email)
        search_type = "email"

    if err:
        return make_json_response({"ok": False, "error": err}, 400)

    cost_est = estimate_cost()
    logging.info(f"[FETCH] type={search_type} raw='{provided[0]}' normalized='{query}' cost=${cost_est}")

    try:
        upstream = call_leakosint(query)
    except Exception as e:
        logging.exception("Upstream failed")
        return make_json_response({"ok": False, "error": f"Upstream failed: {str(e)}"}, 502)

    if "Error code" in upstream:
        return make_json_response({"ok": False, "error": upstream["Error code"]}, 502)

    # Build filtered results
    results = build_results(upstream, search_type, query)
    
    # Calculate total matches across all databases
    total_matches = sum(db.get("total_found", 0) for db in results.values())

    return make_json_response({
        "ok":                 True,
        "type":               search_type,
        "query_raw":          provided[0],
        "query_normalized":   query,
        "limit_used":         LIMIT,
        "estimated_cost_usd": cost_est,
        "total_databases":    len(results),
        "total_matches":      total_matches,
        "results":            results
    })

@app.route("/", methods=["GET"])
def index():
    return make_json_response({
        "service":   "LeakOsint API Wrapper",
        "developer": SOURCE_NAME,
        "version":   "2.0",
        "features":  "Filtered search results - only shows records matching your query",
        "examples": {
            "phone": f"/fetch?key={API_KEY}&num=9876543210",
            "aadhaar": f"/fetch?key={API_KEY}&adhar=123456789012",
            "email": f"/fetch?key={API_KEY}&email=test@gmail.com"
        }
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
