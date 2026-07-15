#!/usr/bin/env python3
"""No-Website Finder — local server.

Serves the web UI and proxies requests to:
  - Nominatim (geocoding, free)
  - Overpass API (OpenStreetMap business data, free)
  - Google Places API (New) (accurate business data, needs user's API key)

Pure standard library — no pip installs required. Run:  python3 server.py
"""
import json
import re
import time
import urllib.request
import urllib.parse
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PORT = 4173
PUBLIC_DIR = Path(__file__).parent / "docs"
USER_AGENT = "no-website-finder/1.0 (personal lead-research tool)"
KEY_FILE = Path(__file__).parent / "google_api_key.txt"


def server_api_key():
    """Google API key from google_api_key.txt or the GOOGLE_API_KEY env var."""
    import os
    if KEY_FILE.is_file():
        key = KEY_FILE.read_text().strip()
        if key:
            return key
    return os.environ.get("GOOGLE_API_KEY", "").strip()

# ---------------------------------------------------------------- helpers

def http_json(url, *, method="GET", body=None, headers=None, timeout=90):
    """Make an outbound HTTP request and parse the JSON response."""
    data = None
    if body is not None:
        data = body.encode() if isinstance(body, str) else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("User-Agent", USER_AGENT)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode()), None
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode()[:2000]
        except Exception:
            detail = ""
        return None, f"HTTP {e.code} from {urllib.parse.urlparse(url).hostname}: {detail}"
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


# ---------------------------------------------------------------- geocoding

def api_geocode(params):
    q = params.get("query", "").strip()
    if not q:
        return {"error": "Empty query"}
    url = (
        "https://nominatim.openstreetmap.org/search?"
        + urllib.parse.urlencode({
            "format": "jsonv2",
            "limit": 6,
            "addressdetails": 1,
            "countrycodes": "us,ca,gb",
            "q": q,
        })
    )
    data, err = http_json(url)
    if err:
        return {"error": err}
    results = []
    for r in data:
        results.append({
            "name": r.get("display_name"),
            "lat": float(r["lat"]),
            "lng": float(r["lon"]),
            "type": r.get("type"),
            "boundingbox": r.get("boundingbox"),
        })
    return {"results": results}


# ---------------------------------------------------------------- OpenStreetMap / Overpass

OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

def overpass_fetch(q):
    """Run one Overpass query with retries over the mirror list."""
    data = err = None
    for attempt in range(2):                    # two rounds over the mirror list
        for endpoint in OVERPASS_ENDPOINTS:
            data, err = http_json(endpoint, method="POST",
                                  body="data=" + urllib.parse.quote(q),
                                  headers={"Content-Type": "application/x-www-form-urlencoded"},
                                  timeout=70)
            if data is not None:
                return data, None
        time.sleep(4)
    return None, err


def api_osm(params):
    lat = float(params["lat"])
    lng = float(params["lng"])
    radius = min(int(params.get("radius", 2000)), 15000)
    around = f"around:{radius},{lat},{lng}"
    # nodes+ways only (small businesses are practically never relations), and split into
    # two lighter queries — big single queries 504 on the free Overpass servers
    queries = [
        f"""[out:json][timeout:50][maxsize:536870912];
(
  nw({around})["shop"]["name"];
  nw({around})["craft"]["name"];
);
out center tags;""",
        f"""[out:json][timeout:50][maxsize:536870912];
(
  nw({around})["amenity"~"^(restaurant|cafe|fast_food|bar|pub|ice_cream|food_court|nightclub)$"]["name"];
  nw({around})["leisure"~"^(fitness_centre)$"]["name"];
  nw({around})["office"~"^(estate_agent|accountant|lawyer|insurance|architect|travel_agent)$"]["name"];
);
out center tags;""",
    ]
    elements, failures = [], []
    for q in queries:
        data, err = overpass_fetch(q)
        if data is None:
            failures.append(err)
        else:
            elements.extend(data.get("elements", []))
    if len(failures) == len(queries):
        return {"error": failures[0]}

    places = []
    for el in elements:
        tags = el.get("tags", {})
        name = tags.get("name")
        if not name:
            continue
        website = (tags.get("website") or tags.get("contact:website") or "").strip()
        social = (tags.get("contact:facebook") or tags.get("contact:instagram") or "").strip()
        if not website and social:
            website = social
        lat_ = el.get("lat") or (el.get("center") or {}).get("lat")
        lng_ = el.get("lon") or (el.get("center") or {}).get("lon")
        addr_parts = [tags.get("addr:housenumber"), tags.get("addr:street"),
                      tags.get("addr:city"), tags.get("addr:postcode")]
        category = tags.get("shop") or tags.get("craft") or tags.get("amenity") \
            or tags.get("leisure") or tags.get("office") or ""
        places.append({
            "id": f"osm-{el.get('type')}-{el.get('id')}",
            "name": name,
            "category": category.replace("_", " "),
            "address": " ".join(p for p in addr_parts if p),
            "phone": tags.get("phone") or tags.get("contact:phone") or "",
            "website": website,
            "lat": lat_, "lng": lng_,
            "mapsUrl": f"https://www.google.com/maps/search/{urllib.parse.quote(name)}/@{lat_},{lng_},17z" if lat_ else "",
            "source": "osm",
        })
    result = {"places": places}
    if failures:
        result["warning"] = ("Part of the OpenStreetMap data couldn't be fetched (server busy) — "
                             "results may be incomplete. Retry in a minute for full coverage.")
    return result


# ---------------------------------------------------------------- Google Places API (New)

GOOGLE_FIELD_MASK = ",".join([
    "places.id", "places.displayName", "places.formattedAddress",
    "places.websiteUri", "places.nationalPhoneNumber", "places.rating",
    "places.userRatingCount", "places.types", "places.googleMapsUri",
    "places.businessStatus", "places.location",
    "nextPageToken",
])

def api_config(params):
    return {"hasServerKey": bool(server_api_key())}


def api_google(params):
    api_key = params.get("apiKey", "").strip() or server_api_key()
    if not api_key:
        return {"error": "Missing Google API key"}
    text_query = params.get("textQuery", "").strip()
    rect = params.get("rect")  # {south, west, north, east}

    body = {"textQuery": text_query, "pageSize": 20}
    if rect:
        body["locationRestriction"] = {"rectangle": {
            "low": {"latitude": rect["south"], "longitude": rect["west"]},
            "high": {"latitude": rect["north"], "longitude": rect["east"]},
        }}

    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": GOOGLE_FIELD_MASK,
    }

    places, requests_made = [], 0
    page_token = None
    for _ in range(3):  # up to 3 pages = 60 results per query
        if page_token:
            body["pageToken"] = page_token
        data, err = http_json("https://places.googleapis.com/v1/places:searchText",
                              method="POST", body=body, headers=headers)
        requests_made += 1
        if err:
            # a fresh pageToken can briefly return INVALID_ARGUMENT; retry once
            if page_token and "INVALID_ARGUMENT" in err:
                time.sleep(2)
                data, err = http_json("https://places.googleapis.com/v1/places:searchText",
                                      method="POST", body=body, headers=headers)
                requests_made += 1
            if err:
                if places:
                    break
                return {"error": err, "requests": requests_made}
        for p in data.get("places", []):
            loc = p.get("location") or {}
            places.append({
                "id": p.get("id"),
                "name": (p.get("displayName") or {}).get("text", ""),
                "category": (p.get("types") or [""])[0].replace("_", " "),
                "address": p.get("formattedAddress", ""),
                "phone": p.get("nationalPhoneNumber", ""),
                "website": p.get("websiteUri", ""),
                "rating": p.get("rating"),
                "reviews": p.get("userRatingCount"),
                "status": p.get("businessStatus", ""),
                "lat": loc.get("latitude"), "lng": loc.get("longitude"),
                "mapsUrl": p.get("googleMapsUri", ""),
                "source": "google",
            })
        page_token = data.get("nextPageToken")
        if not page_token:
            break
    return {"places": places, "requests": requests_made}


# ---------------------------------------------------------------- server

ROUTES = {
    "/api/geocode": api_geocode,
    "/api/osm": api_osm,
    "/api/google": api_google,
    "/api/config": api_config,
}

MIME = {".html": "text/html", ".js": "text/javascript", ".css": "text/css",
        ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon"}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print("[%s] %s" % (time.strftime("%H:%M:%S"), fmt % args))

    def _send(self, code, content, content_type="application/json"):
        if isinstance(content, (dict, list)):
            content = json.dumps(content).encode()
        elif isinstance(content, str):
            content = content.encode()
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/":
            path = "/index.html"
        # only serve files that resolve inside PUBLIC_DIR
        target = (PUBLIC_DIR / path.lstrip("/")).resolve()
        if PUBLIC_DIR.resolve() in target.parents or target == PUBLIC_DIR.resolve():
            if target.is_file():
                ctype = MIME.get(target.suffix, "application/octet-stream")
                self._send(200, target.read_bytes(), ctype)
                return
        self._send(404, {"error": "not found"})

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        handler = ROUTES.get(path)
        if not handler:
            self._send(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            params = json.loads(self.rfile.read(length) or b"{}")
            result = handler(params)
            self._send(200, result)
        except (BrokenPipeError, ConnectionResetError):
            pass  # client gave up waiting; nothing to send
        except Exception as e:
            try:
                self._send(500, {"error": f"{type(e).__name__}: {e}"})
            except (BrokenPipeError, ConnectionResetError):
                pass


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"No-Website Finder running at http://localhost:{PORT}")
    server.serve_forever()
