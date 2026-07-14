# Quick Start Guide — EPUB to Markdown / HTML

Two tools, same options and output layout — pick your format:

- **`epub_to_markdown.py`** → `<book>.md`  (editing, diffing, pipelines)
- **`epub_to_html.py`** → `<book>.html`  (single self-styled file for reading in a browser)

Every command below works with either script — just swap the name.

## One-Time Setup

This project uses [uv](https://docs.astral.sh/uv/). Install uv, then from the project folder:

```bash
uv sync --extra full     # creates .venv and installs all dependencies
```

Run the commands below with `uv run` (e.g. `uv run python epub_to_markdown.py …`), or
`source .venv/bin/activate` once and use `python3 …` directly.

## Convert EPUB Files

### Simplest Usage — Convert All EPUBs

```bash
# Run in a folder containing EPUB files
python3 epub_to_markdown.py          # -> Markdown
python3 epub_to_html.py              # -> HTML

# Output: each book gets its own subfolder
# book1/book1.md    + book1/images/     (markdown)
# book1/book1.html  + book1/images/     (html)
```

### Convert Single EPUB

```bash
python3 epub_to_html.py mybook.epub

# Output: mybook/mybook.html + mybook/images/
```

### With Smaller Images

```bash
python3 epub_to_markdown.py --zoom 60      # or: epub_to_html.py

# All EPUBs converted with 60% image size
```

### Auto-scale Large Images (requires Pillow)

```bash
python3 epub_to_html.py --auto-scale 800

# Wide images capped at 800px
```

### Output to Specific Directory

```bash
python3 epub_to_html.py --output-dir ~/Documents/Books

# Output goes to ~/Documents/Books/<book_name>/
```

### Split into Individual Chapters

```bash
python3 epub_to_html.py --split-chapters

# Output: book/book.html + book/chapters/*.html + book/images/
```

## Example: Convert "economics.epub"

```bash
python3 epub_to_markdown.py economics.epub   # economics/economics.md  + images/
python3 epub_to_html.py     economics.epub   # economics/economics.html + images/
```

## Clean Up After Conversion

```bash
rm mybook.epub      # Remove original EPUB (optional)
# Keep: mybook/mybook.(md|html) + mybook/images/
```

## Command Reference

```bash
# Full syntax (identical for both tools)
python3 epub_to_markdown.py [epub_files...] [options]
python3 epub_to_html.py     [epub_files...] [options]

# Options
--zoom PERCENT          # Image size (1-100, default: 100)
--include-titlepage     # Include titlepage (skipped by default)
--split-chapters        # Export individual chapter files
--output-dir DIR        # Output directory
--auto-scale [WIDTH]    # Scale large images to max WIDTH px (default 800; needs Pillow)

# Examples (swap in epub_to_html.py for HTML output)
python3 epub_to_markdown.py                              # All EPUBs in current dir
python3 epub_to_markdown.py book.epub                    # Single EPUB
python3 epub_to_markdown.py book1.epub book2.epub        # Multiple EPUBs
python3 epub_to_markdown.py --zoom 60                    # With 60% images
python3 epub_to_markdown.py --split-chapters             # With chapter files
python3 epub_to_markdown.py --output-dir ./converted     # To specific directory
```

## Output Structure

Same layout for both tools — only the extension differs (`.md` vs `.html`):

```
your-directory/
├── epub_to_markdown.py / epub_to_html.py
├── book.epub              # Original (can delete after)
└── book/                  # Created automatically
    ├── book.md  OR  book.html     # Your document
    ├── chapters/                  # Only with --split-chapters
    │   ├── 01_intro.(md|html)
    │   ├── 02_chapter.(md|html)
    │   └── ...
    └── images/                    # All book images
```
