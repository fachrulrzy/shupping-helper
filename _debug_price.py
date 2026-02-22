import json, random
from playwright.sync_api import sync_playwright
from fake_useragent import UserAgent
from playwright_stealth import Stealth

ua = UserAgent()
captured = []

all_gql_responses = []

def handle_resp(response):
    try:
        if "gql.tokopedia.com" in response.url and response.status == 200:
            body = response.json()
            all_gql_responses.append(body)
            items = body if isinstance(body, list) else [body]
            for item in items:
                data = item.get("data") or {}
                for key in data.keys():
                    node = data[key]
                    if isinstance(node, dict):
                        products = node.get("data", {}).get("products", [])
                        if not products:
                            products = node.get("products", [])
                        if products:
                            captured.extend(products)
    except:
        pass

with sync_playwright() as pw:
    browser = pw.chromium.launch(channel="chrome", headless=True)
    ctx = browser.new_context(
        user_agent=ua.random,
        viewport={"width": 1366, "height": 768},
        locale="id-ID",
    )
    page = ctx.new_page()
    # Stealth().apply_stealth_sync(page)
    page.on("response", handle_resp)
    page.goto(
        "https://www.tokopedia.com/search?q=adidas+samba",
        wait_until="domcontentloaded",
        timeout=45000,
    )
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except:
        pass
    for _ in range(3):
        page.evaluate("window.scrollBy(0, 800)")
        page.wait_for_timeout(1000)
    page.wait_for_timeout(3000)
    ctx.close()
    browser.close()

if captured:
    for i, p in enumerate(captured[:3]):
        name = p.get("name", "?")[:50]
        print(f"--- Product {i}: {name} ---")
        print("price:", repr(p.get("price")))
        print("rating:", repr(p.get("rating")))
        print("shop:", repr(p.get("shop")))
        print("ads:", repr(p.get("ads")))
        print("labelGroups:", repr(p.get("labelGroups")[:2] if p.get("labelGroups") else None))
        print()
else:
    print("No products captured")
    print(f"Total GQL responses: {len(all_gql_responses)}")
    for i, r in enumerate(all_gql_responses[:5]):
        items = r if isinstance(r, list) else [r]
        for item in items:
            data = item.get("data") or {}
            if data:
                print(f"  Response {i} keys: {list(data.keys())}")
                for k, v in data.items():
                    if isinstance(v, dict):
                        print(f"    {k} sub-keys: {list(v.keys())[:10]}")
                        d_inner = v.get("data")
                        if isinstance(d_inner, dict):
                            print(f"      data sub-keys: {list(d_inner.keys())[:10]}")
