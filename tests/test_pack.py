"""Tests for the Free Pet Care Pack.

Run with:
    python3 -m unittest discover -s tests -v

Covers:
  * every sheet source exists and passes source validation
  * sources contain no external URLs (offline pack) and no branding
  * the privacy guards: templates ship blank — no phone-like numbers,
    no microchip-style digit runs, at most a handful of stray digits
  * per-sheet structure: profiles' photo box, vet rows, two handoff
    cards + cut line, a mon..sun feeding week, nine flyer tabs, six
    pet-safe rooms with ticked-off checkboxes
  * the validator catches corrupted sheets (mutation tests)
  * a fresh end-to-end build produces valid PDFs with the expected pages
  * the committed printables/*.pdf set is valid, complete and brand-free
  * project meta files: LICENSE copyright line, README credit, STATUS.md
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import build  # noqa: E402

try:
    from pypdf import PdfReader
except ImportError:  # pragma: no cover
    PdfReader = None


def _renderer_env() -> dict:
    """Pin the build's renderer for the test suite (weasyprint preferred)."""
    env = dict(os.environ)
    if env.get("PRINT_RENDERER") in ("chrome", "weasyprint"):
        return env
    if build.find_weasyprint():
        env["PRINT_RENDERER"] = "weasyprint"
    elif build.find_chrome():
        env["PRINT_RENDERER"] = "chrome"
    return env


def _mutate(slug: str, old: str, new: str) -> str:
    """Return a source with one occurrence swapped; brute force the rest."""
    text = (build.SHEETS_DIR / f"{slug}.html").read_text(encoding="utf-8")
    return text.replace(old, new, 1)


class SheetSources(unittest.TestCase):
    def test_every_source_exists(self) -> None:
        for slug in build.SHEETS:
            with self.subTest(slug=slug):
                self.assertTrue((build.SHEETS_DIR / f"{slug}.html").is_file())
        self.assertTrue((build.SHEETS_DIR / "shared" / "shared.css").is_file())

    def test_sources_validate_with_expected_pages(self) -> None:
        for slug in build.SHEETS:
            with self.subTest(slug=slug):
                self.assertEqual(build.validate_source(slug), build.EXPECTED_PAGES[slug])

    def test_sources_are_fully_offline(self) -> None:
        for path in sorted(build.SHEETS_DIR.rglob("*")):
            if path.suffix in (".html", ".css"):
                with self.subTest(file=str(path)):
                    text = path.read_text(encoding="utf-8").lower()
                    self.assertNotRegex(text, r"https?://")
                    self.assertNotIn("<script", text)

    def test_sources_are_brand_free(self) -> None:
        for path in sorted(build.SHEETS_DIR.rglob("*")):
            if path.suffix in (".html", ".css"):
                with self.subTest(file=str(path)):
                    text = path.read_text(encoding="utf-8").lower()
                    for needle in build.FORBIDDEN_STRINGS:
                        self.assertNotIn(needle, text)

    def test_validate_only_exits_zero(self) -> None:
        proc = subprocess.run(
            [sys.executable, str(ROOT / "build.py"), "--validate-only"],
            capture_output=True, text=True, cwd=ROOT, timeout=120,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_list_slugs(self) -> None:
        proc = subprocess.run(
            [sys.executable, str(ROOT / "build.py"), "--list"],
            capture_output=True, text=True, cwd=ROOT, timeout=60,
        )
        self.assertEqual(proc.stdout.split(), build.SHEETS)


class PrivacyGuards(unittest.TestCase):
    """The templates must ship blank: no personal data baked into sources."""

    def test_body_text_strips_styles_and_tags(self) -> None:
        src = "<head><meta charset='utf-8'></head><style>p{margin:1mm 2mm}</style><body><p>a &amp; b</p></body>"
        self.assertEqual(build.body_text(src), "a &amp; b")

    def test_real_sources_pass_digit_scan(self) -> None:
        for slug in build.SHEETS:
            with self.subTest(slug=slug):
                text = (build.SHEETS_DIR / f"{slug}.html").read_text(encoding="utf-8")
                build.validate_no_personal_digits(slug, text)  # raises on failure

    def test_phone_like_number_is_caught(self) -> None:
        src = '<p>contact: (555) 123-4567</p>'
        with self.assertRaises(build.BuildError):
            build.validate_no_personal_digits("x", src)
        spaced = '<p>contact: 555 123 4567</p>'
        with self.assertRaises(build.BuildError):
            build.validate_no_personal_digits("x", spaced)
        dashed = '<p>contact: 555-123-4567</p>'
        with self.assertRaises(build.BuildError):
            build.validate_no_personal_digits("x", dashed)

    def test_microchip_style_run_is_caught(self) -> None:
        src = '<p>chip: 987654323</p>'
        with self.assertRaises(build.BuildError):
            build.validate_no_personal_digits("x", src)

    def test_digit_budget_is_caught(self) -> None:
        src = '<p>1234567890</p>'  # too many stray digits overall
        with self.assertRaises(build.BuildError):
            build.validate_no_personal_digits("x", src)

    def test_small_digit_bundles_pass(self) -> None:
        src = '<p>week forty-two, bring the tags</p>'
        build.validate_no_personal_digits("x", src)  # no exception


class SheetStructure(unittest.TestCase):
    """Mutation tests: every structural guard actually catches damage."""

    def test_profile_photo_box_required(self) -> None:
        slug = "01-pet-profile"
        bad = _mutate(slug, '<div class="photo-box">', '<div class="ph">')
        with self.assertRaises(build.BuildError):
            build.validate_sheet(slug, bad)

    def test_profile_required_fields(self) -> None:
        slug = "01-pet-profile"
        bad = _mutate(slug, "tape a photo", "tape a picture")
        with self.assertRaises(build.BuildError):
            build.validate_sheet(slug, bad)

    def test_vet_rows_exactly_eight(self) -> None:
        slug = "02-vet-visit-log"
        base = (build.SHEETS_DIR / f"{slug}.html").read_text(encoding="utf-8")
        one_fewer = base.replace('<tr class="visit-row">', "", 1)
        with self.assertRaises(build.BuildError):
            build.validate_sheet(slug, one_fewer)
        extra = base + '<tr class="visit-row"><td></td><td></td><td></td><td></td><td></td></tr>'
        with self.assertRaises(build.BuildError):
            build.validate_sheet(slug, extra)

    def test_vaccine_rows_exactly_seven(self) -> None:
        slug = "02-vet-visit-log"
        base = (build.SHEETS_DIR / f"{slug}.html").read_text(encoding="utf-8")
        one_fewer = base.replace('<tr class="vac-row">', "", 1)
        with self.assertRaises(build.BuildError):
            build.validate_sheet(slug, one_fewer)

    def test_handoff_needs_two_cards_and_a_cut_line(self) -> None:
        slug = "03-sitter-handoff-card"
        base = (build.SHEETS_DIR / f"{slug}.html").read_text(encoding="utf-8")
        missing_cut = base.replace('class="cut-line"', 'class="cutlinex"', 1)
        with self.assertRaises(build.BuildError):
            build.validate_sheet(slug, missing_cut)
        single = base.rsplit('<div class="handoff-card">', 0)
        only_one = base[: base.find('<div class="handoff-card">')] + base[base.rfind('<div class="handoff-card">'):]
        with self.assertRaises(build.BuildError):
            build.validate_sheet(slug, only_one)

    def test_feeding_week_is_mon_through_sun_in_order(self) -> None:
        slug = "04-feeding-schedule"
        bad = _mutate(slug, 'data-day="wed">', 'data-day="weds">')
        with self.assertRaises(build.BuildError):
            build.validate_sheet(slug, bad)
        missing = _mutate(slug, 'data-day="fri"', 'data-dayz="fri"')
        with self.assertRaises(build.BuildError):
            build.validate_sheet(slug, missing)

    def test_flyer_needs_nine_tabs_and_safety_line(self) -> None:
        slug = "05-lost-pet-flyer"
        base = (build.SHEETS_DIR / f"{slug}.html").read_text(encoding="utf-8")
        eight_tabs = base.replace('<span class="tab">call:<i class="tl"></i></span>', "", 1)
        with self.assertRaises(build.BuildError):
            build.validate_sheet(slug, eight_tabs)
        no_chase = base.replace("don&rsquo;t chase", "please watch calmly")
        with self.assertRaises(build.BuildError):
            build.validate_sheet(slug, no_chase)

    def test_checklist_needs_six_unique_rooms_with_items(self) -> None:
        slug = "06-pet-safe-room-checklist"
        base = (build.SHEETS_DIR / f"{slug}.html").read_text(encoding="utf-8")
        dup = base.replace('data-room="living">', 'data-room="kitchen-floor">', 1).replace(
            'data-room="kitchen">', 'data-room="kitchen-floor">', 1)
        with self.assertRaises(build.BuildError):
            build.validate_sheet(slug, dup)

    def test_checklist_room_needs_five_items(self) -> None:
        slug = "06-pet-safe-room-checklist"
        src = (build.SHEETS_DIR / f"{slug}.html").read_text(encoding="utf-8")
        # squash one room into a stub with a single checkbox
        start = src.find('data-room="living"')
        end = src.find("<!-- /room -->", start) + len("<!-- /room -->")
        stub = '<section class="room" data-room="living"><h3>Living room</h3><ul><li><span class="cb"></span>stub</li></ul></section><!-- /room -->'
        with self.assertRaises(build.BuildError):
            build.validate_sheet(slug, src[:start] + stub + src[end:])

    def test_getting_started_contains_welcome_content(self) -> None:
        slug = "00-getting-started"
        base = (build.SHEETS_DIR / f"{slug}.html").read_text(encoding="utf-8")
        bad = base.replace("start here", "skip me").replace("Start Here", "Skip Me")
        self.assertNotEqual(bad, base)
        with self.assertRaises(build.BuildError):
            build.validate_sheet(slug, bad)


class FreshBuild(unittest.TestCase):
    """End-to-end: build every sheet into a temp dir and verify the PDFs."""

    @classmethod
    def setUpClass(cls) -> None:
        env = _renderer_env()
        cls.skip = not env.get("PRINT_RENDERER")
        cls.tmp = Path(tempfile.mkdtemp(prefix="pet-pack-build-"))
        cls.proc = None
        if not cls.skip:
            cls.proc = subprocess.run(
                [sys.executable, str(ROOT / "build.py"), "--out", str(cls.tmp)],
                capture_output=True, text=True, cwd=ROOT, env=env, timeout=600,
            )

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_build_command_succeeds(self) -> None:
        if self.skip:
            self.skipTest("no PDF renderer (Chrome/Chromium or WeasyPrint) available")
        self.assertEqual(self.proc.returncode, 0, self.proc.stderr)

    def test_every_sheet_builds_a_valid_pdf(self) -> None:
        if self.skip:
            self.skipTest("no PDF renderer available")
        for slug in build.SHEETS:
            pdf = self.tmp / f"{slug}.pdf"
            with self.subTest(slug=slug):
                self.assertTrue(pdf.is_file())
                data = pdf.read_bytes()
                self.assertTrue(data.startswith(b"%PDF-"))
                self.assertIn(b"%%EOF", data[-1024:])
                reader = PdfReader(str(pdf))
                self.assertEqual(len(reader.pages), build.EXPECTED_PAGES[slug])

    def test_pdfs_are_brand_free(self) -> None:
        if self.skip:
            self.skipTest("no PDF renderer available")
        for slug in build.SHEETS:
            data = (self.tmp / f"{slug}.pdf").read_bytes()
            with self.subTest(slug=slug):
                self.assertNotIn(b"Asdale", data)
                self.assertNotIn(b"Dynamics", data)

    def test_guide_page_is_last(self) -> None:
        if self.skip:
            self.skipTest("no PDF renderer available")
        for slug in build.SHEETS:
            reader = PdfReader(str(self.tmp / f"{slug}.pdf"))
            with self.subTest(slug=slug):
                last = (reader.pages[-1].extract_text() or "").lower()
                if build.GUIDE_PAGES[slug]:
                    self.assertIn("how to use", last)
                else:
                    self.assertIn("start here", last)

    def test_first_page_text_reports_expected_content(self) -> None:
        if self.skip:
            self.skipTest("no PDF renderer available")
        expected_first = {
            "00-getting-started": "\u2019s inside",
            "01-pet-profile": "pet profile sheet",
            "02-vet-visit-log": "vet-visit log",
            "03-sitter-handoff-card": "pet sitter",
            "04-feeding-schedule": "the week",
            "05-lost-pet-flyer": "lost pet",
            "06-pet-safe-room-checklist": "pet-safe room checklist",
        }
        for slug, needle in expected_first.items():
            reader = PdfReader(str(self.tmp / f"{slug}.pdf"))
            with self.subTest(slug=slug):
                first = (reader.pages[0].extract_text() or "").lower()
                self.assertIn(needle, first)


class CommittedPrintables(unittest.TestCase):
    @unittest.skipUnless(PdfReader is not None, "pypdf not installed")
    def test_all_expected_pdfs_are_valid_complete_and_brand_free(self) -> None:
        for slug, wanted in build.EXPECTED_PAGES.items():
            pdf = ROOT / "printables" / f"{slug}.pdf"
            with self.subTest(slug=slug):
                self.assertTrue(pdf.is_file(), f"{pdf} missing")
                data = pdf.read_bytes()
                self.assertTrue(data.startswith(b"%PDF-"))
                self.assertIn(b"%%EOF", data[-1024:])
                self.assertNotIn(b"Asdale", data)
                self.assertNotIn(b"Dynamics", data)
                self.assertEqual(len(PdfReader(str(pdf)).pages), wanted)

    @unittest.skipUnless(PdfReader is not None, "pypdf not installed")
    def test_guide_page_is_last_in_committed_pdf(self) -> None:
        for slug in build.GUIDE_PAGES:
            reader = PdfReader(str(ROOT / "printables" / f"{slug}.pdf"))
            last = (reader.pages[-1].extract_text() or "").lower()
            with self.subTest(slug=slug):
                if build.GUIDE_PAGES[slug]:
                    self.assertIn("how to use", last)

    def test_manifest_matches_printables(self) -> None:
        import json

        manifest = json.loads((ROOT / "printables" / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["paper"], "a4")
        self.assertEqual(manifest["expected_pages"], build.EXPECTED_PAGES)
        for slug, info in manifest["sheets"].items():
            with self.subTest(slug=slug):
                pdf = ROOT / "printables" / f"{slug}.pdf"
                self.assertTrue(pdf.is_file())
                self.assertEqual(pdf.stat().st_size, info["bytes"])

    def test_printables_readme_exists(self) -> None:
        self.assertTrue((ROOT / "printables" / "README.txt").is_file())


class ProjectMeta(unittest.TestCase):
    def test_license_has_exact_copyright_line(self) -> None:
        text = (ROOT / "LICENSE").read_text(encoding="utf-8")
        self.assertIn("Copyright (c) 2026 Asdale Dynamics, LLC", text)
        self.assertIn("MIT License", text)

    def test_readme_credits_llc(self) -> None:
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("Asdale Dynamics, LLC", text)

    def test_status_md_exists(self) -> None:
        self.assertTrue((ROOT / "STATUS.md").is_file())

    def test_no_secrets_in_repo_files(self) -> None:
        for path in sorted(ROOT.rglob("*")):
            if not path.is_file() or ".git" in path.parts:
                continue
            if path.suffix not in (".md", ".txt", ".py", ".css", ".html", ".cfg", ".toml", ".json"):
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            with self.subTest(file=str(path.relative_to(ROOT))):
                self.assertNotRegex(text, r"(?i)(api[_-]?key|secret[_-]?key|password\s*=)\s*[:=]")


if __name__ == "__main__":
    unittest.main()
