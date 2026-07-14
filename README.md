# EPUB → Markdown / HTML Converter — Technical Guide

Two Python tools that convert EPUB books while preserving images, formatting, and
reading order, with strong support for Japanese EPUBs (gaiji markers, gothic/gfont
emphasis, sesame dots).

- **`epub_to_markdown.py`** → a combined **Markdown** file (`<book>.md`)
- **`epub_to_html.py`** → a single clean, self-styled **HTML** file (`<book>.html`)

Both tools share the same EPUB parser, the same command-line options, and the same
output layout. Every example works with either — just swap the script name.

> **New here? Read `QUICKSTART.md` first** for copy-paste commands. This document
> covers installation, every option, and advanced usage.

---

## 1. Install

This project uses [uv](https://docs.astral.sh/uv/). Dependencies are declared in
`pyproject.toml`; you don't install them by hand.

### Step 1 — install uv (once)

```bash
brew install uv                                   # macOS
# or, any platform:
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### Step 2 — create the environment

From the project folder:

```bash
uv sync --extra full     # creates .venv, fetches Python ≥3.9, installs everything
```

Plain `uv sync` installs only the minimum (no image auto-scaling / encoding fallback).

| Package          | Required?                     | Purpose                                |
| ---------------- | ----------------------------- | -------------------------------------- |
| `beautifulsoup4` | **required** (both tools)     | HTML/XML parsing                       |
| `html2text`      | **required** (Markdown tool)  | Markdown conversion                    |
| `chardet`        | optional (`full` extra)       | Encoding-detection fallback            |
| `Pillow`         | optional (`full` extra)       | Image dimensions for `--auto-scale`    |

> The HTML tool needs only `beautifulsoup4` (plus optional `Pillow`); it does **not**
> need `html2text`.

### Step 3 — run

`uv run` executes a script inside the managed environment (no manual activation):

```bash
uv run epub_to_markdown.py [options] [epub_file_or_dir ...]   # → Markdown
uv run epub_to_html.py     [options] [epub_file_or_dir ...]   # → HTML
```

Prefer a plain `python3`? Activate the environment once, then drop the `uv run`:

```bash
source .venv/bin/activate
python3 epub_to_markdown.py [options] [epub_file_or_dir ...]
```

Commands that use `--auto-scale` need the `full` extra. With an activated `.venv`
(step 2 used `--extra full`) it just works; with `uv run` on a minimal env, add the
extra: `uv run --extra full epub_to_html.py … --auto-scale`.

---

## 2. Usage & input modes

```bash
uv run epub_to_markdown.py [options] [epub_file_or_dir ...]
uv run epub_to_html.py     [options] [epub_file_or_dir ...]
```

How the tool interprets what you pass:

| You pass…                          | It does…                                                      |
| ---------------------------------- | ------------------------------------------------------------ |
| **nothing**                        | Converts every `*.epub` in the **current** folder (not recursive) |
| **one `.epub` file**               | Converts that book                                           |
| **several `.epub` files**          | Converts each one                                            |
| **a folder** *(no `.epub` suffix)* | Treats it as a single **already-extracted** EPUB directory   |

### Converting a whole folder of books — the important detail

Passing a *folder name* does **not** batch the EPUBs inside it (the tool reads it as
one unzipped book). To convert every book in a folder, let your **shell expand a glob**
so each file arrives as its own argument:

```bash
uv run epub_to_markdown.py epub_input/*.epub --output-dir converted
uv run epub_to_html.py     path/to/books/*.epub --output-dir converted
```

Each matched `.epub` becomes its own subfolder under `converted/`.

---

## 3. Options

Both tools accept the same options:

| Option                 | Description                                             | Default           |
| ---------------------- | ------------------------------------------------------- | ----------------- |
| `--zoom PERCENT`       | Image display size, 1–100                               | `100`             |
| `--include-titlepage`  | Include the titlepage in output                         | skipped           |
| `--split-chapters`     | Also export per-chapter files into `chapters/`          | disabled          |
| `--output-dir DIR`     | Where all book subfolders are written                   | current directory |
| `--auto-scale [WIDTH]` | Downscale wide images to max `WIDTH` px. Needs `Pillow`. | disabled (WIDTH `800` when the flag is given without a value) |
| `-h`, `--help`         | Show help and exit                                      | —                 |

**Image sizing precedence** when `--auto-scale` is active:

1. Gaiji (inline symbols) → `height: 1em` (always)
2. Explicit HTML sizing on the image → preserved as-is
3. Auto-scale → images wider than `WIDTH` capped to it
4. Small images (≤ `WIDTH`) → left untouched

`--zoom` is a display-percentage applied on top; `--auto-scale` changes the pixel cap.

---

## 4. Output structure

Both tools produce the same layout — only the document extension differs:

```
<output-dir>/                     # cwd, or whatever --output-dir points to
└── <book>/                       # one subfolder per book, created automatically
    ├── <book>.md   OR  <book>.html   # the complete document
    ├── chapters/                     # only with --split-chapters
    │   ├── 01_introduction.(md|html)
    │   ├── 02_chapter_one.(md|html)
    │   └── ...
    └── images/                       # every image from the book
        ├── cover.jpg
        └── figure1.png
```

The `<book>.html` is fully self-contained (the stylesheet is embedded); each split
chapter is a standalone, styled page. Image references use `images/…`
(or `../images/…` from inside `chapters/`).

---

## 5. What gets converted

- All text content, in reading order
- All images (copied into `images/`; duplicate names are disambiguated path-aware, so
  same-named images in different EPUB folders don't collide)
- Book metadata (title, author, publisher, date)
- Headings and document structure
- **Bold** (incl. `.bold`, `.gothic`, `.gfont` classes), *italic* (incl. gaiji markers
  such as `tm2.png` / `tu2.png`)
- Underline, subscript, superscript, strikethrough, highlight, small text
- Tables, and lists (respects CSS `list-style-type: none`)
- Multiple text encodings — UTF-8, Shift-JIS, EUC-JP, GB2312, Big5, Latin-1, … (honors
  the file's declared encoding, with a `chardet` fallback when the `full` extra is present)

### Markdown vs. HTML — which to pick

|                    | `epub_to_markdown.py`                       | `epub_to_html.py`                                    |
| ------------------ | ------------------------------------------- | ---------------------------------------------------- |
| Output             | `<book>.md`                                 | `<book>.html` (self-contained, styled)               |
| Best for           | editing, diffing, pipelines, other tools    | reading in a browser, printing to PDF                |
| Styling            | plain Markdown                              | built-in stylesheet: responsive, light/dark, CJK fonts |
| Inline formatting  | bold/italic/code (sub·sup·underline·strike·mark kept as raw HTML) | native `<u>`/`<sub>`/`<sup>`/`<del>`/`<mark>`/`<small>` |
| Extra dependency   | `html2text`                                 | none beyond `beautifulsoup4`                         |

The HTML converter reuses the Markdown tool's content normalization, then writes clean
HTML directly instead of round-tripping through `html2text`: CSS classes become real
semantic tags, presentational noise (`class`, `id`, `xmlns`, vendor wrappers like Kobo's
per-sentence spans) is stripped while `src`/`href`/`alt`/`style` and table structure are
kept, `<script>` is removed, and SVG cover pages become plain `<img>`.

---

## 6. Advanced examples

```bash
# Batch a folder → Markdown, into ./converted, 70% image size, per-chapter files
uv run epub_to_markdown.py epub_input/*.epub \
    --output-dir converted --zoom 70 --split-chapters

# One book → HTML, cap wide images at 600px (needs Pillow / full extra)
uv run --extra full epub_to_html.py "epub_input/My Book.epub" \
    --output-dir converted --auto-scale 600

# Everything in the current folder → HTML, keeping titlepages
uv run epub_to_html.py --include-titlepage

# Re-process an already-extracted EPUB directory (mode 4)
uv run epub_to_markdown.py path/to/unzipped_book_dir --output-dir converted
```

---

## 7. Troubleshooting

**`uv: command not found`**
uv isn't installed — see step 1.

**`No EPUB files found`**
You ran with no filenames and the current folder has no `.epub`. Pass files explicitly,
e.g. `uv run epub_to_markdown.py epub_input/*.epub`.

**A folder "converts" as one weird book, or nothing happens**
You passed a bare folder name (interpreted as one extracted EPUB). Use `folder/*.epub`.

**`ModuleNotFoundError: No module named 'bs4'` (or `html2text`)**
Dependencies aren't set up, or you're outside the environment:
```bash
uv sync --extra full
uv run epub_to_markdown.py ...        # or: source .venv/bin/activate
```

**`--auto-scale` seems ignored**
It needs `Pillow`. Use the `full` extra: `uv run --extra full … --auto-scale`.

**Images not displaying**
Keep `images/` next to the document: `book/book.(md|html)` + `book/images/`.

**Corrupted / non-standard EPUB**
Open it in an EPUB reader to confirm it's valid, and check it has a
`META-INF/container.xml`.

---

## 8. Optional: short `epub2markdown` / `epub2html` commands

`pyproject.toml` already declares console entry points, but installing them needs a
build backend. Add this to `pyproject.toml`:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
include = ["epub_to_markdown.py", "epub_to_html.py"]
```

Then `uv sync --extra full` and use `uv run epub2markdown …` / `uv run epub2html …`.

---

## License

MIT
