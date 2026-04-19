#!/usr/bin/env python3
"""
nlp_layer.py — Rule-based NLP presentation layer for geo-food pipeline (no Gemini).

Usage:
  1) Run final.py to get JSON results:
       python final.py "Nearest biryani under 300" --lat ... --lon ... --out results.json

  2) Run this script on that JSON:
       python nlp_layer.py results.json --top-k 5

This will:
 - Read geo-food results
 - Fetch 1 image per place via Google Custom Search (image) [optional]
 - Generate:
      * overall natural language summary (rule-based)
      * per-place cards (reasoning, evidence, links, scores, image_url)
 - Print final JSON to stdout (or save with --out)
"""

import os
import json
import argparse
import logging
from typing import Any, Dict, List, Optional

import requests

# ---------- CONFIG ----------

# Google Custom Search (Image) — OPTIONAL
# Set these in your environment if you want images:
#   export GOOGLE_SEARCH_API_KEY="..."
#   export GOOGLE_CSE_ID="..."
GOOGLE_SEARCH_API_KEY = os.getenv("GOOGLE_SEARCH_API_KEY", "")
GOOGLE_CSE_ID = os.getenv("GOOGLE_CSE_ID", "")  # no default hardcoded ID now

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")


# ---------- HELPERS ----------

def load_geo_results(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def pick_top_results(data: Dict[str, Any], top_k: int = 5) -> List[Dict[str, Any]]:
    results = data.get("results", []) or []
    # they are already sorted by final_score in final.py, but just in case
    results = sorted(results, key=lambda x: x.get("score") or 0.0, reverse=True)
    return results[:top_k]


def choose_primary_link(place: Dict[str, Any]) -> Optional[str]:
    # Prefer website, then source_url, then any evidence URL
    website = place.get("website")
    if website:
        return website

    src = place.get("source_url")
    if src:
        return src

    for ev in place.get("evidence_list") or []:
        if isinstance(ev, dict) and ev.get("url"):
            return ev["url"]

    return None


def extract_evidence_snippets(place: Dict[str, Any], max_snippets: int = 3) -> List[str]:
    snippets = []

    # 1) evidence excerpt
    ev = place.get("evidence")
    if isinstance(ev, dict) and ev.get("excerpt"):
        snippets.append(ev["excerpt"])

    # 2) other evidence_list excerpts
    for ev in place.get("evidence_list") or []:
        if len(snippets) >= max_snippets:
            break
        if isinstance(ev, dict) and ev.get("excerpt"):
            text = ev["excerpt"]
            if text not in snippets:
                snippets.append(text)

    # 3) reviews if still short
    for rv in place.get("reviews") or []:
        if len(snippets) >= max_snippets:
            break
        txt = (rv.get("text") if isinstance(rv, dict) else str(rv)) or ""
        if txt and txt not in snippets:
            snippets.append(txt)

    # small cleanup
    out = []
    for s in snippets:
        s = s.strip()
        if not s:
            continue
        if len(s) > 350:
            s = s[:347] + "..."
        out.append(s)
    return out[:max_snippets]


def build_place_for_layer(place: Dict[str, Any],
                          user_city: Optional[str],
                          dish: Optional[str]) -> Dict[str, Any]:
    # Compact representation for the presentation layer
    sc = place.get("score_components", {}) or {}
    dm = place.get("dish_match_metrics", {}) or {}

    return {
        "name": place.get("name"),
        "source": place.get("source"),
        "distance_display": place.get("distance_display"),
        "price_est": place.get("price_est"),
        "score": place.get("score"),
        "is_open_now": place.get("is_open_now"),
        "low_evidence": place.get("low_evidence"),
        "score_components": sc,
        "dish_match_metrics": dm,
        "primary_link": choose_primary_link(place),
        "evidence_snippets": extract_evidence_snippets(place),
        "raw_snippet": place.get("snippet") or "",
        "raw_summary": place.get("summary") or "",
        "user_city": user_city,
        "dish": dish,
        # image_url will be added later
    }


# ---------- IMAGE SEARCH (Google Custom Search) ----------

def fetch_image_url_for_place(name: str,
                              user_city: Optional[str] = None,
                              dish: Optional[str] = None) -> Optional[str]:
    """
    Uses Google Custom Search API (image) to get a thumbnail URL for the place.
    Requires:
      GOOGLE_SEARCH_API_KEY
      GOOGLE_CSE_ID
    If not configured, returns None.
    """
    if not GOOGLE_SEARCH_API_KEY or not GOOGLE_CSE_ID:
        logging.warning("Google image search not configured; skipping image for %s", name)
        return None

    query_parts = [name]
    if user_city:
        query_parts.append(user_city)
    if dish:
        query_parts.append(dish)
    query_parts.append("restaurant")
    query = " ".join([p for p in query_parts if p])

    try:
        url = "https://www.googleapis.com/customsearch/v1"
        params = {
            "key": GOOGLE_SEARCH_API_KEY,
            "cx": GOOGLE_CSE_ID,
            "q": query,
            "searchType": "image",
            "num": 1,
            "safe": "active",
        }
        r = requests.get(url, params=params, timeout=8)
        r.raise_for_status()
        data = r.json()
        items = data.get("items") or []
        if not items:
            logging.info("No image results for query: %s", query)
            return None
        return items[0].get("link")
    except Exception as e:
        logging.warning("Image search failed for %s: %s", name, e)
        return None


# ---------- RULE-BASED "LLM" LAYER (NO GEMINI) ----------

def _price_sentence(price_est: Optional[float]) -> str:
    if price_est is None:
        return "Price information is not available for this place."
    try:
        price_est_val = float(price_est)
    except Exception:
        return "Price information is not available for this place."

    if price_est_val <= 150:
        band = "very budget-friendly"
    elif price_est_val <= 300:
        band = "reasonably priced"
    elif price_est_val <= 500:
        band = "a bit on the higher side"
    else:
        band = "relatively expensive"

    return f"Expected spend per person is around ₹{int(price_est_val)}, which is {band}."


def _short_reason(idx: int,
                  dish: Optional[str],
                  distance_display: Optional[str],
                  is_open_now: Optional[bool]) -> str:
    rank_words = ["top choice", "great option", "also a good pick", "solid choice", "another option"]
    rank_str = rank_words[idx] if idx < len(rank_words) else "good option"

    parts = []
    if dish:
        parts.append(f"{rank_str} for {dish}")
    else:
        parts.append(f"{rank_str} nearby")

    if distance_display:
        parts.append(f"about {distance_display} away")

    if is_open_now is True:
        parts.append("and currently open")
    elif is_open_now is False:
        parts.append("but may be closed right now")

    return ", ".join(parts) + "."


def _why_good_for_user(place: Dict[str, Any]) -> str:
    pieces = []

    name = place.get("name") or "This place"
    score = place.get("score")
    distance_display = place.get("distance_display")
    low_evidence = place.get("low_evidence")
    sc = place.get("score_components", {}) or {}
    dm = place.get("dish_match_metrics", {}) or {}

    # Score
    if isinstance(score, (int, float)):
        pieces.append(f"{name} has an overall score of {score:.1f}, based on our ranking logic.")

    # Distance
    if distance_display:
        pieces.append(f"It is approximately {distance_display} from your location.")

    # Dish match
    dish_match = dm.get("name_score") or dm.get("overall_match")
    if isinstance(dish_match, (int, float)):
        pieces.append(f"It matches your requested dish quite well (dish match score ~{dish_match:.2f}).")

    # Score components summary
    interesting = []
    for k in ["distance_score", "price_score", "review_score", "popularity_score"]:
        v = sc.get(k)
        if isinstance(v, (int, float)):
            nice_name = k.replace("_", " ").replace("score", "").strip().capitalize()
            interesting.append(f"{nice_name}: {v:.2f}")

    if interesting:
        pieces.append("Key signals: " + "; ".join(interesting) + ".")

    # Evidence level
    if low_evidence:
        pieces.append("Note: this recommendation is based on limited evidence, so consider checking recent reviews.")

    # Reviews / snippets
    snippets = place.get("evidence_snippets") or []
    if snippets:
        pieces.append("Here’s what people or sources say: \"" + snippets[0].replace('"', "'") + "\"")

    if not pieces:
        pieces.append("This looks like a reasonable option based on distance, price and basic popularity signals.")

    return " ".join(pieces)


def build_cards_without_llm(query: str,
                            user_city: Optional[str],
                            dish: Optional[str],
                            places_for_layer: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Rule-based generator for:
      - overall_summary
      - cards[]
    (mimics the schema expected from the old Gemini-based flow)
    """

    # Handle no results
    if not places_for_layer:
        return {
            "overall_summary": (
                "I couldn't find any matching places for your query. "
                "Try adjusting your budget, distance, or dish keywords."
            ),
            "cards": []
        }

    # Build cards
    cards = []
    for idx, p in enumerate(places_for_layer):
        name = p.get("name") or f"Place {idx+1}"
        score = p.get("score")
        distance_display = p.get("distance_display")
        price_est = p.get("price_est")
        primary_link = p.get("primary_link")
        image_url = p.get("image_url")
        evidence_snippets = p.get("evidence_snippets") or []

        card = {
            "name": name,
            "short_reason": _short_reason(
                idx=idx,
                dish=dish,
                distance_display=distance_display,
                is_open_now=p.get("is_open_now")
            ),
            "why_good_for_user": _why_good_for_user(p),
            "score": score if isinstance(score, (int, float)) else None,
            "distance_display": distance_display,
            "price_est": price_est,
            "price_sentence": _price_sentence(price_est),
            "primary_link": primary_link,
            "image_url": image_url,
            "evidence_snippets": evidence_snippets,
        }
        cards.append(card)

    # Build overall summary
    top = cards[0]
    others = cards[1:]

    city_part = f"in {user_city}" if user_city else "near you"
    dish_part = dish if dish else "your request"

    lines = []

    # First line: best option
    line1 = f"For {dish_part} {city_part}, the top recommendation is {top['name']}."
    if top.get("distance_display"):
        line1 += f" It is about {top['distance_display']} away."
    if isinstance(top.get("score"), (int, float)):
        line1 += f" It scores around {top['score']:.1f} in our ranking."
    lines.append(line1)

    # Second line: budget info for best
    lines.append(top["price_sentence"])

    # Third line: mention other options
    if others:
        names = [c["name"] for c in others[:3]]
        if len(names) == 1:
            lines.append(f"Another option you can consider is {names[0]}.")
        elif len(names) == 2:
            lines.append(f"Other nearby options include {names[0]} and {names[1]}.")
        else:
            lines.append(f"Other nearby options include {names[0]}, {names[1]} and {names[2]}.")

    overall_summary = " ".join(lines)

    return {
        "overall_summary": overall_summary,
        "cards": cards
    }


# ---------- MAIN ----------

def main():
    ap = argparse.ArgumentParser(
        description="Rule-based NLP layer on top of geo-food pipeline JSON output (no Gemini)"
    )
    ap.add_argument("input_json", help="Path to JSON output from final.py")
    ap.add_argument("--top-k", type=int, default=5, help="Number of top places to consider")
    ap.add_argument("--out", help="Output JSON file for NLP answer (optional)")
    args = ap.parse_args()

    data = load_geo_results(args.input_json)
    top_places = pick_top_results(data, top_k=args.top_k)

    user_city = (data.get("user_location") or {}).get("city")
    dish = data.get("dish")
    query = data.get("query")

    # Build presentation-ready structures + attach images
    places_for_layer: List[Dict[str, Any]] = []
    for p in top_places:
        compact = build_place_for_layer(p, user_city, dish)

        # add image_url (optional)
        img_url = fetch_image_url_for_place(
            name=compact["name"],
            user_city=user_city,
            dish=dish
        )
        compact["image_url"] = img_url
        places_for_layer.append(compact)

    # Generate narrative cards WITHOUT any LLM
    nlp_answer = build_cards_without_llm(query, user_city, dish, places_for_layer)

    # Attach the raw structured input as well
    final_output = {
        "query": query,
        "dish": dish,
        "user_city": user_city,
        "nlp_llm_answer": nlp_answer,  # kept same key for compatibility
        "raw_places_for_llm": places_for_layer,
    }

    out_text = json.dumps(final_output, indent=2, ensure_ascii=False)

    if args.out:
        out_path = args.out if args.out.lower().endswith(".json") else args.out + ".json"
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write(out_text)
        print(f"NLP answer saved to: {out_path}")
    else:
        print(out_text)


if __name__ == "__main__":
    main()
