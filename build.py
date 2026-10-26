#!/usr/bin/env python3
"""build.py — print-to-PDF build script for the Free Pet Care Pack.

Renders every sheet in sheets/ into a brand-free PDF ready for printing
(defaults to printables/). Runs fully offline: the only inputs are local
HTML/CSS sources and locally installed system fonts. Nothing leaves the
home — the sheets carry no JavaScript, no web fonts and no remote URLs.

Usage:
  python3 build.py                     # build every sheet to printables/
  python3 build.py --paper letter      # US Letter instead of A4
  python3 build.py --only 02-vet-visit-log
  python3 build.py --validate-only     # validate sources, render nothing
  python3 build.py --list              # list sheet slugs

Renderer ('auto' default): WeasyPrint is preferred (deterministic, fully
local); headless Chrome/Chromium is probed and used when WeasyPrint is
unavailable or fails. Sources are validated — offline URLs, brand-free
text, no personal-data digits (the templates ship blank), and per-sheet
structure — before any PDF is written.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SHEETS_DIR = ROOT / "sheets"
SHEETS = [
    "00-getting-started",
    "01-pet-profile",
    "02-vet-visit-log",
    "03-sitter-handoff-card",
    "04-feeding-schedule",
    "05-lost-pet-flyer",
    "06-pet-safe-room-checklist",
]
GUIDE_PAGES = {
    "00-getting-started": 0,
    "01-pet-profile": 1,
    "02-vet-visit-log": 1,
    "03-sitter-handoff-card": 1,
    "04-feeding-schedule": 1,
    "05-lost-pet-flyer": 1,
    "06-pet-safe-room-checklist": 1,
}
EXPECTED_PAGES = {
    "00-getting-started": 1,
    "01-pet-profile": 2,
    "02-vet-visit-log": 2,
    "03-sitter-handoff-card": 2,
    "04-feeding-schedule": 2,
    "05-lost-pet-flyer": 2,
    "06-pet-safe-room-checklist": 2,
}
BUILD_TMP = ROOT / "build"
FORBIDDEN_STRINGS = ("asdale", "dynamics", "dylan")  # sheets stay brand-free

PRINTABLES_README = """Free Pet Care Pack — family printables for the animals
=======================================================

Ready-to-print PDFs. Nothing here needs a screen, a signup or an internet
connection once you have the file on paper — and nothing in these files
knows anything about you: they ship blank, ready for your pencil.

What is in this folder
----------------------

  00-getting-started.pdf            start here: what's inside, a ten-minute setup plan
  01-pet-profile.pdf                one-page dossier per animal (photo, quirks, vet basics)
  02-vet-visit-log.pdf              visit history + vaccine-due rows ("call and book by")
  03-sitter-handoff-card.pdf        two cut-out cards: one for the sitter, one for the fridge
  04-feeding-schedule.pdf           a week of bowls with fed/water tick-boxes
  05-lost-pet-flyer.pdf             photo box, big name, tear-off call tabs
  06-pet-safe-room-checklist.pdf    room-by-room walkthrough at pet height
  manifest.json                     build record (paper size, renderer, page counts)

How to print
------------

* Choose "Actual size" or 100% scale — no scaling fits either paper.
* Turn OFF "headers and footers" / "fit to page" in the print dialog.
* Black & white is fine: every sheet is designed to work without colour.
* Paper: the files are built for A4; rebuild for US Letter from the project
  root with `python3 build.py --paper letter`.
* The starter sheet suggests a folder; the sitter card wants scissors and
  the flyer tabs do too. Everything else prints as-is.

Reprinting one sheet? Use its number: `python3 build.py --only 01-pet-profile`.

Made warmly, for the whole family — human and otherwise. Copy freely at
home; the sheets themselves carry no branding.
"""

# Personal-data guards: the printed templates must ship blank. No phone-like
# patterns, no microchip-style long digit runs, and at most a dozen stray
# digits anywhere in the printable body text (CSS sizes are excluded).
_PHONE_RE = re.compile(r"\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}")
_LONGNUM_RE = re.compile(r"\d{9,}")


class BuildError(Exception):
    """A source sheet or the environment fails validation."""


# ---------------------------------------------------------------------------
# Source validation
# ---------------------------------------------------------------------------


def body_text(source: str) -> str:
    """Strip <style> blocks and tags; return visible text (for digit scans)."""
    text = re.sub(r"<style\b.*?</style>", " ", source, flags=re.S | re.I)
    text = re.sub(r"<head\b.*?</head>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def validate_no_personal_digits(slug: str, source: str) -> None:
    low = body_text(source)
    if _PHONE_RE.search(low):
        raise BuildError(
            f"{slug}: phone-like number found — templates ship blank, write-in lines stay empty"
        )
    if _LONGNUM_RE.search(low):
        raise BuildError(
            f"{slug}: long digit run found (microchip-like) — templates stay blank"
        )
    digits = len(re.findall(r"\d", low))
    if digits > 12:
        raise BuildError(
            f"{slug}: {digits} stray digits in printable text (budget 12) — write numbers by hand, not in the source"
        )


def fail_unless(cond: bool, msg: str) -> None:
    if not cond:
        raise BuildError(msg)


_ENTS = {
    "&rsquo;": "'", "&amp;": "&", "&mdash;": "\u2014", "&middot;": "\u00b7",
    "&ldquo;": "\u201c", "&rdquo;": "\u201d", "&hellip;": "\u2026", "&nbsp;": " ",
}


def _decode_entities(text: str) -> str:
    for k, v in _ENTS.items():
        text = text.replace(k, v)
    # numeric entities like &#9986; carry no semantic checks — drop them
    return re.sub(r"&#\d+;", " ", text)


def _require_substrings(slug: str, text: str, needles: list[str]) -> None:
    low = re.sub(r"\s+", " ", _decode_entities(text.lower()))
    missing = [n for n in needles if n not in low]
    if missing:
        raise BuildError(f"{slug}: missing required content: {missing}")


def _require_counts(slug: str, text: str, rules: dict[str, tuple[int, int]]) -> None:
    """rules maps a regex to (min, max) accepted occurrences (inclusive)."""
    for pattern, (lo, hi) in rules.items():
        count = len(re.findall(pattern, text, flags=re.I))
        if not (lo <= count <= hi):
            raise BuildError(f"{slug}: pattern {pattern!r} matched {count}x, expected {lo}–{hi}")


def validate_sheet(slug: str, source: str) -> None:
    """Structural validation for one sheet's raw HTML text.

    Called for every real source and directly by the mutation tests.
    """
    low_all = source.lower()
    fail_unless("<!doctype html" in low_all[:200], f"{slug}: missing <!doctype html>")
    fail_unless("charset" in low_all[:400], f"{slug}: missing <meta charset>")
    fail_unless(
        not re.search(r"https?://", low_all),
        f"{slug}: external URL found — the pack must build offline",
    )
    for needle in FORBIDDEN_STRINGS:
        fail_unless(needle not in low_all, f"{slug}: stays brand-free, but {needle!r} appears")

    flat = re.sub(r"\s+", " ", low_all)
    pages = flat.count('<section class="page')
    guides = flat.count('class="page guide')
    fail_unless(
        pages == EXPECTED_PAGES[slug], f"{slug}: expected {EXPECTED_PAGES[slug]} pages, found {pages}"
    )
    fail_unless(guides == GUIDE_PAGES[slug], f"{slug}: expected exactly {GUIDE_PAGES[slug]} guide page(s)")
    validate_no_personal_digits(slug, source)

    if slug == "00-getting-started":
        _require_substrings(slug, source, [
            "start here", "what's inside", "stays at home",
            "pet profile", "vet-visit log", "sitter handoff card",
            "feeding schedule", "lost-pet flyer", "pet-safe room",
        ])
        _require_counts(slug, source, {r'class="paw"': (1, 12)})

    elif slug == "01-pet-profile":
        _require_substrings(slug, source, [
            "tape a photo", "pet's name", "breed", "weight",
            "microchip", "allergies", "loves", "worries", "quirks", "vet",
        ])
        _require_counts(slug, source, {
            r'class="photo-box"': (1, 1),
            r'class="wline"': (8, 60),
        })

    elif slug == "02-vet-visit-log":
        _require_substrings(slug, source, ["next due", "given", "vaccine", "clinic"])
        _require_counts(slug, source, {
            r'class="visit-row"': (8, 8),
            r'class="vac-row"': (7, 7),
        })

    elif slug == "03-sitter-handoff-card":
        _require_substrings(slug, source, ["vet", "phone", "cut"])
        _require_counts(slug, source, {
            r'class="handoff-card"': (2, 2),
            r'class="cut-line"': (1, 1),
        })

    elif slug == "04-feeding-schedule":
        _require_substrings(slug, source, ["fresh water", "treats"])
        days = re.findall(r'data-day="([a-z]{3})"', source)
        fail_unless(
            days == ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
            f"{slug}: feeding rows must be one week mon..sun in order, found {days}",
        )

    elif slug == "05-lost-pet-flyer":
        _require_substrings(slug, source, ["lost", "don't chase", "photo here"])
        _require_counts(slug, source, {
            r'class="photo-box"': (1, 1),
            r'class="tl"': (9, 9),
        })
        # Every tear-off tab carries a blank call: line (privacy + usefulness).
        tabs = re.findall(r'class="tab"[^>]*>(.*?)</span>', source, flags=re.S)
        for tab in tabs:
            fail_unless("call" in tab.lower(), f"{slug}: tear-off tab without a call line")

    elif slug == "06-pet-safe-room-checklist":
        rooms = re.findall(r'data-room="([a-z-]+)"', source)
        fail_unless(len(rooms) == 6, f"{slug}: expected 6 room groups, found {len(rooms)}")
        fail_unless(
            len(set(rooms)) == 6, f"{slug}: room groups must have unique data-room values"
        )
        for room in rooms:
            block = re.search(
                rf'data-room="{room}"(.*?)<!-- /room -->', source, flags=re.S
            )
            fail_unless(block is not None, f"{slug}: room {room!r} has no closing marker")
            items = re.findall(r'class="cb"', block.group(1))
            fail_unless(
                len(items) >= 5, f"{slug}: room {room!r} has {len(items)} checklist items, need >= 5"
            )
        total = len(re.findall(r'class="cb"', source))
        fail_unless(total >= 30, f"{slug}: expected >= 30 checkboxes, found {total}")


def validate_source(slug: str) -> int:
    """Validate sheets/<slug>.html; returns its expected page count."""
    path = SHEETS_DIR / f"{slug}.html"
    if not path.is_file():
        raise BuildError(f"{slug}: source missing ({path})")
    text = path.read_text(encoding="utf-8")
    validate_sheet(slug, text)
    return EXPECTED_PAGES[slug]


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------


def find_chrome() -> str | None:
    exe = os.environ.get("CHROME_BIN") or os.environ.get("CHROME_PATH")
    if not exe:
        for cand in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome"):
            found = shutil.which(cand)
            if found:
                exe = found
                break
    if not exe:
        mac = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
        exe = str(mac) if mac.is_file() else None
    if exe and not Path(exe).exists() and shutil.which(exe):
        exe = shutil.which(exe)
    return exe


def find_weasyprint() -> list[str] | None:
    exe = shutil.which("weasyprint")
    if exe:
        return [exe]
    try:
        import weasyprint  # noqa: F401

        return [sys.executable, "-m", "weasyprint"]
    except ImportError:
        return None


def _paper_src(src: Path, paper: str) -> Path:
    """For letter paper, inject an @page override (default sources are A4).

    The temp copy is written NEXT TO the original source so that relative
    resources (shared/shared.css) resolve for both renderers.
    """
    if paper == "a4":
        return src
    if paper != "letter":
        raise BuildError(f"unknown paper: {paper}")
    text = src.read_text(encoding="utf-8")
    override = '<style>/* build: paper override */\n@page { size: 8.5in 11in; margin: 11mm 12mm; }</style>\n</head>'
    if "</head>" not in text:
        raise BuildError(f"{src.name}: no </head> to inject paper override into")
    out = src.with_name(f".{src.stem}-letter.html")
    out.write_text(text.replace("</head>", override, 1), encoding="utf-8")
    return out


def _run_with_group_kill(cmd: list[str], timeout: int, err_file: Path) -> tuple[bool, str]:
    """Run a renderer; on timeout kill the WHOLE process group.

    Plain subprocess.run(timeout=...) deadlocks forever on headless chrome:
    its forked children keep the stderr pipe open after the main process is
    killed. With start_new_session + killpg every fork dies and the pipe
    closes.
    """
    import contextlib

    err = ""
    ehandle = open(err_file, "w", encoding="utf-8")
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=ehandle,
            start_new_session=True,
        )
        try:
            code = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            with contextlib.suppress(OSError):
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            with contextlib.suppress(Exception):
                proc.wait(timeout=15)
            return False, "timed out"
    except OSError as exc:
        return False, str(exc)
    finally:
        ehandle.close()
        with contextlib.suppress(Exception):
            err = err_file.read_text(encoding="utf-8", errors="replace")[-800:]
    return code == 0, err


def render_chrome(chrome: str, src: Path, out_pdf: Path, tmp_root: Path) -> None:
    tmp_root.mkdir(parents=True, exist_ok=True)
    profile = tmp_root / ".chrome-profile"
    profile.mkdir(parents=True, exist_ok=True)
    err_file = tmp_root / "chrome-stderr.log"
    common = [
        chrome,
        "--no-sandbox",
        "--disable-gpu",
        "--disable-dev-shm-usage",
        "--disable-background-networking",
        "--disable-component-update",
        "--disable-default-apps",
        "--disable-extensions",
        "--disable-sync",
        "--mute-audio",
        "--no-first-run",
        "--user-data-dir=" + str(profile),
        "--virtual-time-budget=3000",
    ]
    attempts = [
        ["--headless", "--no-pdf-header-footer"],
        ["--headless", "--print-to-pdf-no-header"],
    ]
    last_err = ""
    for extra in attempts:
        if out_pdf.exists():
            out_pdf.unlink()
        cmd = common + extra + [f"--print-to-pdf={out_pdf.resolve()}", src.resolve().as_uri()]
        ok, err = _run_with_group_kill(cmd, 120, err_file)
        if ok and out_pdf.exists() and out_pdf.stat().st_size > 2000:
            return
        last_err = err
    raise BuildError(f"Chrome could not render {src.name}: {last_err or 'no output produced'}")


def render_weasyprint(cmd: list[str], src: Path, out_pdf: Path) -> None:
    try:
        proc = subprocess.run(cmd + [str(src), str(out_pdf)], capture_output=True, text=True, timeout=300)
        err = (proc.stderr or "")[-800:]
        if proc.returncode != 0 or not out_pdf.exists() or out_pdf.stat().st_size < 2000:
            raise BuildError(f"WeasyPrint could not render {src.name}: {err or 'no output produced'}")
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise BuildError(f"WeasyPrint failed on {src.name}: {exc}") from exc


def count_pdf_pages(path: Path) -> int:
    try:
        from pypdf import PdfReader

        return len(PdfReader(str(path)).pages)
    except Exception:
        data = path.read_bytes()
        counts = [int(x) for x in re.findall(rb"/Type\s*/Pages[^>]*?/Count\s+(\d+)", data, re.S)]
        typed = len(re.findall(rb"/Type\s*/Page(?![s])", data))
        return max(counts + [typed, 1])


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------


def build_sheet(slug: str, out_dir: Path, paper: str, render_fn, label: str) -> dict:
    src = SHEETS_DIR / f"{slug}.html"
    validate_source(slug)
    src = _paper_src(src, paper)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_pdf = out_dir / f"{slug}.pdf"

    try:
        render_fn(src, out_pdf)
    finally:
        if str(src) != str(SHEETS_DIR / f"{slug}.html"):
            src.unlink(missing_ok=True)
    pages = count_pdf_pages(out_pdf)
    data = out_pdf.read_bytes()
    return {
        "slug": slug,
        "renderer": label,
        "pages": pages,
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest()[:12],
    }


def make_renderer(name: str, tmp_root: Path) -> tuple[callable, str]:
    """Resolve a renderer name into (render(src, out_pdf), label).

    'auto' prefers WeasyPrint (deterministic, immune to headless-Chromium
    hangs in sandboxed environments) and falls back to Chrome on failure or
    when WeasyPrint is absent. PRINT_RENDERER env pins it either way.
    """
    if name == "chrome":
        chrome = find_chrome()
        if not chrome:
            raise BuildError("Chrome/Chromium not found on PATH")
        return (lambda src, out: render_chrome(chrome, src, out, tmp_root)), "chrome"
    if name == "weasyprint":
        cmd = find_weasyprint()
        if not cmd:
            raise BuildError("WeasyPrint not found")
        return (lambda src, out: render_weasyprint(cmd, src, out)), "weasyprint"
    if name == "auto":
        forced = os.environ.get("PRINT_RENDERER", "").strip().lower()
        if forced in ("chrome", "weasyprint"):
            return make_renderer(forced, tmp_root)
        cmd = find_weasyprint()
        chrome = find_chrome()

        def auto_render(src: Path, out: Path) -> None:
            last: Exception | None = None
            if cmd:
                try:
                    render_weasyprint(cmd, src, out)
                    return
                except BuildError as exc:
                    last = exc
            if chrome:
                try:
                    render_chrome(chrome, src, out, tmp_root)
                    return
                except BuildError as exc:
                    last = exc
            raise last or BuildError("no usable renderer found")

        return auto_render, "auto"
    raise BuildError(f"unknown renderer {name!r}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build the free pet care pack.")
    ap.add_argument("--paper", choices=["a4", "letter"], default="a4", help="paper size (default: a4)")
    ap.add_argument("--out", default="printables", help="output directory (default: printables/)")
    ap.add_argument("--only", nargs="*", default=None, help="build only these sheet slugs")
    ap.add_argument("--renderer", choices=["auto", "chrome", "weasyprint"], default="auto")
    ap.add_argument("--validate-only", action="store_true", help="validate sources, render nothing")
    ap.add_argument("--list", action="store_true", help="list sheet slugs")
    args = ap.parse_args(argv)

    if args.list:
        print("\n".join(SHEETS))
        return 0

    selected = SHEETS if args.only is None or args.only == [] else list(args.only)
    unknown = [s for s in selected if s not in SHEETS]
    if unknown:
        print(f"Unknown sheet(s): {', '.join(unknown)}", file=sys.stderr)
        print(f"Known slugs: {', '.join(SHEETS)}", file=sys.stderr)
        return 2

    out_dir = Path(args.out).resolve() if not Path(args.out).is_absolute() else Path(args.out)

    print(f"Validating sources … ({len(selected)} sheet(s))")
    page_expect = {}
    try:
        for slug in selected:
            page_expect[slug] = validate_source(slug)
    except BuildError as exc:
        print(f"VALIDATION FAILED: {exc}", file=sys.stderr)
        return 3
    if args.validate_only:
        print("All sources valid. (validate-only mode, no PDFs written)")
        return 0

    tmp_root = BUILD_TMP
    try:
        mkrender, used_label = make_renderer(args.renderer, tmp_root)
    except BuildError as exc:
        print(f"NO RENDERER: {exc}", file=sys.stderr)
        return 4

    results = []
    try:
        for slug in selected:
            info = build_sheet(slug, out_dir, args.paper, mkrender, used_label)
            results.append((slug, info))
            print(f"  built {slug:>26}  [{used_label}]  {info['pages']} pages  "
                  f"{info['bytes'] // 1024} KB", flush=True)
    except BuildError as exc:
        print(f"BUILD FAILED: {exc}", file=sys.stderr)
        return 4

    used_renderers = sorted({i["renderer"] for _, i in results})
    manifest = {
        "paper": args.paper,
        "renderer": args.renderer,
        "renderers_used": used_renderers,
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sheets": {slug: info for slug, info in results},
        "expected_pages": page_expect,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (out_dir / "README.txt").write_text(PRINTABLES_README, encoding="utf-8")

    total_pages = sum(i["pages"] for _, i in results)
    print(f"\nDone. {len(results)} PDF(s), {total_pages} pages, "
          f"paper={args.paper}, renderers={'+'.join(used_renderers)}.")
    print(f"Output: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
