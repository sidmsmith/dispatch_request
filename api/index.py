from flask import Flask, request, jsonify, send_from_directory
import os
from datetime import datetime
import requests
from requests.auth import HTTPBasicAuth
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)

APP_NAME = "dispatch_request"
APP_VERSION = "1.0.0"

HA_WEBHOOK_URL = os.getenv("HA_WEBHOOK_URL", "http://sidmsmith.zapto.org:8123/api/webhook/manhattan_app_usage")
HA_HEADERS = {"Content-Type": "application/json"}

AUTH_HOST = os.getenv("MANHATTAN_AUTH_HOST", "salep-auth.sce.manh.com")
API_HOST = os.getenv("MANHATTAN_API_HOST", "salep.sce.manh.com")
USERNAME_BASE = os.getenv("MANHATTAN_USERNAME_BASE", "sdtadmin@")
PASSWORD = os.getenv("MANHATTAN_PASSWORD")
CLIENT_ID = os.getenv("MANHATTAN_CLIENT_ID", "omnicomponent.1.0.0")
CLIENT_SECRET = os.getenv("MANHATTAN_SECRET")


if not PASSWORD or not CLIENT_SECRET:
    raise Exception("Missing MANHATTAN_PASSWORD or MANHATTAN_SECRET environment variables")


def send_ha_message(payload):
    try:
        full_payload = {
            "app_name": APP_NAME,
            "app_version": APP_VERSION,
            "timestamp": datetime.utcnow().isoformat(),
            **payload,
        }
        requests.post(HA_WEBHOOK_URL, json=full_payload, headers=HA_HEADERS, timeout=5)
    except Exception:
        pass


def get_manhattan_token(org):
    url = f"https://{AUTH_HOST}/oauth/token"
    username = f"{USERNAME_BASE}{org.lower()}"
    data = {
        "grant_type": "password",
        "username": username,
        "password": PASSWORD,
    }
    auth = HTTPBasicAuth(CLIENT_ID, CLIENT_SECRET)
    try:
        r = requests.post(
            url,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            auth=auth,
            timeout=30,
            verify=False,
        )
        r.raise_for_status()
        return r.json().get("access_token")
    except Exception:
        return None


def manhattan_headers(org, token):
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "selectedOrganization": org,
        "selectedLocation": f"{org}-DM1",
    }


@app.route("/api/app_opened", methods=["POST"])
def app_opened():
    send_ha_message({"event": "dispatch_request_app_opened"})
    return jsonify({"success": True})


@app.route("/api/auth", methods=["POST"])
def auth():
    org = request.json.get("org", "").strip()
    if not org:
        return jsonify({"success": False, "error": "ORG required"})

    token = get_manhattan_token(org)
    if token:
        send_ha_message({"event": "dispatch_request_auth", "org": org, "success": True})
        return jsonify({"success": True, "token": token})

    send_ha_message({"event": "dispatch_request_auth", "org": org, "success": False})
    return jsonify({"success": False, "error": "Auth failed"})


@app.route("/api/facilities", methods=["POST"])
def facilities():
    org = request.json.get("org", "").strip()
    token = request.json.get("token", "").strip()
    if not org or not token:
        return jsonify({"success": False, "error": "Missing org/token"})

    url = f"https://{API_HOST}/facility/api/facility/facility/search"
    payload = {
        "Query": "FacilityId is not null",
        "Template": {
            "FacilityId": None,
            "Description": None,
            "FacilityTypeTerminal": None,
            "FacilityAddress": {"City": None, "State": None},
        },
        "Size": 3000,
    }
    try:
        r = requests.post(
            url,
            json=payload,
            headers=manhattan_headers(org, token),
            timeout=45,
            verify=False,
        )
        rows = []
        if r.ok:
            rows = r.json().get("data", []) or []
        # Fallback for tenants where the null-check query syntax is unsupported.
        if not rows:
            fallback_payload = {
                "Template": payload["Template"],
                "Size": payload["Size"],
            }
            rf = requests.post(
                url,
                json=fallback_payload,
                headers=manhattan_headers(org, token),
                timeout=45,
                verify=False,
            )
            if not rf.ok:
                return jsonify({"success": False, "error": f"HTTP {rf.status_code}: {rf.text[:400]}"})
            rows = rf.json().get("data", []) or []
        facilities_out = []
        terminals_out = []
        for f in rows:
            fid = (f.get("FacilityId") or "").strip()
            if not fid:
                continue
            desc = (f.get("Description") or "").strip()
            addr = f.get("FacilityAddress") or {}
            city = (addr.get("City") or "").strip()
            state = (addr.get("State") or "").strip()
            row = {
                "FacilityId": fid,
                "Description": desc,
                "City": city,
                "State": state,
                "Display": f"{fid} - {desc}" if desc else fid,
                "FacilityTypeTerminal": bool(f.get("FacilityTypeTerminal")),
            }
            facilities_out.append(row)
            if row["FacilityTypeTerminal"]:
                terminals_out.append({"TerminalId": fid, "Description": desc, "Display": row["Display"]})

        facilities_out.sort(key=lambda x: (x.get("FacilityId") or "").lower())
        terminals_out.sort(key=lambda x: (x.get("TerminalId") or "").lower())
        return jsonify({"success": True, "facilities": facilities_out, "terminals": terminals_out})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/submit_request", methods=["POST"])
def submit_request():
    org = request.json.get("org", "").strip()
    token = request.json.get("token", "").strip()
    payload = request.json.get("payload") or {}

    if not org or not token:
        return jsonify({"success": False, "error": "Missing org/token"})

    # Placeholder endpoint: this is where the API chain will be added later.
    send_ha_message(
        {
            "event": "dispatch_request_submit",
            "org": org,
            "payload_keys": list(payload.keys()) if isinstance(payload, dict) else [],
        }
    )
    return jsonify(
        {
            "success": True,
            "message": "Request captured. API chain not implemented yet.",
            "echo": payload,
        }
    )


@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def static_proxy(path):
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    public_dir = os.path.join(root_dir, "public")
    if path and os.path.exists(os.path.join(public_dir, path)):
        return send_from_directory(public_dir, path)
    return send_from_directory(public_dir, "index.html")


if __name__ == "__main__":
    app.run(debug=True)
