Free Pet Care Pack
==================

Printable, paper-first forms for every animal in the family: who they are,
when their shots come due, who feeds them, and the printed pieces you hope
you never need (a lost-pet flyer that's ready *before* it's needed). Made
with plain HTML/CSS, printed to PDF by one build script, kept entirely on
your own machine.

**Privacy in one sentence: nothing here touches the internet.** The sources
are offline-only HTML/CSS (no JavaScript, no web fonts, no external
resources), the templates ship blank (the build refuses phone-shaped or
microchip-shaped numbers in sources), and filled-in pages never need to
leave the house. No signups, no accounts, no app, no cloud — ever.

It's the paw-side companion to the Free Home Safety Pack, which walks the
same rooms for their humans.

## What's included

| File | Purpose |
|---|---|
| `printables/00-getting-started.pdf` | Warm one-page welcome: what's inside, ten-minute setup, printing notes |
| `printables/01-pet-profile.pdf` | Per-pet dossier: photo box, basics, quirks, routines, health basics, who-to-call |
| `printables/02-vet-visit-log.pdf` | Visit history plus vaccine-due rows ("next due" / "call and book by") |
| `printables/03-sitter-handoff-card.pdf` | Two cut-out cards: sitters get one, the fridge keeps one |
| `printables/04-feeding-schedule.pdf` | A week of bowls: portions, meds/extras, fed-and-water ticks |
| `printables/05-lost-pet-flyer.pdf` | Photo box, big name, safety line, tear-off call tabs |
| `printables/06-pet-safe-room-checklist.pdf` | Room-by-room walkthrough at nose height, tick-boxes included |
| `sheets/` | The HTML/CSS sources (one file per sheet + shared/shared.css) |
| `build.py` | The whole build: validate sources, render PDFs, write manifest |

Every content sheet ends with a warm "How to Use" page, so each PDF stands
on its own the moment it comes off the printer.

## How to run it

Requirements: Python 3.10+ and one PDF renderer — WeasyPrint (preferred:
deterministic, fully local) or a locally installed Chrome/Chromium (headless).
Both are auto-detected; the build never touches the network.

```sh
# build (or rebuild) every sheet into printables/
python3 build.py

# US Letter instead of default A4
python3 build.py --paper letter

# build only one sheet, into another folder
python3 build.py --only 02-vet-visit-log --out build/preview

# validate every source without rendering anything
python3 build.py --validate-only

# run the test suite (freshly builds all sheets and verifies the committed PDFs)
python3 -m unittest discover -s tests -v
```

No pip packages are required to build (`pypdf` is optional; the tests fall
back to raw PDF checks without it, though you'll want it for the full page
count tests).

## What the build verifies

* Sources: doctype/charset present, no external URLs (the offline
  guarantee), no branding in sheet text, exact page and guide-page counts.
* Privacy: no phone-like patterns, no microchip-style digit runs, a strict
  digit budget in printable text — the templates ship blank by construction.
* Structure: two handoff cards plus a cut line, a mon–sun feeding week in
  order, nine tear-off tabs with call lines, six unique pet-safe rooms with
  at least five checkbox items each, and a getting-started page that lists
  the whole pack.
* PDFs: valid header/trailer, expected page counts, brand-free bytes, and
  "How to Use" text on each final page (via pypdf when available).

## Layout of the project

```
build.py      print-to-PDF build script (validators, renderer picking, manifest)
sheets/       one HTML source per sheet (+ shared/shared.css)
printables/   the generated PDFs + printing README + build manifest
tests/        ctypes-free unittest suite (no external test deps)
```

## Design notes

* A4 is the default; `--paper letter` re-renders the same layouts for
  US Letter by injecting an @page override.
* All decorations (paw prints, checkboxes, photo boxes, tear-off tabs) are
  pure CSS — no images, no fonts to download, prints fine in black & white.
* Renderer order: WeasyPrint first (deterministic), then headless Chrome
  (probed; process-group killed on timeouts — some sandboxes hang headless
  Chromium indefinitely). Set `PRINT_RENDERER=weasyprint` or `chrome` to pin.

## License & credit

MIT — see `LICENSE` (`Copyright (c) 2026 Asdale Dynamics, LLC`).

Published by **Asdale Dynamics, LLC**: beginner-friendly manuals, open-source
tools and practical print-at-home helpers. Home use of this pack is always
free — copy, print and share it.
