"""
LeakOsint API Wrapper - Smart Edition
Endpoint: GET /fetch?key=<API_KEY>&q=<search_query>&type=<search_type>

Search Types (type parameter):
  num    = Phone number (auto-adds 91 prefix if missing)
  adhar  = Aadhaar number (12 digit)
  email  = Email address
  name   = Full name search
  veh    = Vehicle registration number
  ip     = IP address
  auto   = Auto-detect (default)

Credit-saving: limit is set automatically based on type. No need to pass limit in URL.
"""
from flask import Flask, request, Response
import requests, json, logging, re

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# === CONFIG ===
API_KEY           = "TU_NHI_MANEGA"           # Change to your custom API key
LEAKOSINT_TOKEN   = "8393353246:2MBq29zI"     # Token from /api command in bot
TARGET_URL        = "https://leakosintapi.com/"
SOURCE_NAME       = "@your_father"            # Your name/username
REQUEST_TIMEOUT   = 30
# ==============

# ─── Smart Limit per type (credit-saving defaults) ───────────────────────────
# Lower limit = fewer credits used. Raise only if you need more results.
TYPE_LIMITS = {
    "num":   100,   # phone — usually found in top results
    "adhar": 100,   # aadhaar — exact match, no need for high limit
    "email": 100,   # email — exact match
    "name":  200,   # name — needs a bit more range (multiple words = higher complexity)
    "veh":   100,   # vehicle number — exact
    "ip":    100,   # IP address
    "auto":  100,   # fallback
}

# ─── Detect type from query if not provided ──────────────────────────────────
def detect_type(query: str) -> str:
    q = query.strip()

    # Email
    if re.match(r"^[\w.+\-]+@[\w\-]+\.[a-zA-Z]{2,}$", q):
        return "email"

    # Aadhaar: exactly 12 digits (spaces allowed between groups)
    clean = re.sub(r"\s+", "", q)
    if re.match(r"^\d{12}$", clean):
        return "adhar"

    # Phone: 10 digit (maybe with 91 prefix already)
    if re.match(r"^(\+?91)?[6-9]\d{9}$", clean):
        return "num"

    # Vehicle: Indian format like MH12AB1234
    if re.match(r"^[A-Z]{2}\d{1,2}[A-Z]{1,3}\d{1,4}$", q.upper().replace(" ", "")):
        return "veh"

    # IP address
    if re.match(r"^\d{1,3}(\.\d{1,3}){3}$", q):
        return "ip"

    # Default: name search
    return "name"

# ─── Normalize query based on type ───────────────────────────────────────────
def normalize_query(query: str, search_type: str) -> str:
    q = query.strip()

    if search_type == "num":
        # Remove spaces, dashes, dots
        clean = re.sub(r"[\s\-\.\(\)]", "", q)
        # Remove leading +
        clean = clean.lstrip("+")
        # If starts with 91 and total length is 12 → already has prefix
        if re.match(r"^91[6-9]\d{9}$", clean):
            return clean  # already correct
        # If 10 digit Indian mobile number → add 91
        if re.match(r"^[6-9]\d{9}$", clean):
            return "91" + clean
        # If starts with 0 → remove 0 and add 91
        if re.match(r"^0[6-9]\d{9}$", clean):
            return "91" + clean[1:]
        return clean  # return as-is for other formats

    if search_type == "adhar":
        # Keep only digits
        clean = re.sub(r"\D", "", q)
        return clean

    if search_type == "veh":
        # Uppercase, remove spaces
        return q.upper().replace(" ", "")

    # For email, name, ip — return as-is
    return q

# ─── Cost estimator (for info only) ──────────────────────────────────────────
def estimate_cost(query: str, limit: int) -> float:
    import math
    words = [w for w in query.split() if len(w) >= 4 and not w.isdigit()]
    n = len(words)
    if n <= 1:
        complexity = 1
    elif n == 2:
        complexity = 5
    elif n == 3:
        complexity = 16
    else:
        complexity = 40
    return round(0.0002 * (5 + math.sqrt(limit * complexity)), 5)

# ─── Helpers ──────────────────────────────────────────────────────────────────
def make_json_response(payload_dict, status=200):
    compact = json.dumps(payload_dict, separators=(",", ":"), ensure_ascii=False)
    headers = {"X-Source-Developer": SOURCE_NAME}
    return Response(compact, status=status, mimetype="application/json; charset=utf-8", headers=headers)

def call_leakosint(query, limit=100, lang="en"):
    data = {
        "token": LEAKOSINT_TOKEN,
        "request": query,
        "limit": int(limit),
        "lang": lang
    }
    resp = requests.post(TARGET_URL, json=data, timeout=REQUEST_TIMEOUT)
    return resp.json()

# ─── Main endpoint ────────────────────────────────────────────────────────────
@app.route("/fetch", methods=["GET"])
def fetch():
    provided_key  = request.args.get("key",  "").strip()
    raw_query     = request.args.get("q",    "").strip()
    search_type   = request.args.get("type", "auto").strip().lower()
    lang          = request.args.get("lang", "en").strip()

    # Validate API key
    if not provided_key or provided_key != API_KEY:
        return make_json_response({"ok": False, "error": "Invalid or missing API key."}, status=401)

    # Validate query
    if not raw_query:
        return make_json_response({"ok": False, "error": "Missing ?q= parameter."}, status=400)

    # Validate type
    valid_types = list(TYPE_LIMITS.keys())
    if search_type not in valid_types:
        return make_json_response({
            "ok": False,
            "error": f"Invalid type '{search_type}'. Valid types: {', '.join(valid_types)}"
        }, status=400)

    # Auto-detect type if not provided
    if search_type == "auto":
        search_type = detect_type(raw_query)

    # Normalize query (auto-91, clean aadhaar, etc.)
    query = normalize_query(raw_query, search_type)

    # Smart limit (credit saving — no need to pass in URL)
    limit = TYPE_LIMITS[search_type]

    # Estimate cost before calling
    cost_est = estimate_cost(query, limit)

    logging.info(f"[FETCH] type={search_type} raw='{raw_query}' normalized='{query}' limit={limit} est_cost=${cost_est}")

    # Call LeakOsint
    try:
        upstream = call_leakosint(query, limit, lang)
    except Exception as e:
        logging.exception("Upstream request failed")
        return make_json_response({"ok": False, "error": f"Upstream failed: {str(e)}"}, status=502)

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
        "ok":               True,
        "query_raw":        raw_query,
        "query_normalized": query,
        "type_detected":    search_type,
        "limit_used":       limit,
        "estimated_cost_usd": cost_est,
        "total_databases":  len(results),
        "results":          results,
        "source_developer": SOURCE_NAME
    }
    return make_json_response(payload)


# ─── Info / docs endpoint ─────────────────────────────────────────────────────
@app.route("/", methods=["GET"])
def index():
    info = {
        "service": "LeakOsint Smart API Wrapper",
        "developer": SOURCE_NAME,
        "note": "limit is set automatically per type to save credits. No need to pass limit in URL.",
        "smart_limits": TYPE_LIMITS,
        "endpoints": {
            "/fetch": {
                "method": "GET",
                "params": {
                    "key":   "Your API key (required)",
                    "q":     "Search query (required)",
                    "type":  "num | adhar | email | name | veh | ip | auto (default: auto)",
                    "lang":  "Language code (default: en)"
                },
                "examples": {
                    "phone_number":    "/fetch?key=yourkey&q=9876543210&type=num",
                    "phone_auto_91":   "/fetch?key=yourkey&q=9876543210",
                    "aadhaar":         "/fetch?key=yourkey&q=123456789012&type=adhar",
                    "email":           "/fetch?key=yourkey&q=test@gmail.com&type=email",
                    "name":            "/fetch?key=yourkey&q=Rahul Sharma&type=name",
                    "vehicle":         "/fetch?key=yourkey&q=MH12AB1234&type=veh",
                    "ip":              "/fetch?key=yourkey&q=192.168.1.1&type=ip",
                    "auto_detect":     "/fetch?key=yourkey&q=test@gmail.com"
                }
            }
        }
    }
    compact = json.dumps(info, separators=(",", ":"), ensure_ascii=False)
    return Response(compact, status=200, mimetype="application/json; charset=utf-8")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
