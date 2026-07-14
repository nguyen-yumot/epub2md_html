# Command Reference - EPUB to Markdown / HTML Conversion

This document lists the command-line steps to convert any EPUB file. Two tools share the same options and output layout:

- **`epub_to_markdown.py`** → a combined Markdown file (`<book>.md`)
- **`epub_to_html.py`** → a single self-styled HTML file (`<book>.html`)

Every command below works with either script — just swap the name. Output goes to a `<book_name>/` folder containing the document, `images/`, and (with `--split-chapters`) `chapters/`.

## Table of Contents
1. [Prerequisites](#prerequisites)
2. [Quick Start](#quick-start)
3. [Usage Modes](#usage-modes)
4. [Options](#options)
5. [Markdown vs HTML output](#markdown-vs-html-output)
6. [Examples](#examples)
7. [Troubleshooting](#troubleshooting)

---

## Prerequisites

This project uses [uv](https://docs.astral.sh/uv/) for dependency management (deps are declared in `pyproject.toml`).

### One-Time Setup

```bash
# 1. Install uv (macOS)
brew install uv          # or: curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. Install dependencies from the project folder
uv sync --extra full     # required + optional (chardet, Pillow); omit --extra full for the minimum
```

`--extra full` adds `chardet` (encoding-detection fallback) and `Pillow` (needed for `--auto-scale`).

### Running the commands in this document

The examples are written as `python3 epub_to_markdown.py …`. With uv, run them as:

```bash
uv run python epub_to_markdown.py ...    # -> Markdown
uv run python epub_to_html.py ...        # -> HTML (companion tool, same options)
```

Or activate the environment once (`source .venv/bin/activate`) and use `python3 …` directly.

---

## Quick Start

### Convert All EPUBs in Current Directory

Simply run a tool in a folder containing EPUB files:

```bash
python3 epub_to_markdown.py     # -> Markdown
python3 epub_to_html.py         # -> HTML
```

This will:
1. Find all `.epub` files in the current directory
2. Extract and convert each one automatically
3. Create a subfolder for each book containing:
   - `<book_name>.md` (or `<book_name>.html`) — the document
   - `images/` - all book images

---

## Usage Modes

### Mode 1: Auto-Discovery (Recommended)

Place the script in a folder with EPUB files and run:

```bash
python3 epub_to_markdown.py
```

**Output structure:**
```
your-folder/
├── epub_to_markdown.py
├── book1.epub
├── book2.epub
├── book1/                  # Created automatically
│   ├── book1.md
│   └── images/
└── book2/                  # Created automatically
    ├── book2.md
    └── images/
```

### Mode 2: Single EPUB File

```bash
python3 epub_to_markdown.py mybook.epub
```

Creates `mybook/mybook.md` and `mybook/images/`

### Mode 3: Multiple EPUB Files

```bash
python3 epub_to_markdown.py book1.epub book2.epub book3.epub
```

### Mode 4: Pre-Extracted Directory

If you've already extracted an EPUB:

```bash
unzip -q mybook.epub -d mybook_extracted
python3 epub_to_markdown.py mybook_extracted
```

---

## Options

Both tools accept the same options:

| Option | Description | Default |
|--------|-------------|---------|
| `--zoom PERCENT` | Image display size (1-100) | 100 |
| `--include-titlepage` | Include titlepage in output | Skipped |
| `--split-chapters` | Export individual chapter files to chapters/ | Disabled |
| `--output-dir DIR` | Output directory for all conversions | Current directory |
| `--auto-scale [WIDTH]` | Scale large images down to max `WIDTH` px (default 800). Requires `Pillow`. | Disabled |
| `-h, --help` | Show help message | - |

### Examples with Options

```bash
# Convert all EPUBs with 60% image size
python3 epub_to_markdown.py --zoom 60

# Convert to a specific output directory
python3 epub_to_markdown.py --output-dir ./converted

# Include titlepage and use 50% zoom
python3 epub_to_markdown.py --include-titlepage --zoom 50

# Single book with options
python3 epub_to_markdown.py mybook.epub --zoom 75 --output-dir ./books

# Split into individual chapter files
python3 epub_to_markdown.py --split-chapters

# Combine options: chapters + small images
python3 epub_to_markdown.py --split-chapters --zoom 60
```

---

## Markdown vs HTML output

Both tools take the same EPUB and options; they differ only in what they write:

| | `epub_to_markdown.py` | `epub_to_html.py` |
|---|---|---|
| Output file | `<book>.md` | `<book>.html` (self-contained, styled) |
| Styling | plain Markdown | embedded stylesheet (light/dark, responsive, CJK fonts) |
| Inline formatting | bold/italic/code | native `<u>`/`<sub>`/`<sup>`/`<del>`/`<mark>`/`<small>` too |
| Extra dependency | `html2text` | none beyond `beautifulsoup4` |
| Best for | editing, diffing, pipelines | reading in a browser, printing to PDF |

The HTML tool strips presentational noise (`class`/`id`/`xmlns`, vendor spans), keeps `src`/`href`/`alt`/`style` and table structure, converts SVG cover pages to `<img>`, and removes `<script>`. Each `--split-chapters` file is a standalone, styled HTML page.

```bash
python3 epub_to_html.py mybook.epub                   # -> mybook/mybook.html
python3 epub_to_html.py --auto-scale 800 mybook.epub  # cap wide images at 800px
```

---

## Examples

### Example 1: Convert All Books in a Folder

```bash
# Navigate to folder with EPUB files
cd ~/Books/

# Run conversion
python3 /path/to/epub_to_markdown.py

# Result: Each book gets its own subfolder
```

### Example 2: Economics Textbook

```bash
python3 epub_to_markdown.py economics.epub

# Result:
# economics/
# ├── economics.md
# └── images/
#     ├── figure1.png
#     ├── figure2.png
#     └── ...
```

### Example 3: Batch Conversion with Small Images

```bash
python3 epub_to_markdown.py --zoom 50

# All EPUBs converted with 50% image size
```

### Example 4: Output to Specific Directory

```bash
python3 epub_to_markdown.py --output-dir ~/Documents/Markdown_Books

# All books go to ~/Documents/Markdown_Books/<book_name>/
```

### Example 5: Split into Individual Chapters

```bash
python3 epub_to_markdown.py --split-chapters mybook.epub

# Result:
# mybook/
# ├── mybook.md              # Complete book (always created)
# ├── chapters/              # Individual chapter files
# │   ├── 01_introduction.md
# │   ├── 02_chapter_one.md
# │   ├── 03_chapter_two.md
# │   └── ...
# └── images/
```

Chapters are detected from the EPUB's table of contents (NCX or NAV file). If no TOC exists, chapters are created from spine items.

---

## EPUB Compatibility

The converter handles various EPUB structures automatically:

| Structure Element | Supported Variations |
|-------------------|---------------------|
| OPF Location | `content.opf`, `package.opf`, `OEBPS/content.opf`, etc. |
| Image Folders | `images/`, `image/`, `Images/`, `OEBPS/images/`, etc. |
| Content Folders | `text/`, `content/`, `OEBPS/`, `OPS/`, etc. |
| Encodings | UTF-8, Latin-1, Shift-JIS, GB2312, etc. |

The script uses the standard EPUB container.xml and OPF manifest to locate all files correctly, regardless of folder structure.

---

## Features

### Formatting Preservation

The converter preserves:
- **Bold text** (including Japanese gothic/gfont classes)
- *Italic text* (including gaiji markers)
- <u>Underlined text</u> (em-line classes)
- Tables
- Lists (ordered and unordered)
- Headings and structure

### Special Handling

- **CSS `list-style-type: none`**: Converts numbered lists to bullet lists when CSS hides numbers
- **Internal EPUB links**: Removes cross-reference links but keeps the text
- **Duplicate images**: Automatically renamed to avoid conflicts
- **Gaiji markers**: Japanese emphasis markers (tm2.png/tu2.png) converted to italic

---

## Troubleshooting

### Error: "No EPUB files found"

**Problem:** No `.epub` files in current directory.

**Solution:** Either:
- Navigate to folder containing EPUB files
- Specify EPUB file(s) directly: `python3 epub_to_markdown.py /path/to/book.epub`

### Error: "Not a valid EPUB/ZIP file"

**Problem:** The file is corrupted or not an EPUB.

**Solution:**
- Try opening the EPUB in an EPUB reader to verify it works
- Re-download the file if corrupted

### Error: "No OPF file found"

**Problem:** Invalid or non-standard EPUB structure.

**Solution:**
- This is rare with legitimate EPUBs
- Try extracting manually and checking for `.opf` file

### Error: "ModuleNotFoundError: No module named 'bs4'" (or 'html2text')

**Problem:** Dependencies aren't installed, or the command isn't running inside the uv environment.

**Solution:**
```bash
uv sync --extra full
uv run python epub_to_markdown.py ...    # or: source .venv/bin/activate
```

### Images Not Displaying

**Problem:** Markdown viewer can't find images.

**Solution:**
- Ensure `images/` directory is in the same folder as your `.md` file
- The output structure should be:
  ```
  book_name/
  ├── book_name.md
  └── images/
  ```

### Permission Denied

**Problem:** Can't write output files.

**Solution:**
```bash
# Check directory permissions
ls -la

# Or specify a different output directory
python3 epub_to_markdown.py --output-dir ~/Documents/books
```

---

## Quick Reference Card

```
EPUB → Markdown / HTML — Quick Reference
(swap epub_to_markdown.py <-> epub_to_html.py for the other format)

  Convert all EPUBs in current folder:
     python3 epub_to_markdown.py          # or: epub_to_html.py

  Convert single EPUB:
     python3 epub_to_html.py BOOK.epub

  With smaller images (60%):
     python3 epub_to_markdown.py --zoom 60

  Auto-scale large images (needs Pillow):
     python3 epub_to_html.py --auto-scale 800

  Split into chapter files:
     python3 epub_to_html.py --split-chapters

  Output to specific folder:
     python3 epub_to_markdown.py --output-dir ./out

  Output: book_name/book_name.(md|html) + book_name/images/
          book_name/chapters/ (with --split-chapters)
```

---

## File Structure After Conversion

### Before:
```
your-directory/
├── epub_to_markdown.py
├── book1.epub
├── book2.epub
└── book3.epub
```

### After running `python3 epub_to_markdown.py`:
```
your-directory/
├── epub_to_markdown.py
├── book1.epub               # Original (can delete)
├── book2.epub               # Original (can delete)
├── book3.epub               # Original (can delete)
├── book1/                   # ✓ Output folder
│   ├── book1.md            # ✓ Markdown file
│   └── images/             # ✓ Book images
├── book2/                   # ✓ Output folder
│   ├── book2.md
│   └── images/
└── book3/                   # ✓ Output folder
    ├── book3.md
    └── images/
```

### After running `python3 epub_to_markdown.py --split-chapters`:
```
your-directory/
└── book1/
    ├── book1.md            # ✓ Complete markdown
    ├── chapters/           # ✓ Individual chapters
    │   ├── 01_intro.md
    │   ├── 02_chapter_1.md
    │   └── ...
    └── images/             # ✓ Book images
```

The files you need to keep are marked with ✓. Original EPUB files can be deleted after successful conversion.
