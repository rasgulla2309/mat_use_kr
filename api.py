''' ✅ PHONE:
GET /fetch?key=TU_NHI_MANEGA&num=9876543210
→ {"ok":true,"type":"num",...}

✅ AADHAR:
GET /fetch?key=TU_NHI_MANEGA&adhar=123456789012  
→ {"ok":true,"type":"adhar",...}

✅ EMAIL:
GET /fetch?key=TU_NHI_MANEGA&email=test@gmail.com
→ {"ok":true,"type":"email",...}

✅ NOT FOUND:
→ {"ok":true,"message":"not found"}

✅ INVALID:
→ {"ok":false,"error":"Format not supported"}'''

from flask import Flask, request, Response, g
import requests, json, logging, re, math
app = Flask(__name__)

logging.basicConfig(level=logging.INFO)

# === CONFIG ===
API_KEY = "TU_NHI_MANEGA"
LEAKOSINT_TOKEN = "8393353246:2MBq29zI"
TARGET_URL = "https://leakosintapi.com/"
SOURCE_NAME = "@your_father"
REQUEST_TIMEOUT = 30
LIMIT = 100
# ==============

def validate_num(raw):
    clean = re.sub(r"[\s-.$      $+]", "", raw)
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
    if re.match(r"^[\w.+-]+@[\w-]+.[a-zA-Z]{2,}$", s):
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
    """Filter results based on search type - NO CROSS RESULTS"""
    results = {}
    
    if "List" not in upstream:
        return results
        
    query_lower = str(query).lower()
    
    for db_name, db_data in upstream["List"].items():
        filtered_data = []
        
        # Database level filtering (skip irrelevant DBs)
        if search_type == "num" and any(skip in db_name.lower() for skip in ["email", "gmail", "aadhar"]):
            continue
        if search_type == "adhar" and any(skip in db_name.lower() for skip in ["phone", "mobile", "email", "gmail"]):
            continue
        if search_type == "email" and any(skip in db_name.lower() for skip in ["phone", "mobile", "aadhar", "number"]):
            continue
        
        # Record level filtering
        for record in db_data.get("Data", []):
            record_str = str(record).lower()
            
            if search_type == "num":
                if (re.search(r'\b91[6-9]\d{9}\b', record_str) or 
                    re.search(r'\b[6-9]\d{9}\b', record_str) or
                    query_lower in record_str):
                    filtered_data.append(record)
                    
            elif search_type == "adhar":
                if re.search(r'\b\d{12}\b', record_str) and query_lower in record_str:
                    filtered_data.append(record)
                    
            elif search_type == "email":
                if (re.search(r'[\w\.-]+@[\w\.-]+\.\w{2,}', record_str) and 
                    query_lower in record_str):
                    filtered_data.append(record)
        
        if filtered_data:
            results[db_name] = {
                "info": db_data.get("InfoLeak", ""),
                "data": filtered_data,
                "count": len(filtered_data)
            }
    
    return results

@app.before_request
def before_request():
    g.search_type = None
    g.query = None

@app.route("/fetch", methods=["GET"])
def fetch():
    key = request.args.get("key", "").strip()
    if not key or key != API_KEY:
        return make_json_response({"ok": False, "error": "Invalid or missing API key."}, 401)
    
    num = request.args.get("num", "").strip()
    adhar = request.args.get("adhar", "").strip()
    email = request.args.get("email", "").strip()
    
    provided = [p for p in [num, adhar, email] if p]
    if len(provided) == 0:
        return make_json_response({"ok": False, "error": "Provide num OR adhar OR email"}, 400)
    if len(provided) > 1:
        return make_json_response({"ok": False, "error": "Only one parameter at a time"}, 400)
    
    # Validate & normalize
    if num:
        query, err = validate_num(num)
        search_type = "num"
    elif adhar:
        query, err = validate_adhar(adhar)
        search_type = "adhar"
    else:
        query, err = validate_email(email)
        search_type = "email"
    
    if err:
        return make_json_response({"ok": False, "error": err}, 400)
    
    # Store in context
    g.search_type = search_type
    g.query = query
    
    cost_est = estimate_cost()
    logging.info(f"[FETCH] type={search_type} raw='{provided[0]}' normalized='{query}' cost=${cost_est}")
    
    try:
        upstream = call_leakosint(query)
    except Exception as e:
        logging.exception("Upstream failed")
        return make_json_response({"ok": False, "error": "Service unavailable"}, 502)
    
    if "Error code" in upstream:
        return make_json_response({"ok": False, "error": upstream["Error code"]}, 502)
    
    # FILTERED RESULTS
    results = build_results(upstream, search_type, query)
    
    # ✅ NOT FOUND CHECK - SIMPLE RESPONSE
    if not results:
        return make_json_response({
            "ok": True,
            "type": search_type,
            "query_raw": provided[0],
            "query_normalized": query,
            "message": "not found"
        })
    
    return make_json_response({
        "ok": True,
        "type": search_type,
        "query_raw": provided[0],
        "query_normalized": query,
        "limit_used": LIMIT,
        "estimated_cost_usd": cost_est,
        "total_databases": len(results),
        "total_records": sum(db.get("count", 0) for db in results.values()),
        "results": results
    })

@app.route("/", methods=["GET"])
def index():
    return make_json_response({
        "service": "LeakOsint API Wrapper v2.1 ✅",
        "developer": SOURCE_NAME,
        "status": "FIXED - No Cross Results + Not Found",
        "examples": {
            "phone": f"/fetch?key={API_KEY}&num=9876543210",
            "adhar": f"/fetch?key={API_KEY}&adhar=123456789012", 
            "email": f"/fetch?key={API_KEY}&email=test@gmail.com"
        },
        "responses": {
            "found": "Full results with databases",
            "not_found": '{"ok":true,"type":"num","query_raw":"...","query_normalized":"...","message":"not found"}'
        }
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
