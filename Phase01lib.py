import socket
import requests
import asyncio
from playwright.async_api import async_playwright

# ---------- 1) Check internet connectivity ----------
def is_connected(host="8.8.8.8", port=53, timeout=3):
    try:
        socket.create_connection((host, port), timeout=timeout)
        return True
    except:
        return False

# ---------- 2) Get Local IP ----------
def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "Unknown"

# ---------- 3) Get Public IP ----------
def get_public_ip():
    try:
        res = requests.get("https://api.ipify.org?format=json", timeout=5)
        return res.json().get("ip")
    except:
        return "Unknown"

# ---------- 4) Browser Public IP ----------
async def browser_public_ip(playwright):
    browser = await playwright.chromium.launch(headless=True)
    page = await browser.new_page()
    await page.goto("https://api.ipify.org?format=json", timeout=15000)

    content = await page.content()
    await browser.close()

    import re
    match = re.search(r'(\d{1,3}(?:\.\d{1,3}){3})', content)
    return match.group(1) if match else None

# ---------- Main Pipeline ----------
async def main():
    print("\nChecking Internet Connection...\n")

    if not is_connected():
        print("❌ No Internet Connection")
        return

    print("✅ Internet Connected Successfully")

    local_ip = get_local_ip()
    public_ip = get_public_ip()

    print(f"Local IP Address:  {local_ip}")
    print(f"Public IP Address: {public_ip}\n")

    async with async_playwright() as pw:
        print("Launching Headless Browser...\n")
        browser_ip = await browser_public_ip(pw)
        print(f"Browser Public IP: {browser_ip}")

    print("\n==== PIPELINE COMPLETED SUCCESSFULLY ====\n")

# ---------- Run main ----------
if __name__ == "__main__":
    asyncio.run(main())
