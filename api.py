"""
LeakOsint API Wrapper
  GET /fetch?key=<KEY>&num=<phone>     → exactly 10 digit (91 auto-added)
  GET /fetch?key=<KEY>&adhar=<number>  → exactly 12 digit (any starting digits)
  GET /fetch?key=<KEY>&email=<email>   → valid email

  Rate Limit: 50 requests per API key per 24 hours
"""
from flask import Flask, request, Response
import requests, json, logging, re, math, os, time

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# === CONFIG ===
API_KEY         = "TU_NHI_MANEGA"
LEAKOSINT_TOKEN = "8393353246:2MBq29zI"
TARGET_URL      = "https://leakosintapi.com/"
SOURCE_NAME     = "@your_father"
REQUEST_TIMEOUT = 30
LIMIT           = 100
# === RATE LIMIT CONFIG ===
MAX_REQUESTS    = 50          # 24 ghante mein max itne searches
WINDOW_SECONDS  = 24 * 3600  # 24 hours in seconds
RATE_LIMIT_DIR  = "/tmp/rate_limits"  # Vercel pe /tmp available hota hai
# ==============

# --- Rate Limit Functions ---

def _get_rate_file(key):
    os.makedirs(RATE_LIMIT_DIR, exist_ok=True)
    safe_key = re.sub(r"[^a-zA-Z0-9_\-]", "_", key)
    return os.path.join(RATE_LIMIT_DIR, f"{safe_key}.json")

def _load_rate_data(key):
    path = _get_rate_file(key)
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"window_start": time.time(), "count": 0}

def _save_rate_data(key, data):
    path = _get_rate_file(key)
    with open(path, "w") as f:
        json.dump(data, f)

def check_rate_limit(key):
    data = _load_rate_data(key)
    now = time.time()
    elapsed = now - data["window_start"]

    # Agar 24 ghante nikal gaye to window reset karo
    if elapsed >= WINDOW_SECONDS:
        data = {"window_start": now, "count": 0}

    remaining = MAX_REQUESTS - data["count"]
    reset_in = int(WINDOW_SECONDS - (now - data["window_start"]))

    if data["count"] >= MAX_REQUESTS:
        return False, 0, reset_in

    data["count"] += 1
    _save_rate_data(key, data)
    return True, remaining - 1, reset_in

def get_rate_status(key):
    data = _load_rate_data(key)
    now = time.time()
    elapsed = now - data["window_start"]
    if elapsed >= WINDOW_SECONDS:
        return MAX_REQUESTS, 0
    remaining = MAX_REQUESTS - data["count"]
    reset_in = int(WINDOW_SECONDS - elapsed)
    return max(remaining, 0), reset_in

def format_reset_time(seconds):
    h = seconds // 3600
    m = (seconds % 3600) // 60
    if h > 0:
        return f"{h} ghante {m} minute mein"
    return f"{m} minute mein"

# --- Validation Functions ---

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
    results = {}
    if "List" not in upstream:
        return results
    for db_name, db_data in upstream["List"].items():
        filtered_data = []
        data_entries = db_data.get("Data", [])
        for entry in data_entries:
            entry_str = str(entry).lower()
            query_str = str(query).lower()
            if query_str in entry_str:
                filtered_data.append(entry)
        if filtered_data:
            results[db_name] = {
                "info": db_data.get("InfoLeak", ""),
                "data": filtered_data,
                "total_found": len(filtered_data),
                "total_in_db": len(data_entries)
            }
    return results

# --- Routes ---

@app.route("/fetch", methods=["GET"])
def fetch():
    key = request.args.get("key", "").strip()
    if not key or key != API_KEY:
        return make_json_response({"ok": False, "error": "Invalid or missing API key."}, 401)

    # === RATE LIMIT CHECK ===
    allowed, remaining, reset_in = check_rate_limit(key)
    if not allowed:
        reset_msg = format_reset_time(reset_in)
        return make_json_response({
            "ok": False,
            "error": f"Rate limit exceed ho gaya. 24 ghante mein sirf {MAX_REQUESTS} searches allowed hain.",
            "limit": MAX_REQUESTS,
            "remaining": 0,
            "reset_in_seconds": reset_in,
            "reset_message": f"Aapki limit {reset_msg} reset hogi."
        }, 429)
    # =======================

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
    logging.info(f"[FETCH] type={search_type} raw='{provided[0]}' normalized='{query}' cost=${cost_est} remaining={remaining}")

    try:
        upstream = call_leakosint(query)
    except Exception as e:
        logging.exception("Upstream failed")
        return make_json_response({"ok": False, "error": f"Upstream failed: {str(e)}"}, 502)

    if "Error code" in upstream:
        return make_json_response({"ok": False, "error": upstream["Error code"]}, 502)

    results = build_results(upstream, search_type, query)
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
        "rate_limit": {
            "limit":            MAX_REQUESTS,
            "remaining":        remaining,
            "reset_in_seconds": reset_in
        },
        "results": results
    })


@app.route("/", methods=["GET"])
def index():
    key = request.args.get("key", "").strip()
    rate_info = {}
    if key and key == API_KEY:
        remaining, reset_in = get_rate_status(key)
        rate_info = {
            "limit":            MAX_REQUESTS,
            "remaining":        remaining,
            "reset_in_seconds": reset_in,
            "window":           "24 hours"
        }
    return make_json_response({
        "service":    "LeakOsint API Wrapper",
        "developer":  SOURCE_NAME,
        "version":    "2.1",
        "features":   "Filtered search results - only shows records matching your query",
        "rate_limit": rate_info if rate_info else f"{MAX_REQUESTS} requests per 24 hours",
        "examples": {
            "phone": f"/fetch?key={API_KEY}&num=9876543210"
        }
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
