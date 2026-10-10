import contextlib
import io
import json
import os
import threading
import unittest
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.async_api import async_playwright

import scraper
from test_scraper import record, row


BROWSER_TESTS = os.environ.get("RUN_BROWSER_TESTS") == "1"
ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(BROWSER_TESTS, "RUN_BROWSER_TESTS=1 aktiviert Chromium-Prüfungen")
class DashboardTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=True)
        self.page = await self.browser.new_page()
        self.errors = []
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.data = {"1": record()}
        self.history = [{"datum": "01.01.2020 12:00", "funde": []}]
        self.data_status = 200
        self.history_status = 200
        await self.page.route("http://monitor.test/**", self.route)

    async def asyncTearDown(self):
        await self.browser.close()
        await self.playwright.stop()

    async def route(self, route):
        if route.request.url.endswith("hagelregister_daten.json"):
            await route.fulfill(status=self.data_status, content_type="application/json", body=json.dumps(self.data))
        elif route.request.url.endswith("history.json"):
            await route.fulfill(status=self.history_status, content_type="application/json", body=json.dumps(self.history))
        else:
            await route.fulfill(content_type="text/html", body=(ROOT / "index.html").read_text(encoding="utf-8"))

    async def open(self):
        await self.page.goto("http://monitor.test/")
        await self.page.wait_for_function("!document.getElementById('erneut-laden').disabled")
        self.assertEqual(self.errors, [])

    async def test_existing_data_and_legacy_scan_timestamp(self):
        self.data = json.loads((ROOT / "hagelregister_daten.json").read_text())
        self.history = json.loads((ROOT / "history.json").read_text())
        await self.open()
        self.assertEqual(await self.page.locator("#inhalt tr").count(), len(self.data))
        self.assertEqual(await self.page.locator("#history-inhalt p").count(), len(self.history))
        self.assertIn(self.history[0]["datum"], await self.page.locator("#zeitstempel").inner_text())

    async def test_html_payloads_are_shown_as_text_in_both_sections(self):
        payload = '<img src="data:,invalid" onerror="window.reviewMarker=1">'
        self.data = {payload: record(payload)}
        self.history = [{"datum": payload, "funde": [{"nr": payload, "bezeichnung": payload, "typ": "NEU"}]}]
        await self.open()
        self.assertIn(payload, await self.page.locator("#inhalt").inner_text())
        self.assertIn(payload, await self.page.locator("#history-inhalt").inner_text())
        self.assertEqual(await self.page.locator("#inhalt img, #history-inhalt img").count(), 0)
        self.assertIsNone(await self.page.evaluate("window.reviewMarker"))

    async def test_data_http_error_has_message_and_retry_recovers_without_duplicates(self):
        self.data_status = 503
        await self.open()
        self.assertIn("nicht geladen", await self.page.locator("#loading").inner_text())
        self.assertTrue(await self.page.locator("#erneut-laden").is_visible())
        self.data_status = 200
        await self.page.locator("#erneut-laden").click()
        await self.page.wait_for_selector("#tabelle", state="visible")
        await self.page.wait_for_function("!document.getElementById('erneut-laden').disabled")
        self.assertEqual(await self.page.locator("#inhalt tr").count(), 1)
        self.assertEqual(await self.page.locator("#history-inhalt p").count(), 1)
        self.assertFalse(await self.page.locator("#erneut-laden").is_visible())

    async def test_history_error_does_not_hide_successful_data(self):
        self.history_status = 404
        await self.open()
        self.assertTrue(await self.page.locator("#tabelle").is_visible())
        self.assertIn("nicht geladen", await self.page.locator("#history-inhalt").inner_text())
        self.assertIn("unbekannt", await self.page.locator("#zeitstempel").inner_text())
        self.assertTrue(await self.page.locator("#erneut-laden").is_visible())

    async def test_iso_scan_timestamp_uses_swiss_time_and_warns_for_old_data(self):
        self.history[0]["scan_at"] = "2020-07-01T12:00:00+00:00"
        await self.open()
        text = await self.page.locator("#zeitstempel").inner_text()
        self.assertIn("14:00", text)
        self.assertIn("älter als 48 Stunden", text)

    async def test_recent_scan_does_not_warn(self):
        self.history[0]["scan_at"] = datetime.now(timezone.utc).isoformat()
        await self.open()
        self.assertNotIn("älter", await self.page.locator("#zeitstempel").inner_text())

    async def test_removed_certificate_has_label_and_style(self):
        self.history[0]["funde"] = [{"nr": "42", "bezeichnung": "Entferntes Modul", "typ": "ENTFERNT"}]
        await self.open()
        self.assertEqual(await self.page.locator(".entfernt-tag").inner_text(), "[ENTFERNT]")

    async def test_invalid_json_shapes_show_error_instead_of_partial_data(self):
        self.data = {"1": {"Bezeichnung": "Unvollständig"}}
        self.history = {"wrong": "shape"}
        await self.open()
        self.assertIn("nicht geladen", await self.page.locator("#loading").inner_text())
        self.assertIn("nicht geladen", await self.page.locator("#history-inhalt").inner_text())
        self.assertEqual(await self.page.locator("#inhalt tr").count(), 0)


FILTER_SCRIPT = """
<script>
document.querySelector('input').addEventListener('keypress', event => {
    if (event.key !== 'Enter') return;
    event.preventDefault();
    const term = event.target.value.toLowerCase();
    for (const row of document.querySelectorAll('tbody tr')) {
        row.style.display = row.textContent.toLowerCase().includes(term) ? '' : 'none';
    }
});
</script>
"""


@unittest.skipUnless(BROWSER_TESTS, "RUN_BROWSER_TESTS=1 aktiviert Chromium-Prüfungen")
class SearchBrowserTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(handler):
                handler.send_response(self.status)
                handler.send_header("Content-Type", "text/html; charset=utf-8")
                handler.end_headers()
                handler.wfile.write(self.html.encode("utf-8"))

            def log_message(handler, *args):
                pass

        self.status = 200
        self.html = ""
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}/"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    async def search(self, html, terms):
        self.html = (
            '<style>.hidden { display: none }</style>'
            '<input placeholder="Hier Suchbegriff(e) eingeben">'
            '<table><tbody>' + html + '</tbody></table>' + FILTER_SCRIPT
        )
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return await scraper.hole_alle_daten(url=self.url, suchbegriffe=terms)

    async def test_real_browser_filters_each_term_and_accepts_no_match(self):
        result = await self.search(row("1", "Alpha") + row("2", "Beta"), ["alpha", "no match", "beta"])
        self.assertEqual(result, {"1": record("Alpha"), "2": record("Beta")})

    async def test_css_hidden_rows_are_excluded_by_browser_visibility(self):
        result = await self.search(row("1", "Alpha") + row("2", "Alpha", 'class="hidden"'), ["alpha"])
        self.assertEqual(set(result), {"1"})

    async def test_one_malformed_search_rejects_previously_successful_results(self):
        with self.assertRaisesRegex(scraper.ScanError, "unvollständig.*beta"):
            await self.search(row("1", "Alpha") + row("2", "Beta", missing="Beschreibung"), ["alpha", "beta"])

    async def test_missing_number_column_rejects_partial_result(self):
        with self.assertRaisesRegex(scraper.ScanError, "unvollständig"):
            await self.search(row("1", "Alpha") + row("2", "Alpha", missing="VKF Nummer"), ["alpha"])

    async def test_all_empty_queries_fail(self):
        with self.assertRaisesRegex(scraper.ScanError, "Keine Daten"):
            await self.search(row("1", "Alpha"), ["absent"])

    async def test_http_error_is_a_failed_scan(self):
        self.status = 503
        with self.assertRaisesRegex(scraper.ScanError, "HTTP 503"):
            await self.search(row("1", "Alpha"), ["alpha"])
