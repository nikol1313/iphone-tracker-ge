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


def make_new_email():
    # A different email every run, so "Create account" never says it already exists.
    return f"e2e{int(time.time() * 1000)}@example.com"


def create_account(page: Page):
    # Open the account menu and choose "Sign in".
    page.click("#accountButton")
    page.click("#signInMenuButton")

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

    expect(page).to_have_title("Discover — Price Monitor")
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
    expect(page.locator("#trackedContent .alert-value")).to_contain_text("900.00")

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
