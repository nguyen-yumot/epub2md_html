#!/usr/bin/env python3
"""
EPUB to HTML Converter
Converts EPUB files to a single clean, self-styled HTML file while preserving
images and content structure. Companion to epub_to_markdown.py — it reuses that
module's EPUB-parsing and content-normalization pipeline, but serializes the
normalized content as HTML instead of Markdown.

Usage:
    python3 epub_to_html.py [options] [epub_file_or_dir...]

Modes:
    1. No arguments: Process all .epub files in current directory
    2. Single EPUB file: Process that specific file
    3. Multiple EPUB files: Process each one
    4. Extracted directory: Process pre-extracted EPUB directory

Output:
    For each EPUB file, creates a subfolder with:
    - <book_name>.html (the combined HTML file, with a clean built-in stylesheet)
    - images/ (all book images)

Options:
    --zoom PERCENT       Set image display size (1-100). Default: 100
    --include-titlepage  Include titlepage in output (skipped by default)
    --split-chapters     Also export individual chapter files to chapters/ subdirectory
    --output-dir DIR     Output directory for all conversions. Default: current directory
    --auto-scale [WIDTH] Auto-scale large images to max width (default: 800px). Requires Pillow.

Examples:
    python3 epub_to_html.py                        # Convert all EPUBs in current dir
    python3 epub_to_html.py book.epub              # Convert single EPUB
    python3 epub_to_html.py --split-chapters       # Also create individual chapter files
    python3 epub_to_html.py --output-dir ./html    # Output to specific directory

Content handling:
    The same normalization the Markdown converter applies is reused (CSS classes
    such as .bold/.italic/.gothic -> <strong>/<em>, gaiji marker pairs -> <em>,
    list-style:none <ol> -> <ul>, internal cross-reference links unwrapped). Since
    HTML natively supports <u>/<sub>/<sup>/<del>/<small>/<mark>, those are emitted
    directly rather than round-tripped through placeholder markers. <script> tags
    are stripped for safety.
"""

import argparse
import html
import re
import shutil
import sys
import tempfile
import traceback
from pathlib import Path
from urllib.parse import unquote

from bs4 import BeautifulSoup

# Reuse the EPUB-parsing + normalization pipeline from the Markdown converter.
from epub_to_markdown import (
    HAS_PIL,
    _normalize_list_styles,
    _normalize_styling_classes,
    _process_gaiji,
    _unwrap_internal_links,
    _zoom_arg,
    calculate_smart_scale,
    copy_manifest_images,
    extract_epub,
    extract_image_sizing,
    find_content_for_file,
    find_epub_files,
    find_opf_file,
    get_chapters_from_toc,
    get_image_dimensions,
    parse_opf,
    read_file_with_encoding,
    resolve_image_filename,
    sanitize_filename,
)


# Clean, readable default stylesheet embedded in every output document.
DEFAULT_CSS = """\
:root { color-scheme: light dark; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Helvetica Neue",
               "Hiragino Sans", "Yu Gothic", Meiryo, sans-serif;
  line-height: 1.7;
  max-width: 42rem;
  margin: 0 auto;
  padding: 2rem 1.25rem 4rem;
  color: #1a1a1a;
  background: #ffffff;
}
header.book-meta h1 { font-size: 1.9rem; line-height: 1.25; margin: 0 0 0.5rem; }
header.book-meta p { margin: 0.15rem 0; color: #666; font-size: 0.95rem; }
h1, h2, h3, h4, h5, h6 { line-height: 1.3; margin-top: 2rem; }
p { margin: 0.9rem 0; }
img { max-width: 100%; height: auto; }
figure { margin: 1.5rem 0; }
figcaption { font-size: 0.85em; color: #666; text-align: center; }
blockquote { margin: 1.25rem 0; padding: 0.25rem 1rem; border-left: 4px solid #d0d0d0; color: #555; }
code { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
       font-size: 0.9em; background: #f2f2f2; padding: 0.1em 0.35em; border-radius: 4px; }
pre { background: #f2f2f2; padding: 1rem; overflow-x: auto; border-radius: 6px; }
pre code { background: none; padding: 0; }
mark { background: #fff3a3; padding: 0 0.15em; }
small { font-size: 0.82em; }
table { border-collapse: collapse; margin: 1.25rem 0; }
th, td { border: 1px solid #ccc; padding: 0.4rem 0.6rem; }
hr { border: none; border-top: 1px solid #e0e0e0; margin: 2rem 0; }
section.chapter { margin-top: 2.5rem; }
section.chapter:first-of-type { margin-top: 0; }
@media (prefers-color-scheme: dark) {
  body { color: #e6e6e6; background: #16181c; }
  a { color: #6db3f2; }
  header.book-meta p, figcaption { color: #9aa0aa; }
  blockquote { border-color: #3a3f47; color: #b8bcc4; }
  code, pre { background: #22262e; }
  mark { background: #7a6a1f; color: #fff; }
  th, td { border-color: #3a3f47; }
  hr { border-color: #2c313a; }
}
"""


# Attributes worth keeping on body content; everything else (class, id, xmlns,
# epub:*, data-*, vendor wrappers like Kobo's koboSpan, etc.) is presentational
# or structural noise once the content has been normalized to semantic tags.
_KEEP_ATTRS = {'src', 'href', 'alt', 'style', 'title', 'colspan', 'rowspan'}


def _clean_attributes(soup):
    """Strip noise attributes down to _KEEP_ATTRS, then unwrap bare <span>s.

    After normalization the original class/id/namespace attributes are dead
    weight (the built-in stylesheet targets none of them). Removing them and
    dropping now-attribute-less <span> wrappers yields much cleaner HTML while
    preserving links, images, inline styles, and table structure.
    """
    for tag in soup.find_all(True):
        if tag.attrs:
            tag.attrs = {k: v for k, v in tag.attrs.items() if k in _KEEP_ATTRS}
    # A <span> with no remaining attributes is an inline no-op wrapper; unwrap it.
    for span in soup.find_all('span'):
        if not span.attrs:
            span.unwrap()


def _rewrite_images_for_html(soup, image_rename_map, image_src_map, base_dir,
                             images_dir, zoom_ratio, auto_scale_width):
    """Point <img>/<svg image> sources at images/… and set sizing inline styles.

    HTML-native equivalent of the Markdown converter's image handling: instead of
    encoding sizing in placeholder markers (needed because html2text drops style),
    the computed style is written straight onto the <img> tag. Style priority:
    gaiji (1em) > explicit HTML sizing > auto-scale (large images) > --zoom.
    """
    # Convert SVG <image> (common on cover pages) to a plain <img> FIRST, so it
    # runs through the same resolution + sizing pipeline as regular <img> below.
    # Replace the enclosing <svg> (not just the <image>) so the <img> isn't
    # stranded inside foreign SVG content, where browsers won't render it.
    for image_elem in list(soup.find_all('image')):
        if image_elem.parent is None:
            continue  # already removed together with its <svg>
        href = image_elem.get('xlink:href') or image_elem.get('href', '')
        if not href or re.match(r'(https?://|data:)', href):
            continue
        img_tag = soup.new_tag('img')
        img_tag['src'] = href  # resolved by the <img> pass below
        img_tag['alt'] = ''
        target = image_elem.find_parent('svg') or image_elem
        target.replace_with(img_tag)

    for img in soup.find_all('img'):
        src = img.get('src', '')
        if not src or re.match(r'(https?://|data:)', src):
            continue
        src = unquote(src)

        img_classes = img.get('class', [])
        if isinstance(img_classes, str):
            img_classes = img_classes.split()
        is_gaiji = bool({'gaiji', 'gaiji-wide', 'gaiji-icon'} & set(img_classes))

        # Compute style before mutating attrs (extract_image_sizing reads
        # width/height/style/class of the original tag).
        if is_gaiji:
            style = 'height:1em;vertical-align:text-bottom;'
        else:
            style = extract_image_sizing(img)

        final_filename = resolve_image_filename(src, base_dir, image_src_map, image_rename_map)
        img['src'] = f'images/{final_filename}'

        # width/height are now captured in `style` (when present); drop the raw
        # attributes so they can't conflict with the inline style.
        for attr in ('width', 'height'):
            if img.has_attr(attr):
                del img[attr]

        if not style and auto_scale_width and images_dir:
            dimensions = get_image_dimensions(images_dir / final_filename)
            if dimensions:
                style = calculate_smart_scale(dimensions[0], dimensions[1], auto_scale_width)

        if not style and zoom_ratio < 100:
            style = f'zoom:{zoom_ratio}%;'

        if style:
            img['style'] = style
        elif img.has_attr('style'):
            del img['style']


def html_content_to_body(html_content, image_rename_map, image_src_map, base_dir,
                         images_dir, zoom_ratio, auto_scale_width):
    """Normalize one XHTML document and return its <body> inner HTML.

    Runs the shared soup-normalization phases, applies HTML-native image
    rewriting, unwraps internal links, strips script/style/link, and serializes
    the body content.
    """
    soup = BeautifulSoup(html_content, 'html.parser')

    _normalize_list_styles(soup)          # reads <style> content; must run first
    _normalize_styling_classes(soup)      # CSS classes -> semantic tags
    _process_gaiji(soup)                  # gaiji marker image pairs -> <em>
    _rewrite_images_for_html(soup, image_rename_map, image_src_map, base_dir,
                             images_dir, zoom_ratio, auto_scale_width)
    _unwrap_internal_links(soup)          # drop internal EPUB cross-references
    _clean_attributes(soup)               # strip class/id/xmlns noise, unwrap bare spans

    # Remove markup that doesn't belong in the combined document. <head> is
    # dropped too so a body-less document can't leak <title>/<meta> into a section.
    for tag in soup.find_all(['script', 'style', 'link', 'head']):
        tag.decompose()

    # decode_contents() (not str-joining children) so bare text with '&'/'<'
    # in the body is properly escaped into valid HTML entities.
    body = soup.body or soup.find('html') or soup
    return body.decode_contents().strip()


def build_html_document(title, metadata, sections):
    """Assemble a complete, self-styled HTML document from body sections."""
    safe_title = html.escape(title or 'Untitled')
    parts = [
        '<!DOCTYPE html>',
        '<html>',
        '<head>',
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f'<title>{safe_title}</title>',
        f'<style>\n{DEFAULT_CSS}</style>',
        '</head>',
        '<body>',
        '<header class="book-meta">',
        f'<h1>{safe_title}</h1>',
    ]
    if metadata.get('authors'):
        authors = html.escape(', '.join(metadata['authors']))
        parts.append(f'<p class="authors"><strong>Authors:</strong> {authors}</p>')
    if metadata.get('publisher'):
        parts.append(f'<p class="publisher"><strong>Publisher:</strong> {html.escape(metadata["publisher"])}</p>')
    if metadata.get('date'):
        parts.append(f'<p class="date"><strong>Date:</strong> {html.escape(metadata["date"])}</p>')
    parts.append('</header>')
    parts.append('<hr>')
    parts.extend(sections)
    parts.append('</body>')
    parts.append('</html>')
    return '\n'.join(parts)


def write_chapter_html_files(chapters, chapter_bodies, chapters_dir, book_name):
    """Write individual standalone chapter HTML files (mirrors write_chapter_files)."""
    written_count = 0
    for i, chapter in enumerate(chapters, 1):
        title = chapter['title']
        src_files = chapter.get('src_files', [chapter['src_file']])

        parts = []
        for src_file in src_files:
            bodies = find_content_for_file(src_file, chapter_bodies)
            if bodies:
                parts.extend(bodies)

        if not parts:
            continue

        body = '\n'.join(f'<section class="chapter">\n{b}\n</section>' for b in parts)
        # chapters/ is one level deeper than images/, so fix the relative paths
        # (both element attributes and CSS url(...) references).
        body = re.sub(r'(\b(?:src|href)=")images/', r'\1../images/', body)
        body = re.sub(r'(url\(\s*[\'"]?)images/', r'\1../images/', body)

        safe_title = sanitize_filename(title)
        filename = f"{i:02d}_{safe_title}.html"
        document = build_html_document(title, {}, [body])

        with open(chapters_dir / filename, 'w', encoding='utf-8') as f:
            f.write(document)
        written_count += 1

    print(f"Created {written_count} chapter files in {chapters_dir}")


def convert_epub_to_html(epub_source, output_dir, zoom_ratio=100, skip_titlepage=True,
                         split_chapters=False, auto_scale_width=None):
    """Convert an EPUB file or extracted directory to a combined HTML file.

    Returns the Path to the created HTML file.
    """
    epub_source = Path(epub_source)
    output_dir = Path(output_dir)

    temp_dir = None
    if epub_source.is_file() and epub_source.suffix.lower() == '.epub':
        temp_dir = tempfile.mkdtemp(prefix='epub_extract_')
        print(f"Extracting {epub_source.name}...")
        epub_path = extract_epub(epub_source, temp_dir)
        book_name = epub_source.stem
    elif epub_source.is_dir():
        epub_path = epub_source
        book_name = epub_source.name
        if book_name.lower().endswith('.epub'):
            book_name = book_name[:-5]
    else:
        raise ValueError(f"Invalid EPUB source: {epub_source}")

    try:
        opf_file = find_opf_file(epub_path)
        opf_dir = opf_file.parent

        try:
            opf_relative = opf_file.relative_to(epub_path)
        except ValueError:
            opf_relative = opf_file.name
        print(f"Found OPF file: {opf_relative}")

        metadata, spine_order, manifest_items = parse_opf(opf_file)

        if not spine_order:
            print("Warning: No content files found in spine. The EPUB may be malformed.")

        output_dir.mkdir(parents=True, exist_ok=True)
        output_file = output_dir / f"{book_name}.html"
        images_output_dir = output_dir / 'images'
        images_output_dir.mkdir(exist_ok=True)

        # Copy all manifest images (path-keyed to avoid cross-wiring duplicates)
        (image_src_map, image_rename_map, image_count, image_errors,
         renamed_count) = copy_manifest_images(manifest_items, images_output_dir)

        if image_count > 0:
            print(f"Copied {image_count} images to {images_output_dir}")
        if image_errors > 0:
            print(f"Warning: {image_errors} image(s) failed to copy")
        if renamed_count > 0:
            print(f"Note: {renamed_count} duplicate image(s) were renamed")

        # Chapter structure if splitting
        chapters = None
        chapter_bodies = {}  # src_file -> list of body HTML
        chapters_dir = None
        if split_chapters:
            chapters = get_chapters_from_toc(manifest_items, opf_dir, spine_order)
            chapters_dir = output_dir / 'chapters'
            chapters_dir.mkdir(exist_ok=True)

        # Process each file in spine order
        print(f"Processing {len(spine_order)} content files...")
        sections = []
        for i, file_path in enumerate(spine_order, 1):
            if skip_titlepage and 'titlepage' in file_path.lower():
                continue

            full_path = opf_dir / file_path
            if not full_path.exists():
                print(f"Warning: {file_path} not found, skipping...")
                continue

            html_content = read_file_with_encoding(full_path)
            body = html_content_to_body(html_content, image_rename_map, image_src_map,
                                        full_path.parent, images_output_dir, zoom_ratio,
                                        auto_scale_width)

            if body:
                sections.append(f'<section class="chapter">\n{body}\n</section>')
                if split_chapters:
                    chapter_bodies.setdefault(file_path, []).append(body)

            if i % 10 == 0:
                print(f"Processed {i}/{len(spine_order)} files...")

        document = build_html_document(metadata.get('title', book_name), metadata, sections)

        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(document)

        print("\nConversion complete!")
        print(f"HTML file: {output_file}")
        print(f"Images directory: {images_output_dir}")
        print(f"Total size: {len(document)} characters")

        if split_chapters and chapters:
            write_chapter_html_files(chapters, chapter_bodies, chapters_dir, book_name)

        return output_file

    finally:
        if temp_dir:
            shutil.rmtree(temp_dir, ignore_errors=True)


def main():
    """Main entry point with CLI argument parsing."""
    parser = argparse.ArgumentParser(
        prog='epub_to_html.py',
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        allow_abbrev=False,
    )
    parser.add_argument('--zoom', type=_zoom_arg, default=100, metavar='PERCENT',
                        help='Image display size (1-100). Default: 100')
    parser.add_argument('--include-titlepage', action='store_true',
                        help='Include titlepage in output (skipped by default)')
    parser.add_argument('--split-chapters', action='store_true',
                        help='Also export individual chapter files to chapters/')
    parser.add_argument('--output-dir', type=Path, metavar='DIR',
                        help='Output directory for all conversions. Default: current directory')
    parser.add_argument('--auto-scale', nargs='?', const='800', default=None, metavar='WIDTH',
                        help='Auto-scale large images to max WIDTH px (default 800). Requires Pillow.')
    parser.add_argument('sources', nargs='*', metavar='epub_file_or_dir',
                        help='EPUB file(s) or extracted directory(ies). Default: all *.epub in cwd')
    args = parser.parse_args()

    zoom_ratio = args.zoom
    skip_titlepage = not args.include_titlepage
    split_chapters = args.split_chapters
    output_dir = args.output_dir
    epub_sources = args.sources

    # Resolve --auto-scale: tell an explicit width apart from a source path that
    # nargs='?' may have swallowed when no width was given.
    auto_scale_width = None
    if args.auto_scale is not None:
        # isdecimal (not isdigit): guarantees int() accepts it.
        if args.auto_scale.isdecimal():
            width = int(args.auto_scale)
            if width <= 0:
                parser.error(f"argument --auto-scale: width must be a positive integer, got {width}")
            auto_scale_width = width
        else:
            # A non-numeric token was consumed; it is really a source, not a width.
            auto_scale_width = 800
            epub_sources.insert(0, args.auto_scale)
        if auto_scale_width is not None and not HAS_PIL:
            print("Warning: --auto-scale requires Pillow. Install with: pip install Pillow")
            print("         Continuing without auto-scaling.")
            auto_scale_width = None

    # If no sources specified, find all EPUBs in current directory
    if not epub_sources:
        epub_files = find_epub_files(Path('.'))
        if not epub_files:
            print("No EPUB files found in current directory.")
            print("\nUsage: python3 epub_to_html.py [options] [epub_file...]")
            print("       python3 epub_to_html.py --help")
            sys.exit(1)
        epub_sources = [str(f) for f in epub_files]
        print(f"Found {len(epub_sources)} EPUB file(s) to convert.\n")

    # Process each source
    successful = 0
    failed = 0

    for source in epub_sources:
        source_path = Path(source)
        print(f"\n{'='*60}")
        print(f"Processing: {source}")
        print('='*60)

        try:
            if output_dir:
                if source_path.suffix.lower() == '.epub':
                    book_output_dir = output_dir / source_path.stem
                else:
                    book_output_dir = output_dir / source_path.name
            else:
                if source_path.suffix.lower() == '.epub':
                    book_output_dir = Path('.') / source_path.stem
                else:
                    book_output_dir = Path('.') / source_path.name

            convert_epub_to_html(
                source_path,
                book_output_dir,
                zoom_ratio=zoom_ratio,
                skip_titlepage=skip_titlepage,
                split_chapters=split_chapters,
                auto_scale_width=auto_scale_width,
            )
            successful += 1

        except FileNotFoundError as e:
            print(f"\nError: {e}")
            failed += 1
        except Exception as e:
            print(f"\nError during conversion: {e}")
            traceback.print_exc()
            failed += 1

    # Summary
    if len(epub_sources) > 1:
        print(f"\n{'='*60}")
        print(f"Summary: {successful} successful, {failed} failed")
        print('='*60)

    sys.exit(0 if failed == 0 else 1)


if __name__ == '__main__':
    main()
