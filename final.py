#!/usr/bin/env python3
"""
final.py — Conversational wrapper over Phase_2 + nlp_layer
with context management so follow-up questions reuse the last results.

Files expected in the same folder:
  - Phase_2.py  (your main geo-food pipeline)
  - nlp_layer.py

Example usage (CLI):

  python final.py --lat 17.3850 --lon 78.4867

Then you can chat like:
  You: Nearest biryani under 300
  You: Top 5 places
  You: Best one
  You: Show me details of second place
  You: Nearest one
  You: Is it open now?
  You: What are the opening timings?
  You: Now where can I get desserts near me
"""

import argparse
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

import nlp_layer as nlp
import Phase_2 as geo_core  # your big pipeline file

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")


class GeoFoodSession:
    """
    Holds context across turns:
      - last geo-food results (raw output of find_places)
      - last top places (raw dicts)
      - last presentation-layer cards
      - last user query
      - current "focused" place index for follow-ups
    """

    def __init__(self, lat: Optional[float] = None, lon: Optional[float] = None, top_k: int = 5):
        self.lat = lat
        self.lon = lon
        self.top_k = top_k
        self.reset()

    def reset(self) -> None:
        self.last_geo_data: Optional[Dict[str, Any]] = None
        self.last_raw_top_places: Optional[List[Dict[str, Any]]] = None
        self.last_places_for_layer: Optional[List[Dict[str, Any]]] = None
        self.last_nlp_answer: Optional[Dict[str, Any]] = None
        self.last_query: Optional[str] = None
        self.focus_index: Optional[int] = None  # which place is currently in focus

    # ---------- INTENT DETECTION (NEW SEARCH vs FOLLOW-UP) ----------

    def _is_new_search_intent(self, user_text: str) -> bool:
        """
        Heuristic:
          - If we have no previous context -> new search
          - If text clearly refers to previous list/details -> follow-up
          - If text contains dish/budget -> new search
          - Otherwise -> follow-up
        """
        if self.last_geo_data is None:
            return True

        text = user_text.lower()

        # If user says "top N" (top 3, top 5 places, etc.) it's follow-up
        if re.search(r"\btop\s+\d+", text):
            return False

        # Strong follow-up markers
        followup_markers = [
            "top 3",
            "top three",
            "three places",
            "3 places",
            "top 5",
            "top five",
            "top 1",
            "top one",
            "second place",
            "third place",
            "first place",
            "from the three places",
            "from these",
            "from them",
            "best from the three",
            "best among them",
            "best one",
            "best place",
            "best option",
            "details of",
            "show details",
            "more near",
            "more nearer",
            "nearest one",
            "closest",
            "which is closer",
            "from the last results",
            "is it open now",
            "opening time",
            "opening timings",
            "opening hours",
        ]
        if any(m in text for m in followup_markers):
            return False

        # Dish-ish words: treat as new search
        dish_words = [
            "biryani", "biriyani", "pizza", "burger", "coffee", "tea",
            "dessert", "desserts", "ice cream", "icecream",
            "cake", "pastry", "pasta", "noodles", "shawarma"
        ]
        budget_markers = [" under ", " below ", " less than ", "≤", "<=", " rs", " inr", "₹"]

        if any(d in text for d in dish_words):
            return True
        if any(b in text for b in budget_markers):
            return True

        # Very short generic follow-ups like "best one", "nearest one"
        if len(text.split()) <= 3 and any(w in text for w in ["best", "nearest", "closest"]):
            return False

        # Default: treat as follow-up
        return False

    # ---------- PUBLIC ENTRY POINT ----------

    def handle_message(self, user_text: str) -> str:
        user_text = (user_text or "").strip()
        if not user_text:
            return "Please type a query like 'Nearest biryani under 300'."

        if self._is_new_search_intent(user_text):
            return self._handle_new_search(user_text)
        else:
            if not self.last_geo_data:
                # Fallback: no context yet, so just run a fresh search
                return self._handle_new_search(user_text)
            return self._handle_follow_up(user_text)

    # ---------- NEW SEARCH FLOW (CALLS Phase_2 + nlp_layer) ----------

    def _handle_new_search(self, query: str) -> str:
        try:
            geo_data = geo_core.find_places(
                query,
                lat=self.lat,
                lon=self.lon,
                top_k=self.top_k,
                only_open=False,
            )
        except Exception as e:
            logging.exception("Error in find_places")
            return f"Something went wrong while searching: {e}"

        self.last_geo_data = geo_data
        self.last_query = query

        user_city = (geo_data.get("user_location") or {}).get("city")
        dish = geo_data.get("dish")
        top_places = nlp.pick_top_results(geo_data, top_k=self.top_k)
        self.last_raw_top_places = top_places

        places_for_layer: List[Dict[str, Any]] = []
        for p in top_places:
            compact = nlp.build_place_for_layer(p, user_city, dish)

            # Optional image via Google Custom Search (if configured)
            img_url = nlp.fetch_image_url_for_place(
                name=compact["name"],
                user_city=user_city,
                dish=dish,
            )
            compact["image_url"] = img_url
            places_for_layer.append(compact)

        self.last_places_for_layer = places_for_layer
        nlp_answer = nlp.build_cards_without_llm(query, user_city, dish, places_for_layer)
        self.last_nlp_answer = nlp_answer

        # By default, focus on the top result
        self.focus_index = 0 if places_for_layer else None

        # Human-readable response
        lines: List[str] = []
        lines.append(nlp_answer.get("overall_summary", ""))
        lines.append("")

        for idx, card in enumerate(nlp_answer.get("cards", []), start=1):
            line = f"{idx}. {card['name']} — {card['short_reason']}"
            if card.get("distance_display"):
                line += f" Approx. distance: {card['distance_display']}."
            if card.get("price_est") is not None:
                line += f" {card['price_sentence']}"
            lines.append(line)

        lines.append(
            "\nYou can ask things like:\n"
            "- 'Give me the top 3 places'\n"
            "- 'Top 5 places'\n"
            "- 'Best one'\n"
            "- 'Where can I get best from the three places?'\n"
            "- 'Show details of the second place'\n"
            "- 'Nearest one'\n"
            "- 'Is it open now?'\n"
            "- 'What are the opening timings?'\n"
            "Or ask a new main query like 'Nearest pizza under 200'."
        )

        return "\n".join(lines)

    # ---------- HELPERS FOR FOLLOW-UP ----------

    def _get_card_and_place_by_index(self, idx: int) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
        if not self.last_nlp_answer or not self.last_places_for_layer or not self.last_raw_top_places:
            return None, None
        cards = self.last_nlp_answer.get("cards") or []
        if idx < 0 or idx >= len(cards) or idx >= len(self.last_raw_top_places):
            return None, None
        return cards[idx], self.last_raw_top_places[idx]

    def _set_focus_by_name(self, name: str) -> None:
        if not self.last_raw_top_places:
            return
        name_l = (name or "").lower()
        for i, p in enumerate(self.last_raw_top_places):
            if (p.get("name") or "").lower() == name_l:
                self.focus_index = i
                return

    def _get_focus_index_or_default(self) -> int:
        if self.focus_index is not None and self.last_nlp_answer and self.last_nlp_answer.get("cards"):
            if 0 <= self.focus_index < len(self.last_nlp_answer["cards"]):
                return self.focus_index
        # fallback: top result
        return 0

    def _format_opening_hours(self, place: Dict[str, Any]) -> Optional[str]:
        oh = place.get("opening_hours")
        if not oh:
            return None
        # Possible formats: list, dict, string
        if isinstance(oh, list):
            return "; ".join(str(x) for x in oh)
        if isinstance(oh, dict):
            if "weekday_text" in oh and isinstance(oh["weekday_text"], list):
                return "; ".join(str(x) for x in oh["weekday_text"])
            try:
                return "; ".join(f"{k}: {v}" for k, v in oh.items())
            except Exception:
                return str(oh)
        return str(oh)

    # ---------- FOLLOW-UP HANDLING (NO NEW SEARCH) ----------

    def _handle_follow_up(self, text: str) -> str:
        text_l = text.lower()

        if not self.last_nlp_answer or not (self.last_nlp_answer.get("cards")):
            return "I don't have any previous results yet. Ask something like 'Nearest biryani under 300' first."

        cards = self.last_nlp_answer["cards"]

        # 1) "Top N places" / "Top 3", "Top 5", "Top 1 place"
        m_top = re.search(r"\btop\s+(\d+)", text_l)
        if m_top:
            n = int(m_top.group(1))
            if n < 1:
                n = 1
            if n > len(cards):
                n = len(cards)
            lines = [f"Here are the top {n} place(s) from your last search:"]
            for i in range(n):
                c = cards[i]
                line = f"{i+1}. {c['name']}"
                if c.get("distance_display"):
                    line += f" — approx. {c['distance_display']} away"
                if c.get("price_est") is not None:
                    line += f", around ₹{int(c['price_est'])} per person"
                lines.append(line)
            # do not change focus here; keep current focused place
            return "\n".join(lines)

        # 2) Short "top places" without number (rare) -> treat as top 3
        if "top places" in text_l or "top place" in text_l:
            n = min(3, len(cards))
            lines = [f"Here are the top {n} place(s) from your last search:"]
            for i in range(n):
                c = cards[i]
                line = f"{i+1}. {c['name']}"
                if c.get("distance_display"):
                    line += f" — approx. {c['distance_display']} away"
                if c.get("price_est") is not None:
                    line += f", around ₹{int(c['price_est'])} per person"
                lines.append(line)
            return "\n".join(lines)

        # 3) "Best one / Best place / Best option / best from the three"
        if (
            "best from the three" in text_l
            or "best among them" in text_l
            or "best one" in text_l
            or "best place" in text_l
            or "best option" in text_l
        ):
            best = cards[0]
            self.focus_index = 0  # focus on best
            return (
                f"The best option from your last results is **{best['name']}**.\n"
                f"{best['short_reason']}\n"
                f"{best['price_sentence']}\n"
                f"Link: {best['primary_link'] or 'Not available'}"
            )

        # 4) "Which restaurant is more near to me?" / "nearest one" / "closest"
        if any(k in text_l for k in ["nearest", "closest", "more near", "more nearer", "which is closer"]):
            results = (self.last_geo_data or {}).get("results") or []
            if not results:
                return "I couldn't find distance info in the last results. Try a fresh query."

            nearest_place = None
            for r in results:
                if r.get("distance_m") is None:
                    continue
                if nearest_place is None or r["distance_m"] < nearest_place["distance_m"]:
                    nearest_place = r

            if not nearest_place:
                nearest_card = cards[0]
                self.focus_index = 0
                return (
                    "I couldn't compute exact distances, but "
                    f"**{nearest_card['name']}** is the top-ranked option from the last search."
                )

            dist_disp = nearest_place.get("distance_display") or f"{nearest_place['distance_m']} m"
            price_est = nearest_place.get("price_est")
            price_part = f" Around ₹{int(price_est)} per person." if price_est is not None else ""

            # update focus to this nearest place
            self._set_focus_by_name(nearest_place.get("name") or "")

            return (
                f"The closest place from your last search is **{nearest_place['name']}**, "
                f"about {dist_disp} away.{price_part}"
            )

        # 5) "Show details of the second / third place"
        idx: Optional[int] = None
        if "first place" in text_l or "1st place" in text_l:
            idx = 0
        elif "second place" in text_l or "2nd place" in text_l:
            idx = 1
        elif "third place" in text_l or "3rd place" in text_l:
            idx = 2

        if idx is not None:
            card, place = self._get_card_and_place_by_index(idx)
            if not card:
                return "I don't have that many places in the last results."

            self.focus_index = idx  # focus now on this place

            lines = [f"Details for place #{idx+1}: **{card['name']}**"]
            if card.get("distance_display"):
                lines.append(f"- Distance: {card['distance_display']}")
            if card.get("price_est") is not None:
                lines.append(
                    f"- Price: around ₹{int(card['price_est'])} per person "
                    f"({card['price_sentence']})"
                )
            if card.get("primary_link"):
                lines.append(f"- Link: {card['primary_link']}")
            snips = card.get("evidence_snippets") or []
            if snips:
                lines.append("- Evidence / reviews:")
                for s in snips[:3]:
                    lines.append(f"  • {s}")
            return "\n".join(lines)

        # 6) Opening status: "Is it open now?"
        if "is it open now" in text_l or (text_l.strip() == "is it open now"):
            idx = self._get_focus_index_or_default()
            card, place = self._get_card_and_place_by_index(idx)
            if not card or not place:
                return "I don't have any place in focus. Try asking 'Best one' or 'Nearest one' first."

            name = card["name"]
            is_open = place.get("is_open_now")
            if is_open is None:
                is_open = card.get("is_open_now")

            oh_text = self._format_opening_hours(place)

            if is_open is True:
                msg = f"Yes, **{name}** appears to be open right now."
            elif is_open is False:
                msg = f"No, **{name}** appears to be closed right now."
            else:
                msg = f"I'm not fully sure if **{name}** is open at this exact moment."

            if oh_text:
                msg += f" Their listed opening hours are: {oh_text}."
            return msg

        # 7) Opening timings / hours
        if (
            "opening time" in text_l
            or "opening timings" in text_l
            or "opening hours" in text_l
            or ("what time" in text_l and "open" in text_l)
        ):
            idx = self._get_focus_index_or_default()
            card, place = self._get_card_and_place_by_index(idx)
            if not card or not place:
                return "I don't have any place in focus. Try asking 'Best one' or 'Nearest one' first."

            name = card["name"]
            oh_text = self._format_opening_hours(place)
            if not oh_text:
                return (
                    f"I don't have detailed opening timings for **{name}**. "
                    f"You may want to check their link: {card.get('primary_link') or 'No link available'}"
                )
            return f"The opening hours for **{name}** are: {oh_text}."

        # 8) Generic "details" (no index)
        if "details" in text_l:
            idx = self._get_focus_index_or_default()
            card, place = self._get_card_and_place_by_index(idx)
            if not card:
                return "I don't have any places stored from the last search."

            self.focus_index = idx

            lines = [f"Here are more details about **{card['name']}**:"]
            if card.get("distance_display"):
                lines.append(f"- Distance: {card['distance_display']}")
            if card.get("price_est") is not None:
                lines.append(
                    f"- Price: around ₹{int(card['price_est'])} per person "
                    f"({card['price_sentence']})"
                )
            if card.get("primary_link"):
                lines.append(f"- Link: {card['primary_link']}")
            oh_text = None
            if place:
                oh_text = self._format_opening_hours(place)
            if oh_text:
                lines.append(f"- Opening hours: {oh_text}")
            snips = card.get("evidence_snippets") or []
            if snips:
                lines.append("- Evidence / reviews:")
                for s in snips[:3]:
                    lines.append(f"  • {s}")
            return "\n".join(lines)

        # 9) Fallback: recap the last summary
        return (
            "I'm treating this as a follow-up to your last search, "
            "but I couldn't match any specific pattern.\n\n"
            "Here's a quick recap of your last results:\n\n"
            f"{self.last_nlp_answer.get('overall_summary', '')}"
        )


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Conversational geo-food assistant using Phase_2 + nlp_layer with context"
    )
    ap.add_argument("--lat", type=float, help="Latitude (optional, else Phase_2 will infer via IP)")
    ap.add_argument("--lon", type=float, help="Longitude (optional, else Phase_2 will infer via IP)")
    ap.add_argument("--top-k", type=int, default=5, help="Number of top places to consider")
    args = ap.parse_args()

    session = GeoFoodSession(lat=args.lat, lon=args.lon, top_k=args.top_k)

    print("Geo-food assistant with context.")
    print("Type a query like 'Nearest biryani under 300', or 'exit' to quit.\n")

    while True:
        try:
            user = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            break

        if not user:
            continue
        if user.lower() in {"exit", "quit", "q", "bye"}:
            print("Bye!")
            break

        reply = session.handle_message(user)
        print("\nAssistant:", reply, "\n")


if __name__ == "__main__":
    main()
