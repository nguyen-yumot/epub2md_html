# Quick Start — Commands You Can Copy & Paste

Convert EPUB books into **Markdown** (`.md`) or **clean HTML** (`.html`).

> **Before anything:** open a terminal *inside this project folder* (the one that
> contains `pyproject.toml`). Every command below is run from here.
> `uv run` sets everything up automatically the first time — no separate install step.

---

## ⭐ The one you want: convert EVERY EPUB in a folder

Put your books in the `epub_input/` folder, then run:

```bash
# → Markdown
uv run epub_to_markdown.py epub_input/*.epub --output-dir converted

# → HTML
uv run epub_to_html.py epub_input/*.epub --output-dir converted
```

Every `.epub` in `epub_input/` is converted. Each book gets its **own subfolder**
inside `converted/`:

```
converted/
├── My First Book/
│   ├── My First Book.md      (or .html)
│   └── images/
└── Another Book/
    ├── Another Book.md
    └── images/
```

Books live in a different folder? Just point at it:

```bash
uv run epub_to_markdown.py /path/to/my/books/*.epub --output-dir converted
```

> ⚠️ Use `folder/*.epub` (with the `*.epub` on the end), **not** just `folder`.
> Passing a bare folder name makes the tool think it's one already-unzipped book.

---

## Convert ONE book

```bash
uv run epub_to_markdown.py "epub_input/My Book.epub" --output-dir converted
```

Keep the quotes if the filename has spaces.

---

## Convert everything sitting in the current folder (no filenames to type)

Drop your `.epub` files right next to the scripts, then just:

```bash
uv run epub_to_markdown.py        # all *.epub in this folder → Markdown
uv run epub_to_html.py            # all *.epub in this folder → HTML
```

The book subfolders are created right here in the project folder.

---

## The 4 tweaks you'll actually use

Add any of these to the **end** of a command:

| I want to…                             | Add this                  |
| -------------------------------------- | ------------------------- |
| Send output to a tidy folder           | `--output-dir converted`  |
| Shrink big images (e.g. to 60%)        | `--zoom 60`               |
| Also save each chapter as its own file | `--split-chapters`        |
| Auto-shrink huge images to 800px wide  | `--auto-scale`            |

Example combining a few:

```bash
uv run epub_to_markdown.py epub_input/*.epub --output-dir converted --zoom 70 --split-chapters
```

For `--auto-scale`, add `--extra full` so the image library is available:

```bash
uv run --extra full epub_to_html.py epub_input/*.epub --output-dir converted --auto-scale
```

---

## Something went wrong?

- **`uv: command not found`** → install uv once: `brew install uv`
- **`No EPUB files found`** → you ran it with no filenames *and* there are no
  `.epub` files in the current folder. Use the `epub_input/*.epub` form instead.
- **Nothing converts, or a folder is "treated as a directory"** → you passed a
  bare folder name. Add `/*.epub` to the end of it.

Need the full picture (install options, every flag, advanced usage)? → see **README.md**.
