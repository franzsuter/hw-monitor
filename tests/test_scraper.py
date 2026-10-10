import contextlib
import io
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import scraper


def record(title="Modul"):
    return {
        "Bezeichnung": title,
        "Beschreibung": "PV",
        "Gesuchsteller": "Firma",
        "Gültig bis": "01.01.2030",
        "Klassierung": "HW 4",
    }


def row(number="42", title="Modul", attributes="", missing=None):
    fields = {"VKF Nummer": number, **record(title)}
    cells = "".join(
        f'<td data-heading="{key}">{value}</td>'
        for key, value in fields.items() if key != missing
    )
    return f"<tr {attributes}>{cells}</tr>"


class ExtractionTests(unittest.TestCase):
    def test_fields_and_certificate_link_text(self):
        html = row(number='<a href="/certificate">42</a> Details')
        self.assertEqual(scraper.extrahiere_alle_daten(html), {"42": record()})

    def test_hidden_rows_and_parents_are_ignored(self):
        html = (
            row("1", attributes='hidden')
            + row("2", attributes='style="DISPLAY :\tNONE !important"')
            + '<table hidden>' + row("3") + '</table>'
            + row("4")
        )
        self.assertEqual(set(scraper.extrahiere_alle_daten(html)), {"4"})

    def test_missing_field_rejects_entire_result_with_row_and_field(self):
        with self.assertRaisesRegex(scraper.ExtractionError, "VKF 42:.*Beschreibung"):
            scraper.extrahiere_alle_daten(row("41") + row("42", missing="Beschreibung"))

    def test_missing_certificate_number_is_an_error(self):
        with self.assertRaisesRegex(scraper.ExtractionError, "ohne VKF Nummer"):
            scraper.extrahiere_alle_daten(row(" "))

    def test_missing_certificate_column_is_an_error(self):
        with self.assertRaisesRegex(scraper.ExtractionError, "ohne VKF-Nummernfeld"):
            scraper.extrahiere_alle_daten(row(missing="VKF Nummer"))

    def test_search_highlighting_does_not_change_field_text(self):
        plain = row(title="JA Solar Modul")
        highlighted = row(title='<span class="keyword">JA Solar</span> Modul')
        self.assertEqual(scraper.extrahiere_alle_daten(plain), scraper.extrahiere_alle_daten(highlighted))

    def test_conflicting_duplicate_is_an_error(self):
        with self.assertRaisesRegex(scraper.ExtractionError, "widersprüchliche"):
            scraper.extrahiere_alle_daten(row() + row(title="Anderes Modul"))

    def test_identical_duplicate_is_deduplicated(self):
        self.assertEqual(scraper.extrahiere_alle_daten(row() + row()), {"42": record()})


class AtomicWriteTests(unittest.TestCase):
    def test_valid_json_replaces_old_file_without_temporary_files(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "data.json"
            target.write_text('{"old": true}', encoding="utf-8")
            scraper.save_json(target, {"new": "Gültig"})
            self.assertEqual(json.loads(target.read_text()), {"new": "Gültig"})
            self.assertEqual(list(Path(directory).iterdir()), [target])

    def test_serialization_failure_preserves_original_file(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "data.json"
            original = '{"old": true}'
            target.write_text(original, encoding="utf-8")
            with self.assertRaises(TypeError):
                scraper.save_json(target, {"invalid": object()})
            self.assertEqual(target.read_text(), original)
            self.assertEqual(list(Path(directory).iterdir()), [target])

    def test_replace_failure_preserves_original_file(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "data.json"
            target.write_text('{"old": true}', encoding="utf-8")
            with patch.object(scraper.os, "replace", side_effect=OSError("disk error")):
                with self.assertRaises(OSError):
                    scraper.save_json(target, {"new": True})
            self.assertEqual(json.loads(target.read_text()), {"old": True})
            self.assertEqual(list(Path(directory).iterdir()), [target])


class ScanPersistenceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.data = Path(self.temporary.name) / "data.json"
        self.history = Path(self.temporary.name) / "history.json"
        self.old = {"1": record("Alt"), "2": record("Entfernt"), "3": record("Unverändert")}
        self.old_history = [{"datum": "01.01.2026 12:00", "funde": []}]
        scraper.save_json(self.data, self.old)
        scraper.save_json(self.history, self.old_history)
        for name, value in (("DATEN_DATEI", self.data), ("HISTORY_DATEI", self.history)):
            replacement = patch.object(scraper, name, value)
            replacement.start()
            self.addCleanup(replacement.stop)

    async def run_scan(self, result=None, error=None):
        fetch = AsyncMock(return_value=result, side_effect=error)
        with patch.object(scraper, "hole_alle_daten", fetch), contextlib.redirect_stdout(io.StringIO()):
            await scraper.main()

    def assert_unchanged(self):
        self.assertEqual(json.loads(self.data.read_text()), self.old)
        self.assertEqual(json.loads(self.history.read_text()), self.old_history)

    async def test_incomplete_scan_preserves_both_files(self):
        with self.assertRaises(scraper.ScanError):
            await self.run_scan(error=scraper.ScanError("Suche nach beta fehlgeschlagen"))
        self.assert_unchanged()

    async def test_empty_scan_preserves_both_files_and_fails(self):
        with self.assertRaises(scraper.ScanError):
            await self.run_scan(result={})
        self.assert_unchanged()

    async def test_new_changed_and_removed_certificates_are_logged(self):
        new = {"1": record("Aktualisiert"), "3": self.old["3"], "4": record("Neu")}
        await self.run_scan(result=new)
        self.assertEqual(json.loads(self.data.read_text()), new)
        history = json.loads(self.history.read_text())
        self.assertEqual({(f["nr"], f["typ"]) for f in history[0]["funde"]}, {
            ("1", "UPDATE"), ("2", "ENTFERNT"), ("4", "NEU"),
        })
        self.assertEqual(history[1:], self.old_history)
        scan_at = datetime.fromisoformat(history[0]["scan_at"])
        self.assertEqual(scan_at.utcoffset(), scan_at.astimezone(scraper.ZEITZONE).utcoffset())
        self.assertEqual(scan_at.strftime("%d.%m.%Y %H:%M"), history[0]["datum"])

    async def test_unchanged_scan_is_logged_and_history_is_limited(self):
        scraper.save_json(self.history, self.old_history * 35)
        await self.run_scan(result=self.old)
        history = json.loads(self.history.read_text())
        self.assertEqual(len(history), 30)
        self.assertEqual(history[0]["funde"], [])

    async def test_corrupt_history_prevents_data_replacement(self):
        self.history.write_text('{broken', encoding="utf-8")
        with self.assertRaises(json.JSONDecodeError):
            await self.run_scan(result={"4": record("Neu")})
        self.assertEqual(json.loads(self.data.read_text()), self.old)
        self.assertEqual(self.history.read_text(), '{broken')

    async def test_failed_data_write_does_not_log_success(self):
        with patch.object(scraper, "save_json", side_effect=OSError("disk error")):
            with self.assertRaises(OSError):
                await self.run_scan(result={"4": record("Neu")})
        self.assert_unchanged()


class ExitStatusTests(unittest.TestCase):
    def test_empty_scan_returns_failure_status(self):
        with patch.object(scraper, "hole_alle_daten", AsyncMock(return_value={})), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(scraper.cli(), 1)

    def test_partial_scan_returns_failure_status(self):
        with patch.object(scraper, "hole_alle_daten", AsyncMock(side_effect=scraper.ScanError("partial"))), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(scraper.cli(), 1)
