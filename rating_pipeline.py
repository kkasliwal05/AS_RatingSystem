# rating_pipeline.py / Phase1.py

import socket
import requests
import re
import math
from typing import List, Dict, Any, Optional, Tuple
from bs4 import BeautifulSoup
import logging
import json

# ================== CONFIG ==================

FOURSQUARE_API_KEY = "fsq3ZW+ma0ksomWlYkZYUBMMs7jN3rgr1ZZ0k9DmyU1aL8U="  # your key
GOOGLE_PLACES_API_KEY = "AIzaSyBFoL8jAGilROTcdLAXgYInHoYaRZXw3Hg"         # your key

# scoring weights
W_PREF = 0.4
W_DIST = 0.2
W_RATING = 0.3
W_TIME = 0.1

# expanded search triggers
MIN_RESULTS_BEFORE_EXPAND = 5
MIN_STRONG_MATCHES_BEFORE_EXPAND = 2

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

# ================== OPTIONAL SUMMARIZER ==================
try:
    from transformers import pipeline
    SUMMARIZER = pipeline("summarization", model="sshleifer/distilbart-cnn-12-6")
    HAS_SUMMARIZER = True
except Exception:
    SUMMARIZER = None
    HAS_SUMMARIZER = False

# =========================================================
# INTERNET + IP GEO
# =========================================================

def is_connected(host: str = "8.8.8.8", port: int = 53, timeout: int = 3) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


def get_geo_ip(api: str = "http://ip-api.com/json/") -> Optional[Dict[str, Any]]:
    try:
        r = requests.get(api, timeout=6)
        r.raise_for_status()
        data = r.json()
        if data.get("status") == "success":
            return data
    except Exception:
        pass
    return None

# =========================================================
# QUERY PARSING
# =========================================================

def parse_query(query: str) -> Dict[str, Any]:
    q = query.lower()

    wants_black = "black coffee" in q
    wants_wifi = any(w in q for w in ["wifi", "wi-fi", "wi fi", "internet"])
    wants_quiet = any(w in q for w in ["quiet", "study", "work", "calm", "silent", "peaceful"])
    wants_open_now = any(w in q for w in ["open now", "right now", "currently open"])

    dish_term = None
    m = re.search(r"for\s+([a-zA-Z ]+?)(?:\s+with|\s+near|\s+in|\s+at|\s+within|$)", q)
    if m:
        dish_term = m.group(1).strip()

    max_distance_m = None
    m = re.search(r"(\d+)\s*(m|meter|meters|km|kms?|kilometer|kilometre)", q)
    if m:
        val = float(m.group(1))
        unit = m.group(2)
        if unit.startswith("m"):
            max_distance_m = val
        else:
            max_distance_m = val * 1000.0

    return {
        "wants_black": wants_black,
        "wants_wifi": wants_wifi,
        "wants_quiet": wants_quiet,
        "wants_open_now": wants_open_now,
        "dish_term": dish_term,
        "max_distance_m": max_distance_m,
    }


DISH_SYNONYMS = {
    "black coffee": ["americano", "espresso", "long black", "filter coffee"],
}

BLACK_KEYWORDS = ["black coffee", "americano", "espresso", "long black", "filter coffee"]
WIFI_KEYWORDS = ["wifi", "wi-fi", "wi fi", "internet", "free wifi"]

FOOD_KEYWORDS = [
    "coffee", "espresso", "latte", "mocha", "cappuccino",
    "biryani", "pizza", "burger", "sandwich", "pasta",
    "fries", "dessert", "cake", "paneer", "thali", "tandoori"
]

CURRENCY_PATTERNS = [
    r"₹\s?\d+",
    r"\d+\s?rs",
    r"rs\.?\s?\d+",
    r"₹\d+",
    r"\$\s?\d+",
]

# =========================================================
# OSM VIA OVERPASS
# =========================================================

def query_osm_places(lat: float, lon: float, radius_m: int = 3000) -> List[Dict[str, Any]]:
    q = f"""
    [out:json][timeout:25];
    (
      node["amenity"="cafe"](around:{radius_m},{lat},{lon});
      way["amenity"="cafe"](around:{radius_m},{lat},{lon});
      node["amenity"="restaurant"](around:{radius_m},{lat},{lon});
      way["amenity"="restaurant"](around:{radius_m},{lat},{lon});
      node["amenity"="fast_food"](around:{radius_m},{lat},{lon});
      way["amenity"="fast_food"](around:{radius_m},{lat},{lon});
      node["shop"="coffee"](around:{radius_m},{lat},{lon});
      way["shop"="coffee"](around:{radius_m},{lat},{lon});
    );
    out center;
    """
    try:
        r = requests.post("https://overpass-api.de/api/interpreter",
                          data={"data": q}, timeout=40)
        r.raise_for_status()
        data = r.json()
        results: List[Dict[str, Any]] = []
        for el in data.get("elements", []):
            lat_ = el.get("lat") or (el.get("center") or {}).get("lat")
            lon_ = el.get("lon") or (el.get("center") or {}).get("lon")
            results.append({
                "id": el.get("id"),
                "type": el.get("type"),
                "lat": lat_,
                "lon": lon_,
                "tags": el.get("tags", {}),
                "source": "osm"
            })
        return results
    except Exception as e:
        logging.warning("OSM / Overpass failed: %s", e)
        return []

# =========================================================
# FOURSQUARE SEARCH + DETAILS
# =========================================================

def query_foursquare_places(lat: float, lon: float, query: str,
                            radius_m: int = 3000, limit: int = 15) -> List[Dict[str, Any]]:
    if not FOURSQUARE_API_KEY:
        return []
    url = "https://api.foursquare.com/v3/places/search"
    headers = {"Authorization": FOURSQUARE_API_KEY, "Accept": "application/json"}
    params = {
        "ll": f"{lat},{lon}",
        "query": query or "coffee",
        "radius": radius_m,
        "limit": limit,
        "sort": "DISTANCE"
    }
    try:
        r = requests.get(url, headers=headers, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        out: List[Dict[str, Any]] = []
        for it in data.get("results", []):
            ge = it.get("geocodes", {}).get("main", {})
            lat_ = ge.get("latitude")
            lon_ = ge.get("longitude")
            if lat_ is None or lon_ is None:
                continue
            out.append({
                "id": it.get("fsq_id"),
                "type": "foursquare_place",
                "lat": lat_,
                "lon": lon_,
                "tags": {
                    "fsq_id": it.get("fsq_id"),
                    "rating": it.get("rating"),
                    "price": it.get("price"),
                    "categories": [c.get("name") for c in it.get("categories", [])]
                },
                "website": it.get("website"),
                "name": it.get("name"),
                "source": "foursquare"
            })
        return out
    except Exception as e:
        logging.warning("Foursquare search failed: %s", e)
        return []


def get_foursquare_details(fsq_id: str) -> Dict[str, Any]:
    if not fsq_id or not FOURSQUARE_API_KEY:
        return {}
    url = f"https://api.foursquare.com/v3/places/{fsq_id}"
    headers = {"Authorization": FOURSQUARE_API_KEY, "Accept": "application/json"}
    params = {"fields": "rating,price,hours,website,tel"}
    try:
        r = requests.get(url, headers=headers, params=params, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logging.warning("Foursquare details failed: %s", e)
        return {}


def get_foursquare_reviews(fsq_id: str, limit: int = 5) -> List[str]:
    if not fsq_id or not FOURSQUARE_API_KEY:
        return []
    url = f"https://api.foursquare.com/v3/places/{fsq_id}/tips"
    headers = {"Authorization": FOURSQUARE_API_KEY, "Accept": "application/json"}
    params = {"limit": limit, "sort": "POPULAR"}
    try:
        r = requests.get(url, headers=headers, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        return [t.get("text") for t in data.get("tips", []) if t.get("text")]
    except Exception as e:
        logging.warning("Foursquare tips failed: %s", e)
        return []


def fsq_is_open_now(hours: Dict[str, Any]) -> Optional[bool]:
    if not hours:
        return None
    if "is_open" in hours:
        return bool(hours.get("is_open"))
    return None

# =========================================================
# GOOGLE PLACES (NEARBY + DETAILS)
# =========================================================

def query_google_places(lat: float, lon: float, keyword: str,
                        radius_m: int = 3000, limit: int = 20) -> List[Dict[str, Any]]:
    if not GOOGLE_PLACES_API_KEY:
        return []
    url = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
    params = {
        "location": f"{lat},{lon}",
        "radius": radius_m,
        "keyword": keyword or "coffee",
        "type": "restaurant",
        "key": GOOGLE_PLACES_API_KEY
    }
    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        out: List[Dict[str, Any]] = []
        for it in data.get("results", []):
            geo = it.get("geometry", {}).get("location", {})
            lat_ = geo.get("lat")
            lon_ = geo.get("lng")
            if lat_ is None or lon_ is None:
                continue
            out.append({
                "id": it.get("place_id"),
                "type": "google_place",
                "lat": lat_,
                "lon": lon_,
                "tags": {
                    "google_place_id": it.get("place_id"),
                    "rating": it.get("rating"),
                    "user_ratings_total": it.get("user_ratings_total"),
                    "price_level": it.get("price_level"),
                },
                "website": None,
                "name": it.get("name"),
                "source": "google_places"
            })
        return out
    except Exception as e:
        logging.warning("Google Places nearby failed: %s", e)
        return []


def get_google_place_details(place_id: str) -> Dict[str, Any]:
    if not GOOGLE_PLACES_API_KEY or not place_id:
        return {}
    url = "https://maps.googleapis.com/maps/api/place/details/json"
    params = {
        "place_id": place_id,
        "fields": (
            "name,website,formatted_phone_number,opening_hours,"
            "rating,user_ratings_total,url,reviews"
        ),
        "key": GOOGLE_PLACES_API_KEY
    }
    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        return data.get("result", {})
    except Exception as e:
        logging.warning("Google Place details failed: %s", e)
        return {}


def google_is_open_now(details: Dict[str, Any]) -> Optional[bool]:
    opening = details.get("opening_hours", {})
    if "open_now" in opening:
        return bool(opening.get("open_now"))
    return None

# =========================================================
# HTML FETCH + MENU / REVIEWS
# =========================================================

def fetch_page_html(url: Optional[str], timeout: int = 12) -> str:
    if not url:
        return ""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Rating-System-Bot)"}
        r = requests.get(url, timeout=timeout, headers=headers)
        r.raise_for_status()
        return r.text
    except Exception:
        return ""


def looks_like_food_line(text: str) -> bool:
    low = text.lower()
    if len(low) < 3 or len(low) > 160:
        return False

    for pat in CURRENCY_PATTERNS:
        if re.search(pat, low):
            return True

    if any(w in low for w in FOOD_KEYWORDS):
        return True

    return False


def extract_menu_and_reviews_from_html(html: str) -> Tuple[List[str], str, List[str]]:
    """
    Returns: (menu_items, full_text, html_reviews_guess)
    """
    if not html:
        return [], "", []

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()

    full_text = soup.get_text(" ", strip=True) or ""

    menu_items: List[str] = []
    html_reviews: List[str] = []

    for tag in soup.find_all(["li", "p", "span", "div"]):
        line = tag.get_text(" ", strip=True)
        if not line:
            continue
        if looks_like_food_line(line):
            menu_items.append(line)

    for tag in soup.find_all(string=re.compile(r"(review|rating|customer|feedback)", re.I)):
        txt = (tag or "").strip()
        if 10 <= len(txt) <= 280:
            html_reviews.append(txt)

    def dedupe(seq: List[str]) -> List[str]:
        seen = set()
        out = []
        for x in seq:
            x_s = x.strip()
            if not x_s:
                continue
            if x_s in seen:
                continue
            seen.add(x_s)
            out.append(x_s)
        return out

    menu_items = dedupe(menu_items)
    html_reviews = dedupe(html_reviews)

    return menu_items, full_text, html_reviews


def summarize_text(text: str) -> str:
    if not text:
        return ""
    if len(text) < 200:
        return text[:200] + ("..." if len(text) > 200 else "")
    if HAS_SUMMARIZER:
        try:
            out = SUMMARIZER(text, max_length=140, min_length=60, do_sample=False)
            return out[0]["summary_text"]
        except Exception:
            return text[:300] + "..."
    return text[:300] + "..."

# =========================================================
# DISTANCE + OSM HOURS
# =========================================================

def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = (math.sin(dphi / 2) ** 2 +
         math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


def osm_open_now_from_tags(tags: Dict[str, Any]) -> Optional[bool]:
    oh = tags.get("opening_hours")
    if not oh:
        return None
    if "24/7" in oh:
        return True
    return None

# =========================================================
# EVIDENCE BUILDER
# =========================================================

def build_evidence(
    source: str,
    source_url: Optional[str],
    website: Optional[str],
    tags: Dict[str, Any],
    menu_items: List[str],
    reviews: List[str],
    matched_constraints: List[str],
    has_google_details: bool
) -> List[Dict[str, Any]]:
    ev: List[Dict[str, Any]] = []
    url = website or source_url

    if menu_items:
        ev.append({
            "type": "menu",
            "url": url,
            "excerpt": "; ".join(menu_items[:3]),
            "confidence": 0.9
        })

    if reviews:
        ev.append({
            "type": "review",
            "url": url,
            "excerpt": reviews[0][:200],
            "confidence": 0.85
        })

    if source == "osm" and ("amenity" in tags or "cuisine" in tags):
        amenity = tags.get("amenity")
        cuisine = tags.get("cuisine")
        if amenity or cuisine:
            ev.append({
                "type": "osm_tags",
                "url": url,
                "excerpt": f"amenity={amenity}, cuisine={cuisine}",
                "confidence": 0.6
            })

    if source == "google_places" and has_google_details:
        ev.append({
            "type": "google_details",
            "url": url,
            "excerpt": "Google Place details (rating / opening hours / phone verified)",
            "confidence": 0.8
        })

    if matched_constraints:
        ev.append({
            "type": "html_match",
            "url": url,
            "excerpt": ", ".join(matched_constraints),
            "confidence": 0.5
        })

    return ev

# =========================================================
# PROCESS PLACES (SCORING, CONSTRAINTS, EVIDENCE)
# =========================================================

def process_places(
    places: List[Dict[str, Any]],
    query: str,
    constraints: Dict[str, Any],
    user_lat: float,
    user_lon: float,
    search_radius_m: int,
    use_synonyms: bool
) -> Tuple[List[Dict[str, Any]], int]:

    results: List[Dict[str, Any]] = []
    strong_match_count = 0

    dish_term = constraints.get("dish_term")
    q_lower = query.lower()

    dish_terms_all: List[str] = []
    if dish_term:
        dt = dish_term.lower()
        dish_terms_all.append(dt)
        if use_synonyms and dt in DISH_SYNONYMS:
            dish_terms_all.extend([x.lower() for x in DISH_SYNONYMS[dt]])

    preferred_radius = constraints.get("max_distance_m") or search_radius_m

    for p in places:
        c_lat = p.get("lat")
        c_lon = p.get("lon")
        if c_lat is None or c_lon is None:
            continue

        tags = p.get("tags", {}) or {}
        source = p.get("source", "unknown")
        name = (
            p.get("name")
            or tags.get("name")
            or tags.get("name:en")
            or tags.get("operator")
            or "Unnamed Place"
        )

        website = p.get("website") or tags.get("website")
        rating = None
        rating_count = None
        phone = None
        is_open_now: Optional[bool] = None

        # ---------- Foursquare enrichment ----------
        fsq_reviews: List[str] = []
        if source == "foursquare":
            fsq_id = tags.get("fsq_id") or p.get("id")
            fsq_det = get_foursquare_details(fsq_id)
            website = fsq_det.get("website") or website
            rating = fsq_det.get("rating", tags.get("rating"))
            phone = fsq_det.get("tel")
            is_open_now = fsq_is_open_now(fsq_det.get("hours", {}))
            fsq_reviews = get_foursquare_reviews(fsq_id)

        # ---------- Google enrichment ----------
        g_details: Dict[str, Any] = {}
        google_reviews: List[str] = []
        has_google_details = False

        if source == "google_places":
            place_id = tags.get("google_place_id") or p.get("id")
            g_details = get_google_place_details(place_id)
            if g_details:
                has_google_details = True
            website = g_details.get("website") or website
            rating = g_details.get("rating", tags.get("rating"))
            rating_count = g_details.get("user_ratings_total", tags.get("user_ratings_total"))
            phone = g_details.get("formatted_phone_number", phone)
            g_open = google_is_open_now(g_details)
            if g_open is not None:
                is_open_now = g_open

            for rv in g_details.get("reviews", []):
                txt = (rv.get("text") or "").strip()
                if len(txt) >= 10:
                    google_reviews.append(txt)

        # ---------- OSM open hours fallback ----------
        if is_open_now is None and source == "osm":
            is_open_now = osm_open_now_from_tags(tags)

        # ---------- derive canonical source URL ----------
        if website:
            source_url = website
        else:
            if source == "osm":
                source_url = f"https://www.openstreetmap.org/{p.get('type')}/{p.get('id')}"
            elif source == "google_places":
                source_url = f"https://www.google.com/maps/place/?q=place_id:{p.get('id')}"
            elif source == "foursquare":
                source_url = f"https://foursquare.com/v/{name.replace(' ', '-')}/{p.get('id')}"
            else:
                source_url = None

        logging.info("Fetching %s (%s)", name, source_url)

        # ---------- MENU SCRAPING ----------
        menu_items: List[str] = []
        html_reviews_guess: List[str] = []
        full_text = ""

        html = ""
        if website:
            html = fetch_page_html(website)
        elif source == "google_places" and g_details.get("url"):
            html = fetch_page_html(g_details.get("url"))

        if html:
            menu_html, full_text, html_reviews_guess = extract_menu_and_reviews_from_html(html)
            menu_items.extend(menu_html)

        # ---------- text + reviews ----------
        all_reviews: List[str] = []
        all_reviews.extend(fsq_reviews)
        all_reviews.extend(google_reviews)
        all_reviews.extend(html_reviews_guess)

        combined_text = (full_text or "") + " " + " ".join(all_reviews)
        combined_text = combined_text.strip()
        t_lower = combined_text.lower()

        # ---------- distance ----------
        distance_km = haversine_km(user_lat, user_lon, c_lat, c_lon)
        distance_m = distance_km * 1000.0

        within_search_radius = distance_m <= search_radius_m
        within_preferred_radius = distance_m <= preferred_radius

        # ---------- scores ----------
        # distance score
        dist_norm = min(distance_m / (2 * search_radius_m), 1.0)
        distance_score = 1.0 - dist_norm

        # rating score
        rating_score = 0.0
        if rating is not None:
            try:
                if rating <= 5:
                    rating_score = float(rating) / 5.0
                else:
                    rating_score = float(rating) / 10.0
            except Exception:
                rating_score = 0.0

        # time score
        if is_open_now is True:
            time_score = 1.0
        elif is_open_now is False:
            time_score = 0.0
        else:
            time_score = 0.5

        # ---------- preference score (FIXED & PRIORITISED) ----------
        matched_constraints: List[str] = []
        # we don't expose matched_constraints_evidence in final JSON, only use internally if needed
        # but can still collect a simple list if you want to extend later
        preference_score = 0.0

        # 1️⃣ Dish match (if user asked some specific dish)
        if dish_terms_all:
            for term in dish_terms_all:
                if term and term in t_lower:
                    matched_constraints.append("dish_match")
                    preference_score += 0.7
                    break

        # 2️⃣ Black coffee
        if constraints.get("wants_black"):
            if any(kw in t_lower for kw in BLACK_KEYWORDS) or "coffee" in (tags.get("cuisine", "") or "").lower():
                matched_constraints.append("black_coffee")
                preference_score += 0.8  # strong

        # 3️⃣ WiFi (highest preference)
        if constraints.get("wants_wifi"):
            wifi_ok = False
            if any(kw in t_lower for kw in WIFI_KEYWORDS):
                wifi_ok = True
            elif tags.get("internet_access") in ("yes", "wifi", "wlan"):
                wifi_ok = True

            if wifi_ok:
                matched_constraints.append("wifi")
                preference_score += 1.0  # strongest

        # 4️⃣ Quiet / work / study
        if constraints.get("wants_quiet"):
            if any(w in t_lower for w in ["quiet", "peaceful", "calm", "study", "work"]):
                matched_constraints.append("quiet")
                preference_score += 0.4

        # 5️⃣ Open now
        if constraints.get("wants_open_now") and is_open_now is True:
            matched_constraints.append("open_now")
            preference_score += 0.6

        # 6️⃣ Within preferred radius
        if within_preferred_radius:
            matched_constraints.append("within_radius")
            preference_score += 0.3

        # 7️⃣ Semantic bonus (light)
        semantic_bonus = sum(0.05 for w in q_lower.split() if w and w in t_lower)
        semantic_bonus = min(semantic_bonus, 0.2)
        preference_score += semantic_bonus

        # ---------- summary + snippet ----------
        snippet = combined_text[:400]
        summary = summarize_text(combined_text)

        # ---------- evidence ----------
        evidence_list = build_evidence(
            source=source,
            source_url=source_url,
            website=website,
            tags=tags,
            menu_items=menu_items,
            reviews=all_reviews,
            matched_constraints=matched_constraints,
            has_google_details=has_google_details
        )

        # ---------- low_evidence ----------
        strong_evidence = [
            e for e in evidence_list
            if e["type"] in ("menu", "review", "google_details") and e["confidence"] >= 0.7
        ]
        low_evidence = (len(strong_evidence) == 0)

        # ---------- final score ----------
        final_score = (
            W_PREF * max(preference_score, 0.0) +
            W_DIST * max(distance_score, 0.0) +
            W_RATING * max(rating_score, 0.0) +
            W_TIME * max(time_score, 0.0)
        )

        # strong match definition
        if within_preferred_radius and any(
            c in matched_constraints for c in ["dish_match", "black_coffee", "wifi", "quiet", "open_now"]
        ):
            strong_match_count += 1

        results.append({
            "name": name,
            "lat": c_lat,
            "lon": c_lon,
            "source": source,
            "source_url": source_url,
            "website": website,
            "phone": phone,
            "tags": tags,
            "rating": rating,
            "rating_count": rating_count,
            "menu_items": menu_items,
            "menu_available": len(menu_items) > 0,
            "reviews": all_reviews,
            "reviews_available": len(all_reviews) > 0,
            "snippet": snippet,
            "summary": summary,
            "distance_km": round(distance_km, 3),
            "distance_m": round(distance_m, 2),
            "within_search_radius": within_search_radius,
            "within_preferred_radius": within_preferred_radius,
            "is_open_now": is_open_now,
            "matched_constraints": matched_constraints,
            "evidence": evidence_list,
            "low_evidence": low_evidence,
            "score_components": {
                "preference_score": round(preference_score, 4),
                "distance_score": round(distance_score, 4),
                "rating_score": round(rating_score, 4),
                "time_score": round(time_score, 4),
            },
            "raw_final_score": round(final_score, 4),
        })

    return results, strong_match_count

# =========================================================
# MAIN ORCHESTRATOR
# =========================================================

def find_places(query: str,
                lat: Optional[float] = None,
                lon: Optional[float] = None,
                radius_m: int = 3000) -> Dict[str, Any]:

    if not is_connected():
        return {"error": "No internet connection"}

    geo = get_geo_ip()
    if lat is None or lon is None:
        if geo:
            lat = geo.get("lat")
            lon = geo.get("lon")
        else:
            return {"error": "No geolocation available"}

    constraints = parse_query(query)
    q_lower = query.lower()

    if any(w in q_lower for w in ["near me", "nearby", "near by me"]) and constraints.get("max_distance_m") is None:
        constraints["max_distance_m"] = radius_m

    dish_for_search = constraints.get("dish_term") or "coffee"

    # ---------- first pass ----------
    osm_p = query_osm_places(lat, lon, radius_m)
    fsq_p = query_foursquare_places(lat, lon, dish_for_search, radius_m)
    g_p = query_google_places(lat, lon, dish_for_search, radius_m)

    all_initial = osm_p + fsq_p + g_p

    results_1, strong_1 = process_places(
        all_initial, query, constraints, lat, lon, radius_m, use_synonyms=False
    )

    expanded_search_used = False
    expanded_info = None
    results_final = list(results_1)

    # ---------- expansion criteria ----------
    if len(results_1) == 0 or strong_1 < MIN_STRONG_MATCHES_BEFORE_EXPAND:
        expanded_search_used = True
        exp_radius = max(radius_m * 2, 5000)

        dish_key = (constraints.get("dish_term") or "coffee").lower()
        if dish_key in DISH_SYNONYMS:
            search_word = DISH_SYNONYMS[dish_key][0]
        else:
            search_word = dish_key

        osm_p2 = query_osm_places(lat, lon, exp_radius)
        fsq_p2 = query_foursquare_places(lat, lon, search_word, exp_radius)
        g_p2 = query_google_places(lat, lon, search_word, exp_radius)

        all_exp = osm_p2 + fsq_p2 + g_p2

        seen = {(r["name"], r["lat"], r["lon"], r["source"]) for r in results_final}
        uniq_exp: List[Dict[str, Any]] = []
        for p in all_exp:
            pname = (
                p.get("name")
                or p.get("tags", {}).get("name")
                or p.get("tags", {}).get("name:en")
                or "Unnamed Place"
            )
            plat = p.get("lat")
            plon = p.get("lon")
            src = p.get("source", "unknown")
            key = (pname, plat, plon, src)
            if key not in seen:
                uniq_exp.append(p)
                seen.add(key)

        results_2, strong_2 = process_places(
            uniq_exp, query, constraints, lat, lon, exp_radius, use_synonyms=True
        )
        results_final.extend(results_2)

        expanded_info = {
            "from_radius_m": radius_m,
            "to_radius_m": exp_radius,
            "reason": "too_few_strong_matches",
            "initial_strong_matches": strong_1,
            "note": "Expanded search because initial strong matches were low."
        }

    # ---------- normalization ----------
    if results_final:
        max_s = max(r["raw_final_score"] for r in results_final)
        for r in results_final:
            if max_s > 0:
                norm = r["raw_final_score"] / max_s
            else:
                norm = 0.0
            r["normalized_score"] = round(norm, 3)
            r["normalized_score_percent"] = round(norm * 100, 1)

        results_final.sort(key=lambda x: (-x["normalized_score"], x["distance_km"]))

    return {
        "query": query,
        "user_location": {"lat": lat, "lon": lon, "search_radius_m": radius_m},
        "expanded_search_used": expanded_search_used,
        "expanded_search": expanded_info,
        "results": results_final,
    }

# =========================================================
# CLI
# =========================================================

if __name__ == "__main__":
    q = input("Enter your query: ").strip()
    lat_in = input("Enter latitude (blank for auto): ").strip()
    lon_in = input("Enter longitude (blank for auto): ").strip()

    lat = float(lat_in) if lat_in else None
    lon = float(lon_in) if lon_in else None

    out = find_places(q, lat, lon, radius_m=3000)
    print(json.dumps(out, indent=2, ensure_ascii=False))
