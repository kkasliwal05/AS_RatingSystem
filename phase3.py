import json
from finalphase import find_places   # ← MAKE SURE this file exists in same folder

# --------------------- IMAGE FETCHER (DUCKDUCKGO + BING HYBRID) ---------------------

import requests

BING_API_KEY = ""   # optional, only for fallback

def fetch_images(query, max_results=3):
    images = []

    # ----------------- DuckDuckGo free image search -----------------
    try:
        r = requests.get(
            "https://duckduckgo.com/",
            params={"q": query},
            headers={"User-Agent": "Mozilla"}
        )
        token = r.text.split("vqd=")[1].split("&")[0]

        img_res = requests.get(
            "https://duckduckgo.com/i.js",
            params={"q": query, "vqd": token},
            headers={"User-Agent": "Mozilla"}
        ).json()

        for img in img_res.get("results", []):
            if len(images) < max_results:
                images.append(img.get("image"))
    except:
        pass

    # ----------------- Fallback Bing Search (uses API key) -----------------
    if len(images) < max_results and BING_API_KEY:
        url = "https://api.bing.microsoft.com/v7.0/images/search"
        headers = {"Ocp-Apim-Subscription-Key": BING_API_KEY}
        params = {"q": query, "count": max_results}

        try:
            resp = requests.get(url, headers=headers, params=params).json()
            for img in resp.get("value", []):
                if len(images) < max_results:
                    images.append(img.get("contentUrl"))
        except:
            pass

    return images[:max_results]

# --------------------- MARKDOWN RESPONSE BUILDER ------------------------------

def format_markdown(result_entry):
    name = result_entry.get("name", "Unknown Place")
    score = result_entry.get("final_score_normalized", 0)
    url = result_entry.get("source_url") or result_entry.get("website")

    md = f"## ⭐ {name}\n"
    md += f"**Match Score:** {score * 100:.1f}%\n\n"

    if url:
        md += f"🔗 **Link:** {url}\n\n"

    # Images
    imgs = fetch_images(name)
    for img in imgs:
        md += f"![image]({img})\n"

    md += "\n---\n"

    # Menu items
    if result_entry.get("menu_items"):
        md += "### 🍔 Menu Highlights\n"
        for i in result_entry["menu_items"][:5]:
            md += f"- {i}\n"
        md += "\n"

    # Reviews
    if result_entry.get("reviews"):
        md += "### 💬 Popular Reviews\n"
        for r in result_entry["reviews"][:3]:
            md += f"- {r}\n"
        md += "\n"

    return md


# --------------------- MAIN RUNNER -----------------------------------------

if __name__ == "__main__":
    query = input("Enter your food search query: ")

    results = find_places(query)

    # Format top 3 entries
    print("\n\n====================== AI RESULTS ======================\n")

    for entry in results.get("results", [])[:3]:
        print(format_markdown(entry))
