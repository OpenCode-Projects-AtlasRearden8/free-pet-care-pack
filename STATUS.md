# STATUS — Free Pet Care Pack

Built and verified locally. Last full check: 2026-10-26.

## What was built

A local-first, print-at-home pack of six fill-in printable sheets for the
family's animals, plus a warm getting-started page. Sources are plain
HTML/CSS; one build script (`build.py`) validates every source and renders
brand-free PDFs into `printables/`. Nothing touches the network; the
templates ship blank (validators refuse phone-shaped / microchip-shaped
digit patterns), and each content PDF ends with its own warm "How to Use"
page.

| File (in `printables/`) | What it is |
|---|---|
| `00-getting-started.pdf` | Warm one-page welcome: what's inside, ten-minute setup, printing notes |
| `01-pet-profile.pdf` | Per-pet dossier: photo box, basics, loves/worries/quirks, routines, health basics, who-to-call |
| `02-vet-visit-log.pdf` | Eight visit rows + seven vaccine-due rows ("next due" / "call and book by") |
| `03-sitter-handoff-card.pdf` | Two fold-out handoff cards (one for the sitter, one for the fridge) with cut line |
| `04-feeding-schedule.pdf` | Mon–Sun feeding grid: portions, meds/extras, fed/water ticks, initials |
| `05-lost-pet-flyer.pdf` | Photo box, big name line, don't-chase safety note, nine tear-off call tabs |
| `06-pet-safe-room-checklist.pdf` | Six pet-safe rooms × five tick-box hazards + an outside reminder |

Supporting files: `build.py` (validate → render → manifest), `sheets/`
(HTML/CSS sources + `shared/shared.css`), `tests/` (35-test suite),
`README.md`, `LICENSE` (MIT), `printables/README.txt` + `manifest.json`.

## How to run it

```sh
python3 build.py                       # build all sheets into printables/ (A4)
python3 build.py --paper letter        # US Letter override
python3 build.py --only 01-pet-profile # one sheet only
python3 build.py --validate-only       # validate sources, render nothing
python3 -m unittest discover -s tests  # full test suite
```

Requirements: Python 3.10+ and one renderer. WeasyPrint is preferred
(auto-detected); headless Chrome/Chromium is the fallback (probed, with
process-group kills for sandbox hangs). `PRINT_RENDERER=weasyprint|chrome`
pins it. No pip installs needed to build; `pypdf` is optional (used by some
tests for page/text checks).

## Verification results

* `python3 build.py --validate-only` — all 7 sources valid (structure,
  offline URLs, brand-free, privacy digit scan).
* `python3 build.py` — 7/7 PDFs, 13 pages total, all at expected page
  counts; renderer: WeasyPrint; manifest + README written to
  `printables/`.
* `python3 -m unittest discover -s tests` — 35/35 tests pass. Covers:
  every source exists/validates, offline + no external URLs + no
  `<script>`, brand-free sources, privacy guards (phone/microchip/digit
  budget, plus mutation tests proving the guards raise), per-sheet
  structure (counts, ordering, tabs, cards, rooms) with mutation tests,
  an end-to-end fresh build with PDF header/`%%EOF`/page-count/text
  checks, the committed `printables/` set (valid, brand-free,
  manifest-matching), and project meta (exact LICENSE copyright line,
  README credit, STATUS presence, basic secret-pattern scan).
* Visual pass of all printed pages via rendered previews: grids, tables,
  write-in lines, checkboxes, paws, tear-off tabs and guide pages render
  cleanly (after fixing WeasyPrint flex quirks — checklist columns were
  converted to floats and the flyer photo row to a nested table).

## Known gaps / notes

* Pages were visually audited page-by-page on A4; US Letter builds are
  verified by page-count equality (13 pages, same as A4) and blank-spill
  scans, not eyeballed page by page.
* Renderer is WeasyPrint-first; headless-Chrome output is not
  byte-identical, so rebuild with one renderer per release (manifest
  records which was used).
* `printables/` PDFs are committed and re-verified against
  `manifest.json` by the tests, so a fresh clone is testable offline even
  without a renderer.
* Parent pack "free-home-safety-pack" is referenced by name in copy but
  is not linked (no URLs anywhere — the pack stays fully offline).
* Forms are deliberately simple (no JS, no PDF form fields): they're for
  pen-on-paper. Screen-filling was intentionally out of scope.
