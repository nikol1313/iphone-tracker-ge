"""Browser tests with Playwright.

These tests click through the real website like a user would.
Start the app first with `docker compose up`, then run:

    uv run playwright install chromium   # only the first time
    uv run pytest -m e2e
"""

import time

import pytest
from playwright.sync_api import Page, expect

# Every test in this file is a browser test.
pytestmark = pytest.mark.e2e

SITE_URL = "http://localhost:8080"
PASSWORD = "password123"


@pytest.fixture(autouse=True)
def english(page: Page):
    # The site opens in Georgian; these tests read the English text.
    page.add_init_script("localStorage.setItem('iphoneTrackerLang', 'en')")


def make_new_email():
    # A different email every run, so "Create account" never says it already exists.
    return f"e2e{int(time.time() * 1000)}@example.com"


def create_account(page: Page):
    # The "Sign in" button in the top bar opens the sign-in form.
    page.click("#accountButton")

    # Switch the dialog from "Sign in" to "Create account".
    page.click("#authMode")
    expect(page.locator("#authTitle")).to_have_text("Create account")

    # Fill in the form and send it.
    page.fill("#authForm input[name=email]", make_new_email())
    page.fill("#authForm input[name=password]", PASSWORD)
    page.click("#authForm button[type=submit]")

    # The site shows a message when it worked.
    expect(page.locator("#toast")).to_have_text("Account created and signed in.")


def open_first_iphone(page: Page):
    # Go to the iPhones page and click the first phone card.
    page.goto(SITE_URL + "/?page=products")
    first_card = page.locator("#productGrid [data-product-id]").first
    first_card.click()


def test_home_page_opens(page: Page):
    page.goto(SITE_URL)

    expect(page).to_have_title("iPhone prices in Georgia — iPhone Tracker")
    expect(page.locator("#accountButton")).to_be_visible()


def test_set_edit_and_remove_an_alert(page: Page):
    page.goto(SITE_URL)
    create_account(page)
    open_first_iphone(page)

    # 1. Set a new alert.
    alert_button = page.locator("#selectedAlertButton")
    expect(alert_button).to_have_text("Set alert")
    alert_button.click()
    page.fill("#alertTargetPrice", "1000")
    page.click("#alertSubmit")
    expect(page.locator("#toast")).to_contain_text("Alert set")

    # 2. The button now says "Edit alert" and the dialog remembers our price.
    expect(alert_button).to_have_text("Edit alert")
    alert_button.click()
    expect(page.locator("#alertTargetPrice")).to_have_value("1000.00")
    expect(page.locator("#alertSubmit")).to_have_text("Update alert")

    # 3. Change the price.
    page.fill("#alertTargetPrice", "900")
    page.click("#alertSubmit")
    expect(page.locator("#toast")).to_contain_text("Alert updated")

    # 4. The watchlist shows the new price.
    page.goto(SITE_URL + "/?page=alerts")
    expect(page.locator("#trackedContent .alert-value")).to_contain_text("900 ₾")

    # 5. Remove the alert from the watchlist.
    page.click("#trackedContent [data-edit-alert]")
    page.click("#alertRemoveButton")
    expect(page.locator("#toast")).to_have_text("Alert removed. The phone stays on your watchlist.")
    expect(page.locator("#trackedContent [data-edit-alert]")).to_have_text("Set alert")


def test_email_needs_confirmation(page: Page):
    page.goto(SITE_URL)
    create_account(page)

    # Save an email address for alerts.
    page.click("#accountButton")
    page.click("[data-notification=email]")
    page.fill("#emailForm input[name=notification_email]", "me@example.com")
    page.click("#emailForm button[type=submit]")

    # The address is not confirmed yet, so the test email button stays off.
    expect(page.locator("#emailVerificationStatus")).to_contain_text("not confirmed yet")
    expect(page.locator("#emailTestButton")).to_be_disabled()


def test_fake_confirmation_link_shows_an_error(page: Page):
    page.goto(SITE_URL + "/?verify_email=not-a-real-token")

    expect(page.locator("#toast")).to_contain_text("invalid or has expired")


def test_site_opens_in_georgian_and_switches_to_english(browser):
    # A fresh browser with no saved choice, so the default language shows.
    page = browser.new_page()
    page.goto(SITE_URL)
    expect(page.locator("html")).to_have_attribute("lang", "ka")
    expect(page.locator("#overviewTitle")).to_have_text("ყველა iPhone, ყველა ფასი, ერთ ადგილას")

    # Switching keeps you where you were on the page.
    page.wait_for_selector(".model-price")
    page.evaluate("window.scrollTo({ top: 600, behavior: 'instant' })")
    scrolled = page.evaluate("window.scrollY")
    page.click("#langToggle")
    expect(page.locator("#overviewTitle")).to_have_text("Every iPhone, every price, one place")
    expect(page.locator("#langToggle")).to_have_text("ქართ")
    expect(page.locator(".model-price-meta").first).to_contain_text("In stock at")
    # Shorter English text above can nudge it a little, but it must not jump to the top.
    assert scrolled > 0
    assert page.evaluate("window.scrollY") > scrolled / 2
    page.close()


def test_search_waits_for_the_search_button(page: Page):
    page.goto(SITE_URL + "/?page=products")
    count = page.locator("#productCount")
    expect(count).not_to_have_text("Loading…")
    everything = count.inner_text()

    # Typing alone leaves the list as it was.
    page.fill("#searchInput", "iphone 15")
    page.wait_for_timeout(300)
    expect(count).to_have_text(everything)

    # Pressing Search filters it.
    page.click("#searchForm button[type=submit]")
    expect(count).not_to_have_text(everything)
    expect(page.locator("#productGrid [data-product-id]").first).to_contain_text("iPhone 15")

    # Emptying the box brings every phone back.
    page.fill("#searchInput", "")
    expect(count).to_have_text(everything)


def test_search_hints_offer_models_and_search_when_chosen(page: Page):
    page.goto(SITE_URL + "/?page=products")
    count = page.locator("#productCount")
    expect(count).not_to_have_text("Loading…")
    everything = count.inner_text()

    page.fill("#searchInput", "15")
    hints = page.locator("#searchInput + .suggestions li")
    expect(hints.first).to_be_visible()
    labels = hints.locator("span").all_inner_texts()
    assert labels and all("15" in label for label in labels)
    # Hints alone don't filter.
    expect(count).to_have_text(everything)

    # Arrow down + Enter chooses the first hint and searches for it.
    page.keyboard.press("ArrowDown")
    page.keyboard.press("Enter")
    expect(page.locator("#searchInput")).to_have_value(labels[0])
    expect(count).not_to_have_text(everything)
    expect(page.locator("#searchInput + .suggestions")).to_be_hidden()


def test_compare_two_phones_by_typing_their_models(page: Page):
    page.goto(SITE_URL + "/?page=compare")
    expect(page.locator("#compareResult")).to_contain_text("Choose two phones")

    for side, model in (("a", "17 Pro Max"), ("b", "16")):
        page.fill(f"#compare-{side}-search", model)
        page.locator(f"#compare-{side}-search + .suggestions li").first.click()
        expect(page.locator(f"#compare-{side}-search")).to_have_value(f"iPhone {model}")

    # Specs side by side; the pick waits until we say what the phone is for.
    expect(page.locator(".spec-table").first).to_contain_text("Chip")
    expect(page.locator(".compare-pick")).to_contain_text("What will you mostly use the phone for?")
    expect(page.locator(".compare-pick-headline")).to_have_count(0)
    assert "a=" in page.url and "b=" in page.url

    page.locator('.compare-pick [data-use="gaming"]').click()
    expect(page.locator(".compare-pick h2")).to_have_text("Our pick for gaming")
    expect(page.locator('.compare-pick [data-use="gaming"]')).to_have_attribute("aria-pressed", "true")
    expect(page.locator(".compare-pick-headline")).to_be_visible()
    assert "use=gaming" in page.url
    # Both phones get a list of where they beat the other, not only the pick.
    expect(page.locator(".compare-edge")).to_have_count(2)
    expect(page.locator(".compare-edge h3").first).to_contain_text("is better")
