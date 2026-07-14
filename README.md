# EPUB to Markdown / HTML Converter

Two Python tools that convert EPUB files while preserving images, formatting, and content structure — with strong support for Japanese EPUBs (gaiji markers, gothic/gfont emphasis, sesame dots).

- **`epub_to_markdown.py`** → a combined **Markdown** file (`<book>.md`)
- **`epub_to_html.py`** → a single clean, self-styled **HTML** file (`<book>.html`)

Both tools share the same EPUB parsing, the same command-line options, and the same output layout — pick whichever format you want. Every example below works with either tool: just swap the script name.

## Features

- **Two output formats**: Markdown (`epub_to_markdown.py`) or self-styled HTML (`epub_to_html.py`)
- **Auto-discovery**: Automatically finds and converts all EPUB files in a directory
- **Preserves formatting**: Bold, italic, underline, subscript/superscript, strikethrough, highlight, tables, lists, headings, blockquotes, code
- **Japanese EPUB support**: Handles gaiji markers, gothic/gfont emphasis, sesame dots
- **Smart list handling**: Respects CSS `list-style-type: none` for bullet lists
- **Automatic extraction**: No need to manually unzip EPUB files
- **Duplicate handling**: Renames duplicate images automatically — path-aware, so same-named images in different folders don't get cross-wired
- **Multiple encodings**: UTF-8, Shift-JIS, EUC-JP, GB2312, Big5, Latin-1, etc. (honors the file's declared encoding)
- **HTML extras**: clean built-in stylesheet (responsive, light/dark, CJK-friendly fonts), native semantic tags, and stripped-down markup

## Markdown vs. HTML — which to use?

|  | `epub_to_markdown.py` | `epub_to_html.py` |
|---|---|---|
| Output | `<book>.md` | `<book>.html` (self-contained, styled) |
| Best for | editing, diffing, static-site pipelines, feeding to other tools | reading in a browser, printing to PDF, faithful formatting |
| Styling | plain Markdown | clean built-in stylesheet (light/dark, responsive) |
| Inline formatting | bold/italic/code (underline·sub·sup·strike·mark kept as raw HTML) | native `<u>`/`<sub>`/`<sup>`/`<del>`/`<mark>`/`<small>` |
| Extra dependency | `html2text` | none beyond `beautifulsoup4` |

Both accept identical options and produce the same folder layout (`<book>/` with the document, `images/`, and optional `chapters/`).

## Installation

This project uses [uv](https://docs.astral.sh/uv/) for dependency management. Dependencies are declared in `pyproject.toml`.

### 1. Install uv

```bash
brew install uv          # macOS
# or: curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 2. Install dependencies

From the project folder:

```bash
uv sync --extra full     # creates .venv, fetches Python ≥3.9, installs everything
```

Use plain `uv sync` (without `--extra full`) for the minimum install.

| Package | Required? | Purpose |
|---------|-----------|---------|
| `beautifulsoup4` | required (both tools) | HTML/XML parsing |
| `html2text` | required (Markdown tool only) | Markdown conversion |
| `chardet` | optional (`full` extra) | Encoding-detection fallback |
| `Pillow` | optional (`full` extra) | Image dimensions for `--auto-scale` |

> The HTML tool needs only `beautifulsoup4` (plus optional `Pillow`); it does **not** require `html2text`.

### 3. Run

Prefix the commands in this guide with `uv run`:

```bash
uv run python epub_to_markdown.py [options] [epub_file...]   # -> Markdown
uv run python epub_to_html.py     [options] [epub_file...]   # -> HTML
```

Or activate the environment once and drop the prefix:

```bash
source .venv/bin/activate
python3 epub_to_markdown.py ...
```

> **Note:** the examples below are written as `python3 epub_to_markdown.py …` / `python3 epub_to_html.py …`. With uv, run them as `uv run python …` (or activate `.venv` first).

<details>
<summary>Optional: enable the short <code>epub2markdown</code> / <code>epub2html</code> commands</summary>

Add a build backend to `pyproject.toml` so uv installs the console entry points:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
include = ["epub_to_markdown.py", "epub_to_html.py"]
```

Then re-run `uv sync --extra full` and use `uv run epub2markdown …` / `uv run epub2html …`.
</details>

## Quick Start

Convert every EPUB in the current folder:

```bash
python3 epub_to_markdown.py         # -> Markdown
python3 epub_to_html.py             # -> HTML
```

Each book gets its own subfolder:

```
book1/book1.md    + book1/images/     # markdown tool
book1/book1.html  + book1/images/     # html tool
```

Convert a single book, or use options (identical for both tools):

```bash
python3 epub_to_html.py mybook.epub              # single book -> HTML
python3 epub_to_markdown.py --zoom 60            # smaller images (60%)
python3 epub_to_html.py --split-chapters         # + per-chapter files
python3 epub_to_markdown.py --output-dir ./out   # choose output folder
```

## Usage

```bash
python3 epub_to_markdown.py [options] [epub_file_or_dir...]   # Markdown
python3 epub_to_html.py     [options] [epub_file_or_dir...]   # HTML
```

### Modes

1. **No arguments**: Process all `.epub` files in current directory
2. **Single EPUB file**: Process that specific file
3. **Multiple EPUB files**: Process each one
4. **Extracted directory**: Process pre-extracted EPUB directory

### Options

Both tools accept the same options:

| Option | Description | Default |
|--------|-------------|---------|
| `--zoom PERCENT` | Image display size (1-100) | 100 |
| `--include-titlepage` | Include titlepage in output | Skipped |
| `--split-chapters` | Export individual chapter files to `chapters/` | Disabled |
| `--output-dir DIR` | Output directory for all conversions | Current directory |
| `--auto-scale [WIDTH]` | Scale large images down to max `WIDTH` px (default 800). Requires `Pillow`. | Disabled |
| `-h, --help` | Show help message | - |

## Output Structure

Both tools use the same layout — only the document's extension differs (`.md` vs `.html`):

```
your-directory/
├── epub_to_markdown.py / epub_to_html.py
├── book.epub               # Original EPUB (can delete)
└── book/                   # Created automatically
    ├── book.md  OR  book.html     # Complete document
    ├── chapters/                  # Only with --split-chapters
    │   ├── 01_chapter_one.(md|html)
    │   ├── 02_chapter_two.(md|html)
    │   └── ...
    └── images/                    # All book images
        ├── cover.jpg
        ├── figure1.png
        └── ...
```

The `<book>.html` is a single self-contained file (the stylesheet is embedded), and each split chapter is a standalone HTML page. Image references use `images/…` (or `../images/…` inside `chapters/`).

## What Gets Converted

- All text content in reading order
- All images (preserved in `images/` directory)
- Book metadata (title, author, publisher, date)
- Headings and document structure
- **Bold text** (including `.bold`, `.gothic`, `.gfont` classes)
- *Italic text* (including gaiji markers like tm2.png/tu2.png)
- Underline, subscript, superscript, strikethrough, highlight, small text
- Tables
- Lists (respects `list-style-type: none` CSS)

## HTML output (`epub_to_html.py`)

The HTML converter reuses the same content normalization as the Markdown tool, then writes clean HTML directly instead of running it through `html2text`:

- **Self-contained & styled** — one `<book>.html` with an embedded stylesheet: a centered readable column, responsive images (`max-width:100%`), styled blockquotes/code/tables, CJK-friendly fonts, and automatic **light/dark** mode.
- **Semantic tags** — CSS classes become real tags: `.bold`/`.gothic`/`.gfont` → `<strong>`, `.italic` → `<em>`, and underline/subscript/superscript/strikethrough/highlight/small become native `<u>`/`<sub>`/`<sup>`/`<del>`/`<mark>`/`<small>` (Markdown can't represent several of these).
- **Cleaned markup** — presentational noise (`class`, `id`, `xmlns`, and vendor wrappers such as Kobo's per-sentence spans) is stripped; `src`/`href`/`alt`/`style` and table structure (`colspan`/`rowspan`) are kept. `<script>` tags are removed.
- **Images** — copied to `images/`, with sizing applied inline (gaiji → `1em`, explicit sizes, `--auto-scale`, `--zoom`); SVG cover pages are converted to plain `<img>`.
- **No `html2text` needed** — only `beautifulsoup4` (plus optional `Pillow` for `--auto-scale`).

Open the resulting `.html` directly in any browser; with `--split-chapters`, each chapter file is a standalone, styled page.

## Examples

### Convert a textbook to Markdown

```bash
python3 epub_to_markdown.py economics.epub

# Result:
# economics/
# ├── economics.md
# └── images/
```

### Convert to HTML (single self-styled file)

```bash
python3 epub_to_html.py economics.epub

# Result:
# economics/
# ├── economics.html      # open in any browser
# └── images/
```

### Batch Convert with Small Images

```bash
python3 epub_to_markdown.py --zoom 50     # or: epub_to_html.py

# All EPUBs converted with 50% image size
```

### Auto-scale large images (requires Pillow)

```bash
python3 epub_to_html.py --auto-scale 800 mybook.epub   # cap wide images at 800px
```

### Convert to a Specific Directory

```bash
python3 epub_to_html.py --output-dir ~/Documents/Books

# All books go to ~/Documents/Books/<book_name>/
```

### Split into Individual Chapters

```bash
python3 epub_to_html.py --split-chapters mybook.epub   # or: epub_to_markdown.py

# Result:
# mybook/
# ├── mybook.html          # Complete book
# ├── chapters/            # Individual chapters (standalone, styled)
# │   ├── 01_introduction.html
# │   ├── 02_chapter_one.html
# │   └── ...
# └── images/
```

## Troubleshooting

### Error: "No EPUB files found"
- Navigate to folder containing EPUB files
- Or specify file directly: `python3 epub_to_markdown.py /path/to/book.epub`

### Error: "ModuleNotFoundError: No module named 'bs4'" (or 'html2text')
Dependencies aren't installed, or you're not running inside the uv environment:
```bash
uv sync --extra full
uv run python epub_to_markdown.py ...    # or: source .venv/bin/activate
```

### Images not displaying
- Ensure the `images/` directory sits next to your `.md`/`.html` file
- The structure should be: `book/book.md` (or `book.html`) + `book/images/`

### Corrupted or non-standard EPUB
- Try opening the EPUB in an EPUB reader first to verify it works
- Check if the EPUB has a valid `META-INF/container.xml` file

## Documentation

- `QUICKSTART.md` - Quick start guide
- `COMMANDS.md` - Complete command reference
- `CHEATSHEET.txt` - Quick reference card

## License

MIT License
