"""
LeakOsint API Wrapper
Endpoints:
  GET /fetch?key=<KEY>&num=<phone>     → Phone number search (auto 91 prefix)
  GET /fetch?key=<KEY>&adhar=<number>  → Aadhaar search
"""
from flask import Flask, request, Response
import requests, json, logging, re, math

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# === CONFIG ===
API_KEY         = "TU_NHI_MANEGA"          # Apna custom key
LEAKOSINT_TOKEN = "8393353246:2MBq29zI"    # /api command se mila token
TARGET_URL      = "https://leakosintapi.com/"
SOURCE_NAME     = "@your_father"
REQUEST_TIMEOUT = 30
LIMIT           = 100                       # Fixed limit (minimum & enough for exact match)
# ==============

def make_json_response(payload, status=200):
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    return Response(body, status=status, mimetype="application/json; charset=utf-8",
                    headers={"X-Source-Developer": SOURCE_NAME})

def estimate_cost(limit: int) -> float:
    # Single word / exact match → complexity = 1
    return round(0.0002 * (5 + math.sqrt(limit * 1)), 5)

def call_leakosint(query: str) -> dict:
    data = {
        "token":   LEAKOSINT_TOKEN,
        "request": query,
        "limit":   LIMIT,
        "lang":    "en"
    }
    resp = requests.post(TARGET_URL, json=data, timeout=REQUEST_TIMEOUT)
    return resp.json()

def normalize_phone(raw: str) -> str:
    """Remove junk, add 91 prefix if missing."""
    clean = re.sub(r"[\s\-\.\(\)\+]", "", raw)
    if re.match(r"^91[6-9]\d{9}$", clean):
        return clean                   # already has 91
    if re.match(r"^[6-9]\d{9}$", clean):
        return "91" + clean            # add 91
    if re.match(r"^0[6-9]\d{9}$", clean):
        return "91" + clean[1:]        # replace 0 with 91
    return clean                       # return as-is (international etc.)

def normalize_adhar(raw: str) -> str:
    """Keep only digits, must be 12."""
    return re.sub(r"\D", "", raw)

def build_results(upstream: dict) -> dict:
    results = {}
    if "List" in upstream:
        for db_name, db_data in upstream["List"].items():
            results[db_name] = {
                "info": db_data.get("InfoLeak", ""),
                "data": db_data.get("Data", [])
            }
    return results

# ─── Main endpoint ────────────────────────────────────────────────────────────
@app.route("/fetch", methods=["GET"])
def fetch():
    # Auth
    key = request.args.get("key", "").strip()
    if not key or key != API_KEY:
        return make_json_response({"ok": False, "error": "Invalid or missing API key."}, 401)

    num   = request.args.get("num",   "").strip()
    adhar = request.args.get("adhar", "").strip()

    # Must provide exactly one
    if not num and not adhar:
        return make_json_response({
            "ok": False,
            "error": "Provide either ?num=<phone> or ?adhar=<aadhaar>",
            "examples": {
                "phone": "/fetch?key=YOUR_KEY&num=9876543210",
                "adhar": "/fetch?key=YOUR_KEY&adhar=123456789012"
            }
        }, 400)

    if num and adhar:
        return make_json_response({"ok": False, "error": "Use only one: num OR adhar, not both."}, 400)

    # ── Phone ──
    if num:
        query      = normalize_phone(num)
        search_type = "num"

        # Validate after normalization
        if not re.match(r"^\d{10,13}$", query):
            return make_json_response({
                "ok": False,
                "error": f"Invalid phone number: '{num}'. Use 10-digit Indian mobile number."
            }, 400)

    # ── Aadhaar ──
    else:
        query      = normalize_adhar(adhar)
        search_type = "adhar"

        if not re.match(r"^\d{12}$", query):
            return make_json_response({
                "ok": False,
                "error": f"Invalid Aadhaar: '{adhar}'. Must be exactly 12 digits."
            }, 400)

    cost_est = estimate_cost(LIMIT)
    logging.info(f"[FETCH] type={search_type} raw='{num or adhar}' normalized='{query}' est_cost=${cost_est}")

    # Call LeakOsint
    try:
        upstream = call_leakosint(query)
    except Exception as e:
        logging.exception("Upstream failed")
        return make_json_response({"ok": False, "error": f"Upstream failed: {str(e)}"}, 502)

    if "Error code" in upstream:
        return make_json_response({"ok": False, "error": upstream["Error code"]}, 502)

    results = build_results(upstream)

    return make_json_response({
        "ok":                 True,
        "type":               search_type,
        "query_raw":          num or adhar,
        "query_normalized":   query,
        "limit_used":         LIMIT,
        "estimated_cost_usd": cost_est,
        "total_databases":    len(results),
        "results":            results
    })


# ─── Info endpoint ────────────────────────────────────────────────────────────
@app.route("/", methods=["GET"])
def index():
    return make_json_response({
        "service": "LeakOsint API Wrapper",
        "developer": SOURCE_NAME,
        "endpoints": {
            "/fetch": {
                "method": "GET",
                "params": {
                    "key":   "Your API key (required)",
                    "num":   "Phone number — 10 digit, 91 auto-added (use this OR adhar)",
                    "adhar": "Aadhaar number — 12 digit (use this OR num)"
                },
                "examples": {
                    "phone": "/fetch?key=TU_NHI_MANEGA&num=9876543210",
                    "adhar": "/fetch?key=TU_NHI_MANEGA&adhar=123456789012"
                }
            }
        }
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
