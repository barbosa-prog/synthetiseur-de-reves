"""Recette Chrome P13 : pages publiques, aucune donnée ni session personnelle."""

import os
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect, sync_playwright


@pytest.mark.browser
@pytest.mark.parametrize("width", [1280, 390])
def test_privacy_public_navigation_desktop_mobile(width, tmp_path):
    origin = os.getenv("WEB_TEST_URL", "")
    chrome = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    if not origin or not chrome.is_file():
        pytest.skip("Chrome/origine temporaire absent")
    # Ne jamais utiliser l'instance personnelle, même pour cette page publique.
    target = urlsplit(origin)
    assert target.hostname == "127.0.0.1" and target.scheme == "https"
    assert target.port not in {None, 5434, 8443}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(chrome), headless=True)
        try:
            context = browser.new_context(ignore_https_errors=True,
                                          viewport={"width": width, "height": 900})
            page = context.new_page()
            requested, errors = [], []
            page.on("request", lambda request: requested.append(request.url))
            page.on("pageerror", lambda error: errors.append(str(error)))
            assert page.goto(origin + "/confidentialite").status == 200
            expect(page.get_by_role("heading", name="Confidentialité", exact=True)).to_be_visible()
            expect(page.get_by_text("Propositions non activées", exact=False)).to_be_visible()
            assert not any(cookie["name"] == "__Host-dream_session"
                           for cookie in context.cookies())
            assert page.locator("html").evaluate("node => node.scrollWidth <= innerWidth")
            page.screenshot(path=str(tmp_path / f"notice-{width}.png"))
            footer = page.locator("footer").get_by_role("link", name="Confidentialité")
            footer.scroll_into_view_if_needed()
            expect(footer).to_be_visible()
            footer.click()
            expect(page).to_have_url(origin + "/confidentialite")
            page.goto(origin + "/inscription")
            expect(page.get_by_role("heading", name="Créer votre compte")).to_be_visible()
            inline = page.locator("main").get_by_role("link", name="notice de confidentialité")
            inline.scroll_into_view_if_needed()
            expect(inline).to_be_visible()
            page.screenshot(path=str(tmp_path / f"inscription-{width}.png"))
            inline.click()
            expect(page).to_have_url(origin + "/confidentialite")
            assert page.locator("html").evaluate("node => node.scrollWidth <= innerWidth")
            assert requested and all(urlsplit(url).netloc == target.netloc for url in requested)
            assert not errors
        finally:
            browser.close()
