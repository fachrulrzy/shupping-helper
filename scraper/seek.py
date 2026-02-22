from playwright.sync_api import sync_playwright
from seleniumbase import sb_cdp

sb = sb_cdp.Chrome(locale="en", ad_block=True)
endpoint_url = sb.get_endpoint_url()

with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp(endpoint_url)
    context = browser.contexts[0]
    page = context.pages[0]
    page.goto("https://www.footlocker.id/")
    sb.maximize()
    page.wait_for_timeout(5000)
    sb.click_if_visible("//button[text()='Accept Cookies']")
    sb.sleep(2)
    sb.click_if_visible("//*[contains(@class, 'popup-newsletter')]//button[@class='action-close']")
    sb.sleep(2)
    input_field = "//input[@id='search']"
    page.wait_for_selector(input_field)
    sb.sleep(1)
    page.click(input_field)
    sb.press_keys(input_field, "adidas samba")
    sb.sleep(2)
    sb.click_if_visible("//button[@aria-label='Search']")
    input("Press Enter to close the browser...")  # keeps browser open
    # sb.maximize()
    # print(page.content())
    # browser.close()