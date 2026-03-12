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


def normalize_capitalization(text):
    raw = (text or "").strip()
    if not raw:
        return ""
    # Normalize all-caps/all-lower/mixed input into a consistent display case.
    return " ".join(part.capitalize() for part in raw.lower().split())


def build_in_clause(field, values):
    cleaned = [v.replace("'", "''") for v in values if v]
    if not cleaned:
        return "1 = 0"
    quoted = ", ".join(f"'{v}'" for v in cleaned)
    return f"{field} in ({quoted})"


def asset_manager_search(org, token, entity_name, payload):
    url = f"https://{API_HOST}/asset-manager/api/asset-manager/{entity_name}/search"
    r = requests.post(
        url,
        json=payload,
        headers=manhattan_headers(org, token),
        timeout=45,
        verify=False,
    )
    if not r.ok:
        raise Exception(f"{entity_name} search failed: HTTP {r.status_code}: {r.text[:400]}")
    data = r.json().get("data", []) or []
    return data if isinstance(data, list) else []


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
        "Template": {
            "FacilityId": None,
            "Description": None,
            "FacilityTypeTerminal": None,
            "IsActive": None,
            "FacilityAddress": {"City": None, "State": None},
        },
        "Size": 9999,
    }
    terminals_payload = {
        "Size": 1000,
        "Query": "FacilityTypeTerminal = 'true' AND IsActive = 'true'",
        "Template": payload["Template"],
    }
    try:
        r = requests.post(
            url,
            json=payload,
            headers=manhattan_headers(org, token),
            timeout=45,
            verify=False,
        )
        if not r.ok:
            return jsonify({"success": False, "error": f"HTTP {r.status_code}: {r.text[:400]}"})
        rows = r.json().get("data", []) or []

        rt = requests.post(
            url,
            json=terminals_payload,
            headers=manhattan_headers(org, token),
            timeout=45,
            verify=False,
        )
        if not rt.ok:
            return jsonify({"success": False, "error": f"HTTP {rt.status_code}: {rt.text[:400]}"})
        terminal_rows = rt.json().get("data", []) or []
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
                "Display": f"{fid}: {desc}" if desc else fid,
                "FacilityTypeTerminal": bool(f.get("FacilityTypeTerminal")),
                "IsActive": bool(f.get("IsActive")) if f.get("IsActive") is not None else None,
            }
            facilities_out.append(row)

        for t in terminal_rows:
            tid = (t.get("FacilityId") or "").strip()
            if not tid:
                continue
            tdesc = (t.get("Description") or "").strip()
            taddr = t.get("FacilityAddress") or {}
            tdisplay = f"{tid}: {tdesc}" if tdesc else tid
            terminals_out.append({"TerminalId": tid, "Description": tdesc, "Display": tdisplay})

        facilities_out.sort(key=lambda x: (x.get("FacilityId") or "").lower())
        terminals_out.sort(key=lambda x: (x.get("TerminalId") or "").lower())
        return jsonify({"success": True, "facilities": facilities_out, "terminals": terminals_out})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/product_classes", methods=["POST"])
def product_classes():
    org = request.json.get("org", "").strip()
    token = request.json.get("token", "").strip()
    if not org or not token:
        return jsonify({"success": False, "error": "Missing org/token"})

    url = f"https://{API_HOST}/item-master/api/item-master/productClass/search"
    payload = {
        "Query": "",
        "Size": 1000,
        "Template": {
            "ProductClassId": None,
            "Description": None,
            "Rank": None,
            "Threshold": None,
        },
    }
    try:
        r = requests.post(
            url,
            json=payload,
            headers=manhattan_headers(org, token),
            timeout=45,
            verify=False,
        )
        if not r.ok:
            return jsonify({"success": False, "error": f"HTTP {r.status_code}: {r.text[:400]}"})

        data = r.json().get("data", []) or []
        if isinstance(data, dict):
            rows = data.get("ProductClass", []) or data.get("productClass", [])
            if not rows:
                rows = [v for v in data.values() if isinstance(v, list)]
                rows = rows[0] if rows else []
        else:
            rows = data if isinstance(data, list) else []

        out = []
        for row in rows:
            pcid = (row.get("ProductClassId") or "").strip()
            desc_raw = (row.get("Description") or "").strip()
            display = normalize_capitalization(desc_raw) if desc_raw else pcid
            if not pcid and not display:
                continue
            out.append(
                {
                    "ProductClassId": pcid or display,
                    "Description": desc_raw,
                    "Display": display,
                }
            )

        out.sort(key=lambda x: (x.get("Display") or "").lower())
        return jsonify({"success": True, "productClasses": out})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/terminal_resource_defaults", methods=["POST"])
def terminal_resource_defaults():
    org = request.json.get("org", "").strip()
    token = request.json.get("token", "").strip()
    terminal_id = request.json.get("terminalId", "").strip()

    if not org or not token or not terminal_id:
        return jsonify({"success": False, "error": "Missing org/token/terminalId"})

    try:
        tid_safe = terminal_id.replace("'", "''")

        driver_assets = asset_manager_search(
            org,
            token,
            "driverAsset",
            {
                "Query": f"TerminalId = '{tid_safe}' AND TrackAvailability = 'true'",
                "Size": 1000,
                "Template": {
                    "DriverAssetId": None,
                    "TerminalId": None,
                    "CarrierId": None,
                    "DriverTypeId": None,
                },
            },
        )
        driver_type_ids = sorted({d.get("DriverTypeId") for d in driver_assets if d.get("DriverTypeId")})
        driver_types = []
        if driver_type_ids:
            rows = asset_manager_search(
                org,
                token,
                "driverType",
                {"Query": build_in_clause("DriverTypeId", list(driver_type_ids)), "Size": len(driver_type_ids)},
            )
            for r in rows:
                dtid = (r.get("DriverTypeId") or "").strip()
                desc = (r.get("Description") or "").strip()
                display = normalize_capitalization(desc) if desc else dtid
                if dtid or display:
                    driver_types.append({"Id": dtid or display, "Description": desc, "Display": display})
            driver_types.sort(key=lambda x: (x.get("Display") or "").lower())

        tractor_assets = asset_manager_search(
            org,
            token,
            "tractorAsset",
            {
                "Query": f"TerminalId = '{tid_safe}' AND TrackAvailability = 'true'",
                "Size": 1000,
                "Template": {
                    "TractorAssetId": None,
                    "TerminalId": None,
                    "CarrierId": None,
                    "EquipmentTypeId": None,
                },
            },
        )
        tractor_type_ids = sorted({t.get("EquipmentTypeId") for t in tractor_assets if t.get("EquipmentTypeId")})
        tractor_types = []
        if tractor_type_ids:
            rows = asset_manager_search(
                org,
                token,
                "equipmentType",
                {"Query": build_in_clause("EquipmentTypeId", list(tractor_type_ids)), "Size": len(tractor_type_ids)},
            )
            for r in rows:
                etid = (r.get("EquipmentTypeId") or "").strip()
                desc = (r.get("Description") or "").strip()
                display = normalize_capitalization(desc) if desc else etid
                if etid or display:
                    tractor_types.append({"Id": etid or display, "Description": desc, "Display": display})
            tractor_types.sort(key=lambda x: (x.get("Display") or "").lower())

        trailer_assets = asset_manager_search(
            org,
            token,
            "trailerAsset",
            {
                "Query": f"TerminalId = '{tid_safe}' AND TrackAvailability = 'true'",
                "Size": 1000,
                "Template": {
                    "TrailerAssetId": None,
                    "TerminalId": None,
                    "CarrierId": None,
                    "EquipmentTypeId": None,
                },
            },
        )
        trailer_type_ids = sorted({t.get("EquipmentTypeId") for t in trailer_assets if t.get("EquipmentTypeId")})
        trailer_types = []
        if trailer_type_ids:
            rows = asset_manager_search(
                org,
                token,
                "equipmentType",
                {"Query": build_in_clause("EquipmentTypeId", list(trailer_type_ids)), "Size": len(trailer_type_ids)},
            )
            for r in rows:
                etid = (r.get("EquipmentTypeId") or "").strip()
                desc = (r.get("Description") or "").strip()
                display = normalize_capitalization(desc) if desc else etid
                if etid or display:
                    trailer_types.append({"Id": etid or display, "Description": desc, "Display": display})
            trailer_types.sort(key=lambda x: (x.get("Display") or "").lower())

        return jsonify(
            {
                "success": True,
                "terminalId": terminal_id,
                "driverTypes": driver_types,
                "tractorTypes": tractor_types,
                "trailerTypes": trailer_types,
                "defaultDriverTypeId": driver_types[0]["Id"] if driver_types else None,
                "defaultTractorTypeId": tractor_types[0]["Id"] if tractor_types else None,
                "defaultTrailerTypeId": trailer_types[0]["Id"] if trailer_types else None,
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/submit_request", methods=["POST"])
def submit_request():
    org = request.json.get("org", "").strip()
    token = request.json.get("token", "").strip()
    payload = request.json.get("payload") or {}

    if not org or not token:
        return jsonify({"success": False, "error": "Missing org/token"})

    # REQUIRED ENVIRONMENT CONFIG:
    # This app expects a NextUp counter named TransportationOrderId to exist.
    # If the counter is missing/not configured in an environment, we stop here
    # and return a clear message to the UI.
    nextup_url = (
        f"https://{API_HOST}/routing/api/nextup/getNextupNumbersByCounterType"
        "?counterTypeId=TransportationOrderId&count=1"
    )
    try:
        nr = requests.get(
            nextup_url,
            headers=manhattan_headers(org, token),
            timeout=30,
            verify=False,
        )
        if not nr.ok:
            return jsonify(
                {
                    "success": False,
                    "error": "No NextUp Transportation Order counter is configured in this environment.",
                }
            )
        nbody = nr.json() or {}
        numbers = nbody.get("data", []) or []
        to_number = numbers[0] if numbers else None
        if not to_number:
            return jsonify(
                {
                    "success": False,
                    "error": "No NextUp Transportation Order counter is configured in this environment.",
                }
            )
    except Exception:
        return jsonify(
            {
                "success": False,
                "error": "No NextUp Transportation Order counter is configured in this environment.",
            }
        )

    # Placeholder for subsequent API chain that will use the generated TO number.
    send_ha_message(
        {
            "event": "dispatch_request_submit",
            "org": org,
            "to_number": to_number,
            "payload_keys": list(payload.keys()) if isinstance(payload, dict) else [],
        }
    )
    return jsonify(
        {
            "success": True,
            "message": f"Generated Transportation Order Number: {to_number}",
            "toNumber": to_number,
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
