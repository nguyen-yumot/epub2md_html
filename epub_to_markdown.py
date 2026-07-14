#!/usr/bin/env python3
"""
EPUB to Markdown Converter
Converts EPUB files to markdown while preserving images and content structure.

Usage:
    python3 epub_to_markdown.py [options] [epub_file_or_dir...]

Modes:
    1. No arguments: Process all .epub files in current directory
    2. Single EPUB file: Process that specific file
    3. Multiple EPUB files: Process each one
    4. Extracted directory: Process pre-extracted EPUB directory

Output:
    For each EPUB file, creates a subfolder with:
    - <book_name>.md (the markdown file)
    - images/ (all book images)

Options:
    --zoom PERCENT       Set image display size (1-100). Default: 100
    --include-titlepage  Include titlepage in output (skipped by default)
    --split-chapters     Also export individual chapter files to chapters/ subdirectory
    --output-dir DIR     Output directory for all conversions. Default: current directory
    --auto-scale [WIDTH] Auto-scale large images to max width (default: 800px). Requires Pillow.

Examples:
    python3 epub_to_markdown.py                              # Convert all EPUBs in current dir
    python3 epub_to_markdown.py book.epub                    # Convert single EPUB
    python3 epub_to_markdown.py book1.epub book2.epub        # Convert multiple EPUBs
    python3 epub_to_markdown.py --zoom 60                    # All EPUBs at 60% image size
    python3 epub_to_markdown.py --output-dir ./converted     # Output to specific directory
    python3 epub_to_markdown.py --split-chapters             # Also create individual chapter files
    python3 epub_to_markdown.py --auto-scale                 # Auto-scale large images to 800px
    python3 epub_to_markdown.py --auto-scale 600             # Auto-scale large images to 600px
    python3 epub_to_markdown.py --split-chapters --auto-scale

Image Scaling Priority (when --auto-scale is used):
    1. Gaiji (inline symbols)     -> height:1em (always applied)
    2. Explicit HTML sizing       -> preserved as-is
    3. Auto-scale (width > max)   -> max-width:Xpx;height:auto;
    4. Small images (width <= max)-> plain markdown

Supported Formatting:
    - Bold, Italic, Underline, Strikethrough
    - Subscript, Superscript
    - Code blocks, Blockquotes
    - Tables, Images
    - Small text, Highlighted text
"""

import argparse
import functools
import re
import shutil
import sys
import tempfile
import traceback
import zipfile
from pathlib import Path
from urllib.parse import unquote

from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET

# NOTE: html2text is imported lazily inside _run_html2text so that modules which
# only reuse the EPUB-parsing helpers (e.g. epub_to_html.py) don't require it.

# Optional encoding detection
try:
    import chardet
    HAS_CHARDET = True
except ImportError:
    HAS_CHARDET = False

# Optional PIL for reading image dimensions
try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

# Common image extensions
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.svg', '.webp', '.bmp', '.tiff', '.tif'}

# Image sizing CSS classes mapping
# Maps class names to style strings
IMAGE_SIZE_CLASSES = {
    # Full width classes
    'full-width': 'width:100%;',
    'fullwidth': 'width:100%;',
    'full': 'width:100%;',
    'w-100': 'width:100%;',
    'img-fluid': 'max-width:100%;height:auto;',
    # Half width classes
    'half-width': 'width:50%;',
    'halfwidth': 'width:50%;',
    'half': 'width:50%;',
    'w-50': 'width:50%;',
    # Thumbnail/icon classes
    'thumbnail': 'max-width:150px;',
    'thumb': 'max-width:150px;',
    'icon': 'height:1.5em;vertical-align:middle;',
    'inline': 'height:1em;vertical-align:text-bottom;',
    'inline-image': 'height:1em;vertical-align:text-bottom;',
    # Cover/figure classes
    'cover': 'width:100%;max-height:100vh;object-fit:contain;',
    'figure': 'max-width:100%;',
    'fig': 'max-width:100%;',
    # Small classes
    'small-image': 'max-width:200px;',
    'small': 'max-width:200px;',
    # Medium classes
    'medium': 'max-width:400px;',
    'med': 'max-width:400px;',
}


def extract_href_file(href):
    """Extract file path from href, removing anchor and URL-decoding.

    Args:
        href: URL or path that may contain an anchor (#section)

    Returns:
        str: Decoded file path without anchor
    """
    # Extract file without anchor
    file_path = href.split('#')[0]
    # URL decode
    return unquote(file_path)


def restore_placeholder_tags(text, start_marker, end_marker, open_tag, close_tag):
    """Restore placeholder markers to actual tags and clean whitespace.

    Args:
        text: Text containing placeholder markers
        start_marker: Start placeholder (e.g., '⟦ULINE_S⟧')
        end_marker: End placeholder (e.g., '⟦ULINE_E⟧')
        open_tag: Opening tag (e.g., '<u>')
        close_tag: Closing tag (e.g., '</u>')

    Returns:
        str: Text with placeholders replaced and whitespace cleaned
    """
    text = text.replace(start_marker, open_tag)
    text = text.replace(end_marker, close_tag)
    # Clean up whitespace inside tags
    text = re.sub(re.escape(open_tag) + r'\s+', open_tag, text)
    text = re.sub(r'\s+' + re.escape(close_tag), close_tag, text)
    return text


def clean_whitespace_lines(text):
    """Clean whitespace-only lines and reduce excessive newlines.

    Args:
        text: Text to clean

    Returns:
        str: Cleaned text with whitespace-only lines emptied and max 2 consecutive newlines
    """
    lines = text.split('\n')
    lines = ['' if line.strip() == '' else line for line in lines]
    text = '\n'.join(lines)
    # Reduce 3+ consecutive newlines to 2
    return re.sub(r'\n{3,}', '\n\n', text)


def extract_image_sizing(img_tag):
    """Extract sizing information from an img tag.

    Checks for:
    1. Explicit width/height attributes
    2. Inline style with width/height
    3. CSS classes that indicate sizing

    Returns:
        str or None: Style string to apply, or None if no sizing found
    """
    styles = []

    # 1. Check explicit width/height attributes
    width = img_tag.get('width')
    height = img_tag.get('height')

    if width:
        # Handle both "100" and "100px" and "50%" formats
        if not any(c.isalpha() or c == '%' for c in str(width)):
            width = f"{width}px"
        styles.append(f"width:{width};")

    if height:
        if not any(c.isalpha() or c == '%' for c in str(height)):
            height = f"{height}px"
        styles.append(f"height:{height};")

    # 2. Check inline style attribute
    style = img_tag.get('style', '')
    if style:
        # Extract width and height from style if present
        width_match = re.search(r'width:\s*([^;]+)', style, re.I)
        height_match = re.search(r'height:\s*([^;]+)', style, re.I)
        max_width_match = re.search(r'max-width:\s*([^;]+)', style, re.I)
        max_height_match = re.search(r'max-height:\s*([^;]+)', style, re.I)

        if width_match and 'width:' not in ''.join(styles):
            styles.append(f"width:{width_match.group(1).strip()};")
        if height_match and 'height:' not in ''.join(styles):
            styles.append(f"height:{height_match.group(1).strip()};")
        if max_width_match:
            styles.append(f"max-width:{max_width_match.group(1).strip()};")
        if max_height_match:
            styles.append(f"max-height:{max_height_match.group(1).strip()};")

    # 3. Check CSS classes for sizing patterns
    img_classes = img_tag.get('class', [])
    if isinstance(img_classes, str):
        img_classes = img_classes.split()

    for cls in img_classes:
        cls_lower = cls.lower()
        if cls_lower in IMAGE_SIZE_CLASSES:
            class_style = IMAGE_SIZE_CLASSES[cls_lower]
            # Don't override explicit width/height
            if 'width' in class_style and 'width:' in ''.join(styles):
                continue
            if 'height' in class_style and 'height:' in ''.join(styles):
                continue
            styles.append(class_style)
            break  # Only apply first matching class

    if styles:
        return ''.join(styles)
    return None


@functools.lru_cache(maxsize=None)
def _read_image_size(path_str, mtime_ns, size):
    """PIL image-size read, cached by (path, mtime, size) file identity."""
    try:
        with Image.open(path_str) as img:
            return img.size
    except Exception:
        return None


def get_image_dimensions(image_path):
    """Get image dimensions using PIL.

    Memoized by file identity (path + mtime + size): an image reused across
    pages within a book is opened once, while a file overwritten between books
    (e.g. two same-named sources) is re-read rather than served stale.

    Args:
        image_path: Path to image file

    Returns:
        tuple: (width, height) or None if cannot read
    """
    if not HAS_PIL:
        return None

    try:
        st = Path(image_path).stat()
    except OSError:
        return None

    return _read_image_size(str(image_path), st.st_mtime_ns, st.st_size)


def calculate_smart_scale(width, height, max_width=800):
    """Calculate appropriate scale for large images.

    Args:
        width: Image width in pixels
        height: Image height in pixels
        max_width: Maximum display width (default 800px)

    Returns:
        str or None: Style string if scaling needed, None otherwise
    """
    if width and width > max_width:
        return f"max-width:{max_width}px;height:auto;"
    return None


def resolve_image_filename(src, base_dir, image_src_map, image_rename_map):
    """Resolve an image reference to its filename inside the output images/ dir.

    Prefers matching by the image's resolved source path so that two images that
    share a basename in different folders (e.g. a/cover.jpg and b/cover.jpg) are
    not cross-wired to the same output file. Falls back to a basename lookup only
    when the reference cannot be resolved against a known source path.

    Args:
        src: The (URL-decoded) src/href from the HTML, relative to base_dir.
        base_dir: Directory of the HTML file the reference appears in.
        image_src_map: Dict of resolved source path (str) -> output filename.
        image_rename_map: Dict of basename -> renamed output filename (fallback).

    Returns:
        str: Output filename to use under images/.
    """
    if base_dir is not None and image_src_map:
        try:
            resolved = str((Path(base_dir) / src).resolve())
        except (OSError, ValueError, RuntimeError):
            resolved = None
        if resolved is not None:
            mapped = image_src_map.get(resolved)
            if mapped is not None:
                return mapped

    basename = Path(src).name
    if image_rename_map:
        return image_rename_map.get(basename, basename)
    return basename


def detect_declared_encoding(raw_data):
    """Detect an encoding from a BOM or an XML/HTML charset declaration.

    EPUB content files (XHTML/NCX/OPF) almost always declare their encoding,
    which disambiguates codecs that blind trial-and-error cannot (e.g. Shift-JIS
    vs GB2312 share valid byte ranges, so guessing picks whichever is tried
    first even when wrong). Returns a codec name or None.
    """
    # Byte-order marks take precedence over any declaration
    if raw_data.startswith(b'\xff\xfe') or raw_data.startswith(b'\xfe\xff'):
        return 'utf-16'

    # The declaration is ASCII and lives at the top of the document; decode a
    # prefix as ASCII (dropping any multi-byte text) just to read the header.
    head = raw_data[:1024].decode('ascii', errors='ignore')

    # XML declaration: <?xml version="1.0" encoding="Shift_JIS"?>
    m = re.search(r'<\?xml[^>]*\bencoding\s*=\s*["\']([\w.-]+)["\']', head, re.I)
    if m:
        return m.group(1)

    # HTML <meta charset="..."> or <meta http-equiv=... content="...; charset=...">
    m = re.search(r'charset\s*=\s*["\']?([\w.-]+)', head, re.I)
    if m:
        return m.group(1)

    return None


def read_file_with_encoding(file_path):
    """Read a file with automatic encoding detection.

    Order: UTF-8 (with BOM stripping), then the file's own declared encoding,
    then chardet if available, then a list of common codecs, and finally a
    lossy replacement decode.
    """
    # Try UTF-8 first (most common for EPUB); utf-8-sig also strips a UTF-8 BOM
    try:
        with open(file_path, 'r', encoding='utf-8-sig') as f:
            return f.read()
    except UnicodeDecodeError:
        pass

    # Read the raw bytes once for every remaining strategy
    with open(file_path, 'rb') as f:
        raw_data = f.read()

    # Honor an explicit BOM / XML / HTML charset declaration when present.
    # Runs before chardet because a declaration is authoritative, whereas
    # chardet only guesses statistically.
    declared = detect_declared_encoding(raw_data)
    if declared:
        try:
            return raw_data.decode(declared)
        except (UnicodeDecodeError, LookupError):
            pass

    # Try chardet if available
    if HAS_CHARDET:
        detected = chardet.detect(raw_data)
        if detected['encoding']:
            try:
                return raw_data.decode(detected['encoding'])
            except (UnicodeDecodeError, LookupError):
                pass

    # Fallback to common encodings.
    # ORDER MATTERS: strict multi-byte CJK codecs come first so they can raise
    # UnicodeDecodeError on bytes that aren't valid for them and fall through.
    # The single-byte codecs (cp1252, then latin-1) go last because latin-1
    # decodes ANY byte sequence without error and would otherwise shadow every
    # codec after it, silently turning Shift-JIS/GB text into mojibake.
    fallback_encodings = ['shift_jis', 'euc-jp', 'gb2312', 'big5', 'cp1252', 'latin-1']
    for encoding in fallback_encodings:
        try:
            return raw_data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue

    # Last resort: decode as UTF-8, replacing any undecodable bytes
    return raw_data.decode('utf-8', errors='replace')


def parse_xml_root(xml_path):
    """Parse an XML file into an ElementTree root, tolerating any encoding.

    ElementTree/expat can only decode a handful of encodings itself and aborts
    with "multi-byte encodings are not supported" when an XML file (OPF/NCX)
    declares Shift-JIS, EUC-JP, etc. To avoid that, decode the bytes ourselves
    via read_file_with_encoding, strip the now-inaccurate encoding declaration
    (the string is already Unicode), and parse the resulting text.

    Args:
        xml_path: Path to the XML file.

    Returns:
        xml.etree.ElementTree.Element: the root element.

    Raises:
        ET.ParseError: if the XML is malformed (same as ET.parse).
    """
    text = read_file_with_encoding(xml_path)
    # Remove the encoding attribute from the XML declaration; keeping it would
    # make expat try (and fail) to reinterpret already-decoded Unicode bytes.
    text = re.sub(
        r'(<\?xml\b[^>]*?)\s+encoding\s*=\s*["\'][^"\']*["\']',
        r'\1',
        text,
        count=1,
        flags=re.I,
    )
    return ET.fromstring(text)


def find_opf_file(epub_path):
    """Find the OPF file by parsing META-INF/container.xml.

    EPUB standard requires container.xml to point to the OPF file.
    Falls back to searching for .opf files if container.xml is missing.
    """
    epub_path = Path(epub_path)
    container_xml = epub_path / 'META-INF' / 'container.xml'

    if container_xml.exists():
        try:
            root = parse_xml_root(container_xml)

            # Namespace for container.xml
            ns = {'container': 'urn:oasis:names:tc:opendocument:xmlns:container'}

            # Find rootfile element
            rootfile = root.find('.//container:rootfile', ns)
            if rootfile is None:
                # Try without namespace
                for elem in root.iter():
                    if elem.tag.endswith('rootfile') or elem.tag == 'rootfile':
                        rootfile = elem
                        break

            if rootfile is not None:
                opf_path = rootfile.get('full-path')
                if opf_path:
                    full_opf_path = epub_path / opf_path
                    if full_opf_path.exists():
                        return full_opf_path
        except ET.ParseError:
            pass

    # Fallback: search for .opf files
    opf_files = list(epub_path.glob('**/*.opf'))
    if opf_files:
        # Prefer content.opf or package.opf
        for opf in opf_files:
            if opf.name in ('content.opf', 'package.opf'):
                return opf
        return opf_files[0]

    raise FileNotFoundError(f"No OPF file found in {epub_path}")


def parse_opf(opf_path):
    """Parse the OPF file to get reading order and all manifest items.

    Returns:
        tuple: (metadata, spine_order, manifest_items)
        - metadata: dict with title, authors, etc.
        - spine_order: list of content file paths in reading order
        - manifest_items: dict of all manifest items {id: {href, media_type}}
    """
    opf_path = Path(opf_path)
    opf_dir = opf_path.parent

    root = parse_xml_root(opf_path)

    # Define namespaces
    ns = {
        'opf': 'http://www.idpf.org/2007/opf',
        'dc': 'http://purl.org/dc/elements/1.1/'
    }

    def find_with_fallback(parent, ns_path, local_name):
        """Try namespaced query first, fall back to local name search."""
        result = parent.find(ns_path, ns)
        if result is not None:
            return result
        for elem in parent.iter():
            if elem.tag.endswith('}' + local_name) or elem.tag == local_name:
                return elem
        return None

    def findall_with_fallback(parent, ns_path, local_name):
        """Try namespaced query first, fall back to local name search."""
        results = parent.findall(ns_path, ns)
        if results:
            return results
        fallback_results = []
        for elem in parent.iter():
            if elem.tag.endswith('}' + local_name) or elem.tag == local_name:
                fallback_results.append(elem)
        return fallback_results

    # Extract metadata
    metadata = {}
    title = find_with_fallback(root, './/dc:title', 'title')
    if title is not None and title.text:
        metadata['title'] = title.text

    creators = findall_with_fallback(root, './/dc:creator', 'creator')
    if creators:
        metadata['authors'] = [c.text for c in creators if c.text]

    publisher = find_with_fallback(root, './/dc:publisher', 'publisher')
    if publisher is not None and publisher.text:
        metadata['publisher'] = publisher.text

    date = find_with_fallback(root, './/dc:date', 'date')
    if date is not None and date.text:
        metadata['date'] = date.text

    # Get all manifest items with full info
    manifest_items = {}
    items = findall_with_fallback(root, './/opf:item', 'item')
    for item in items:
        item_id = item.get('id')
        href = item.get('href')
        media_type = item.get('media-type', '')

        if item_id and href:
            # URL decode the href (handles %20 for spaces, etc.)
            decoded_href = unquote(href)
            manifest_items[item_id] = {
                'href': decoded_href,
                'media_type': media_type,
                'full_path': opf_dir / decoded_href,
                'properties': item.get('properties', '')
            }

    # Get spine order
    spine_order = []
    itemrefs = findall_with_fallback(root, './/opf:itemref', 'itemref')
    for itemref in itemrefs:
        idref = itemref.get('idref')
        if idref and idref in manifest_items:
            spine_order.append(manifest_items[idref]['href'])

    return metadata, spine_order, manifest_items


def get_image_items(manifest_items):
    """Extract image items from manifest based on media-type or file extension."""
    images = {}
    for item_id, item_info in manifest_items.items():
        href = item_info['href']
        media_type = item_info['media_type']
        full_path = item_info['full_path']

        # Check by media type
        is_image = media_type.startswith('image/')

        # Also check by extension as fallback
        if not is_image:
            ext = Path(href).suffix.lower()
            is_image = ext in IMAGE_EXTENSIONS

        if is_image:
            images[item_id] = {
                'href': href,
                'full_path': full_path,
                'filename': Path(href).name
            }

    return images


def copy_manifest_images(manifest_items, images_output_dir):
    """Copy all manifest images into images_output_dir, disambiguating duplicates.

    Images are keyed by their resolved source path (not basename) so that images
    sharing a basename across folders each get their own output file and can be
    resolved to the correct one later (see resolve_image_filename).

    Returns:
        tuple: (image_src_map, image_rename_map, image_count, image_errors,
                renamed_count)
        - image_src_map: {resolved source path (str) -> output filename}
        - image_rename_map: {basename -> renamed filename} (fallback lookup)
    """
    image_items = get_image_items(manifest_items)
    image_src_map = {}
    image_rename_map = {}
    used_names = set()  # output filenames already claimed this run
    image_count = 0
    image_errors = 0
    renamed_count = 0  # count of files given a disambiguating suffix

    for item_id, img_info in image_items.items():
        src_path = img_info['full_path']
        if not src_path.exists():
            continue

        # Canonical source path is the identity key for this image
        try:
            resolved_src = str(src_path.resolve())
        except OSError:
            resolved_src = str(src_path)
        if resolved_src in image_src_map:
            continue  # same source file already copied

        original_filename = img_info['filename']

        # Pick a unique output filename, disambiguating duplicate basenames
        dest_name = original_filename
        if dest_name in used_names:
            stem = Path(original_filename).stem
            ext = Path(original_filename).suffix
            counter = 1
            dest_name = f"{stem}_{counter}{ext}"
            while dest_name in used_names:
                counter += 1
                dest_name = f"{stem}_{counter}{ext}"
            # Track the rename for basename fallback lookups
            image_rename_map[original_filename] = dest_name
            renamed_count += 1

        used_names.add(dest_name)
        image_src_map[resolved_src] = dest_name
        dest_path = images_output_dir / dest_name

        try:
            shutil.copy2(src_path, dest_path)
            image_count += 1
        except (OSError, IOError) as e:
            print(f"Warning: Failed to copy {original_filename}: {e}")
            image_errors += 1

    return image_src_map, image_rename_map, image_count, image_errors, renamed_count


def find_toc_file(manifest_items):
    """Find NCX (EPUB 2) or NAV (EPUB 3) file from manifest.

    Returns:
        tuple: (toc_type, full_path) where toc_type is 'ncx', 'nav', or None
    """
    # Look for NCX file (EPUB 2)
    for item_id, item_info in manifest_items.items():
        if item_info['media_type'] == 'application/x-dtbncx+xml':
            return ('ncx', item_info['full_path'])

    # Look for NAV file (EPUB 3): prefer the spec's properties="nav" marker
    # (a space-separated token list), then fall back to an id-substring guess.
    for item_id, item_info in manifest_items.items():
        if (item_info['media_type'] == 'application/xhtml+xml'
                and 'nav' in item_info.get('properties', '').split()):
            return ('nav', item_info['full_path'])

    for item_id, item_info in manifest_items.items():
        if 'nav' in item_id.lower() and item_info['media_type'] == 'application/xhtml+xml':
            return ('nav', item_info['full_path'])

    return (None, None)


def parse_ncx_toc(ncx_path):
    """Parse NCX file to extract top-level chapters.

    Returns list of dicts: [{title, src_file}, ...]
    Only returns top-level chapters (first entry per unique file).
    """
    ncx_path = Path(ncx_path)
    if not ncx_path.exists():
        return []

    try:
        root = parse_xml_root(ncx_path)
    except ET.ParseError:
        return []

    ns = {'ncx': 'http://www.daisy.org/z3986/2005/ncx/'}

    chapters = []
    seen_files = set()

    # Try with namespace first
    navpoints = root.findall('.//ncx:navPoint', ns)
    if not navpoints:
        # Fallback: try without namespace
        navpoints = root.findall('.//{http://www.daisy.org/z3986/2005/ncx/}navPoint')
    if not navpoints:
        # Last fallback: search for any navPoint tag
        navpoints = [elem for elem in root.iter() if elem.tag.endswith('navPoint') or elem.tag == 'navPoint']

    for navpoint in navpoints:
        # Find label text
        label = None
        for child in navpoint:
            tag_name = child.tag.split('}')[-1] if '}' in child.tag else child.tag
            if tag_name == 'navLabel':
                for subchild in child:
                    subtag = subchild.tag.split('}')[-1] if '}' in subchild.tag else subchild.tag
                    if subtag == 'text':
                        label = subchild.text
                        break

        # Find content src
        content_src = None
        for child in navpoint:
            tag_name = child.tag.split('}')[-1] if '}' in child.tag else child.tag
            if tag_name == 'content':
                content_src = child.get('src', '')
                break

        if label and content_src:
            src_file = extract_href_file(content_src)

            # Only keep first entry per file (top-level)
            if src_file and src_file not in seen_files:
                seen_files.add(src_file)
                chapters.append({
                    'title': label.strip(),
                    'src_file': src_file
                })

    return chapters


def parse_nav_toc(nav_path):
    """Parse EPUB 3 NAV file for top-level chapters.

    Returns same format as parse_ncx_toc.
    """
    nav_path = Path(nav_path)
    if not nav_path.exists():
        return []

    content = read_file_with_encoding(nav_path)
    soup = BeautifulSoup(content, 'html.parser')

    chapters = []
    seen_files = set()

    # Find <nav epub:type="toc"> or <nav id="toc">
    nav_elem = soup.find('nav', attrs={'epub:type': 'toc'})
    if not nav_elem:
        nav_elem = soup.find('nav', id='toc')
    if not nav_elem:
        # Fallback: first nav element
        nav_elem = soup.find('nav')

    if not nav_elem:
        return []

    # Get top-level list items only (direct children of first ol/ul)
    list_elem = nav_elem.find(['ol', 'ul'])
    if not list_elem:
        return []

    for li in list_elem.find_all('li', recursive=False):
        a_tag = li.find('a')
        if a_tag:
            href = a_tag.get('href', '')
            title = a_tag.get_text().strip()

            if href and title:
                src_file = extract_href_file(href)

                if src_file and src_file not in seen_files:
                    seen_files.add(src_file)
                    chapters.append({
                        'title': title,
                        'src_file': src_file
                    })

    return chapters


def extract_title_from_html(html_path):
    """Extract first heading (h1-h3) from HTML file."""
    html_path = Path(html_path)
    if not html_path.exists():
        return None
    content = read_file_with_encoding(html_path)
    soup = BeautifulSoup(content, 'html.parser')
    for tag in ['h1', 'h2', 'h3']:
        heading = soup.find(tag)
        if heading:
            return heading.get_text().strip()
    return None


def chapters_from_spine(spine_order, opf_dir):
    """Generate chapter list from spine items as fallback."""
    chapters = []
    for i, file_path in enumerate(spine_order):
        full_path = opf_dir / file_path
        # Try to extract title from first heading in file
        title = extract_title_from_html(full_path) or f"Chapter {i+1}"
        chapters.append({
            'title': title,
            'src_file': file_path
        })
    return chapters


def is_sub_entry(title):
    """Detect if a title represents a sub-entry (should be merged with previous chapter).

    Only returns True for CLEAR sub-entries:
    - ■, ●, ○, ◆, ◇, ・ prefixes (Japanese style sub-points)
    - Japanese numbered sections: １ text, ２ text (full-width numbers with space)

    Be conservative - if unsure, return False to avoid over-grouping.
    """
    title = title.strip()

    # Sub-entry marker prefixes (common in Japanese EPUBs)
    # These are very clear indicators of sub-sections
    if title and title[0] in '■●○◆◇・※★☆▶▷►▼▽◎□△▲':
        return True

    # Japanese-style numbered sub-sections (full-width numbers only)
    # These are typically "１ 収益力..." style entries in Japanese books
    # Only match full-width numbers to avoid false positives with English
    jp_sub_patterns = [
        r'^[０-９]+[\s　]',  # Full-width number + space: １ text
    ]

    for pattern in jp_sub_patterns:
        if re.search(pattern, title):
            return True

    return False


def group_chapters_by_hierarchy(raw_chapters):
    """Group sub-entries under main chapters.

    Takes a flat list of chapters and returns a grouped list where
    ONLY clear sub-entries (■, ●, full-width numbered) are merged.
    Ambiguous entries become their own chapters.

    Returns list of dicts: [{title, src_file, src_files: [file1, file2, ...]}, ...]
    """
    if not raw_chapters:
        return []

    grouped = []
    current_main = None

    for chapter in raw_chapters:
        title = chapter['title']
        src_file = chapter['src_file']

        if is_sub_entry(title):
            # Clear sub-entry - merge into current main chapter
            if current_main:
                if src_file not in current_main['src_files']:
                    current_main['src_files'].append(src_file)
            else:
                # No main chapter yet, start new one
                current_main = {
                    'title': title,
                    'src_file': src_file,
                    'src_files': [src_file]
                }
        else:
            # Not a clear sub-entry - start a new chapter
            # (This includes main chapters AND ambiguous entries)
            if current_main:
                grouped.append(current_main)
            current_main = {
                'title': title,
                'src_file': src_file,
                'src_files': [src_file]
            }

    # Don't forget the last chapter
    if current_main:
        grouped.append(current_main)

    return grouped


def expand_chapter_sources(chapters, spine_order):
    """Expand each chapter's src_files to include all spine files until next chapter.

    NCX/NAV only specifies where each chapter STARTS, but the actual content
    spans multiple spine files until the next chapter begins.
    """
    if not chapters or not spine_order:
        return chapters

    # Build a mapping of spine file -> index
    spine_index = {f: i for i, f in enumerate(spine_order)}

    # Find spine index for each chapter's start file
    chapter_starts = []
    for ch in chapters:
        # Use first src_file as the chapter start
        src_files = ch.get('src_files', [ch['src_file']])
        start_file = src_files[0] if src_files else ch['src_file']

        # Find in spine (try exact match first, then filename match)
        if start_file in spine_index:
            chapter_starts.append((spine_index[start_file], ch))
        else:
            # Try matching by filename only
            start_filename = Path(start_file).name
            matched = False
            for spine_file, idx in spine_index.items():
                if Path(spine_file).name == start_filename:
                    chapter_starts.append((idx, ch))
                    matched = True
                    break
            if not matched:
                # Can't find in spine, keep original
                chapter_starts.append((-1, ch))

    # Sort by spine index
    chapter_starts.sort(key=lambda x: x[0] if x[0] >= 0 else float('inf'))

    # Expand src_files for each chapter
    expanded = []
    for i, (start_idx, ch) in enumerate(chapter_starts):
        if start_idx < 0:
            # Not found in spine, keep original
            expanded.append(ch)
            continue

        # For first chapter, include any files before it (titlepage, copyright, etc.)
        if i == 0:
            actual_start = 0
        else:
            actual_start = start_idx

        # Find end index (start of next chapter or end of spine)
        if i + 1 < len(chapter_starts) and chapter_starts[i + 1][0] >= 0:
            end_idx = chapter_starts[i + 1][0]
        else:
            end_idx = len(spine_order)

        # Collect all spine files for this chapter
        all_src_files = spine_order[actual_start:end_idx]

        expanded.append({
            'title': ch['title'],
            'src_file': ch['src_file'],
            'src_files': all_src_files
        })

    return expanded


def get_chapters_from_toc(manifest_items, opf_dir, spine_order):
    """Get chapter list from TOC, with spine fallback.

    Returns list of dicts: [{title, src_file, src_files}, ...]
    """
    toc_type, toc_path = find_toc_file(manifest_items)

    raw_chapters = None
    if toc_type == 'ncx' and toc_path:
        raw_chapters = parse_ncx_toc(toc_path)
    elif toc_type == 'nav' and toc_path:
        raw_chapters = parse_nav_toc(toc_path)

    if raw_chapters:
        # Group sub-entries under main chapters
        grouped = group_chapters_by_hierarchy(raw_chapters)
        chapters = grouped if grouped else raw_chapters
        # Expand to include all spine files between chapter boundaries
        return expand_chapter_sources(chapters, spine_order)

    # Fallback: use spine items
    return chapters_from_spine(spine_order, opf_dir)


def sanitize_filename(title, max_length=50):
    """Convert chapter title to safe filename."""
    # Remove/replace invalid characters
    safe = re.sub(r'[<>:"/\\|?*]', '', title)
    safe = re.sub(r'\s+', '_', safe)
    # Remove leading/trailing underscores
    safe = safe.strip('_')
    # Truncate if too long
    if len(safe) > max_length:
        safe = safe[:max_length].rstrip('_')
    return safe or 'untitled'


def find_content_for_file(src_file, chapter_contents):
    """Find content for a source file, handling path differences."""
    if src_file in chapter_contents:
        return chapter_contents[src_file]

    # Try matching by filename only
    src_filename = Path(src_file).name
    for key, value in chapter_contents.items():
        if Path(key).name == src_filename:
            return value

    return None


def is_short_or_numeric_title(title):
    """Check if a title is too short or just a number (needs enhancement)."""
    title = title.strip()
    # Just a number (1, 2, 10, etc.)
    if re.match(r'^[0-9]+$', title):
        return True
    # Very short titles (1-2 characters) - likely incomplete
    if len(title) <= 2:
        return True
    return False


def extract_title_from_markdown(content):
    """Extract the first meaningful heading from markdown content.

    Skips very short or numeric-only headings to find descriptive titles.
    """
    # Look for all markdown headings at the start of a line
    # Match # Heading, ## Heading, or ### Heading
    matches = re.findall(r'^#+\s+(.+)$', content, re.MULTILINE)
    for match in matches:
        title = match.strip()
        # Skip short/numeric titles (the ones we're trying to improve)
        if not is_short_or_numeric_title(title):
            return title
    return None


def write_chapter_files(chapters, chapter_contents, chapters_dir, book_name):
    """Write individual chapter markdown files."""
    written_count = 0
    for i, chapter in enumerate(chapters, 1):
        title = chapter['title']

        # Get list of source files for this chapter
        src_files = chapter.get('src_files', [chapter['src_file']])

        # Collect content from all source files
        all_content = []
        for src_file in src_files:
            content_list = find_content_for_file(src_file, chapter_contents)
            if content_list:
                all_content.extend(content_list)

        if not all_content:
            continue

        # Combine content for this chapter
        content = '\n\n'.join(all_content)

        # If title is too short (like just "1"), try to extract better title from content
        if is_short_or_numeric_title(title):
            extracted_title = extract_title_from_markdown(content)
            if extracted_title:
                # Combine original title with extracted title: "1" + "Analyzing..." -> "1_Analyzing..."
                filename_title = f"{title}_{extracted_title}"
            else:
                filename_title = title
        else:
            filename_title = title

        # Build filename: 01_chapter_title.md
        safe_title = sanitize_filename(filename_title)
        filename = f"{i:02d}_{safe_title}.md"

        # Add chapter title as header if not already present
        content_stripped = content.strip()
        if not content_stripped.startswith("# "):
            chapter_md = f"# {filename_title}\n\n{content}"
        else:
            chapter_md = content

        # Fix image paths (chapters/ is one level deeper)
        chapter_md = chapter_md.replace('images/', '../images/')

        # Write file
        chapter_path = chapters_dir / filename
        with open(chapter_path, 'w', encoding='utf-8') as f:
            f.write(chapter_md)
        written_count += 1

    print(f"Created {written_count} chapter files in {chapters_dir}")


# Tags html2text can't represent are protected across conversion with these
# placeholder markers, then restored afterward. Each entry is
# (find_target, start_marker, end_marker, open_tag, close_tag); the preserve and
# restore passes share this table so the two halves cannot drift apart.
_PLACEHOLDER_TAGS = [
    ('u',          '⟦ULINE_S⟧', '⟦ULINE_E⟧', '<u>',     '</u>'),
    ('sub',        '⟦SUB_S⟧',   '⟦SUB_E⟧',   '<sub>',   '</sub>'),
    ('sup',        '⟦SUP_S⟧',   '⟦SUP_E⟧',   '<sup>',   '</sup>'),
    (['del', 's'], '⟦DEL_S⟧',   '⟦DEL_E⟧',   '~~',      '~~'),
    ('small',      '⟦SMALL_S⟧', '⟦SMALL_E⟧', '<small>', '</small>'),
    ('mark',       '⟦MARK_S⟧',  '⟦MARK_E⟧',  '<mark>',  '</mark>'),
]


def convert_to_tag(elem, new_tag_name, soup):
    """Convert an element to a new tag type, preserving content."""
    block_tags = {'div', 'p', 'li', 'ul', 'ol', 'blockquote', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'article', 'section', 'header', 'footer', 'nav', 'aside', 'main'}

    if elem.name == 'span':
        # For span elements, just change the tag name directly
        elem.name = new_tag_name
    else:
        # Check if this block element contains other block elements
        has_block_children = any(
            hasattr(child, 'name') and child.name in block_tags
            for child in elem.children
        )

        if has_block_children:
            # For block elements containing other block elements (e.g., <div class="bold"><p>text</p></div>)
            # We need to apply the styling to the inner block elements instead
            # Otherwise <strong><p>text</p></strong> is invalid HTML
            for child in list(elem.children):
                if hasattr(child, 'name') and child.name in block_tags:
                    # Recursively apply to inner block element
                    convert_to_tag(child, new_tag_name, soup)
                elif hasattr(child, 'name'):
                    # Inline element - wrap in new tag
                    new_tag = soup.new_tag(new_tag_name)
                    child.wrap(new_tag)
                elif str(child).strip():
                    # Non-empty text node - we can't easily wrap these when mixed with block elements
                    # This is rare, but if it happens, the text won't be styled
                    pass
        else:
            # For block-level elements with only inline/text content, wrap content in new tag
            # This preserves block structure: <p class="bold">text</p> -> <p><strong>text</strong></p>
            new_tag = soup.new_tag(new_tag_name)
            # Move all children to the new tag
            for child in list(elem.children):
                if hasattr(child, 'extract'):
                    new_tag.append(child.extract())
                else:
                    # Fallback for any edge cases
                    new_tag.append(str(child))
            elem.clear()
            elem.append(new_tag)


def _normalize_list_styles(soup):
    """Convert <ol> to <ul> where CSS hides the list numbering (common in TOCs)."""
    # Check for CSS rule "list-style-type: none" and convert those <ol> to <ul>
    has_list_style_none = False
    for style_tag in soup.find_all('style'):
        if style_tag.string and 'list-style-type' in style_tag.string and 'none' in style_tag.string:
            has_list_style_none = True
            break

    if has_list_style_none:
        # Convert all <ol> to <ul> since numbers should be hidden
        for ol in soup.find_all('ol'):
            ol.name = 'ul'
    else:
        # Check for inline style on individual <ol> elements
        for ol in soup.find_all('ol'):
            style = ol.get('style', '')
            if 'list-style-type' in style and 'none' in style:
                ol.name = 'ul'


def _normalize_styling_classes(soup):
    """Rewrite CSS-class / inline-style styling to real HTML tags.

    Driven by a table so the many near-identical rules stay in sync. ORDER
    MATTERS (BeautifulSoup mutates in place), so the rules run top-to-bottom.

    method:
      'convert' -> convert_to_tag(elem, target)  (handles span & block elements)
      'span'    -> rename only if elem is a <span>
      'block'   -> rename only if elem is div/p/span/section
      'unwrap'  -> drop the <span> wrapper, keep its text
    """
    def _apply_rename(elem, target, method):
        if method == 'convert':
            convert_to_tag(elem, target, soup)
        elif method == 'span':
            if elem.name == 'span':
                elem.name = target
        elif method == 'block':
            if elem.name in ('div', 'p', 'span', 'section'):
                elem.name = target
        elif method == 'unwrap':
            if elem.name == 'span':
                elem.unwrap()

    def _rename_class(classes, target, method, dedupe=False):
        seen = set() if dedupe else None
        for class_name in classes:
            for elem in soup.find_all(class_=class_name):
                if dedupe:
                    if id(elem) in seen:
                        continue
                    seen.add(id(elem))
                _apply_rename(elem, target, method)

    def _rename_style(pattern, target, method):
        for elem in soup.find_all(style=re.compile(pattern, re.I)):
            _apply_rename(elem, target, method)

    # Bold: .bold/.gothic/.gfont (gothic/sans-serif = emphasis in Japanese EPUBs).
    # Dedupe so an element with several bold classes is converted only once.
    _rename_class(['bold', 'gothic1', 'gothic', 'gfont'], 'strong', 'convert', dedupe=True)
    _rename_class(['italic'], 'em', 'convert')
    _rename_class(['sesame'], 'strong', 'convert')  # Japanese sesame dots -> bold
    # Underline (.em-line etc.; 'marker' = border-bottom underline in some EPUBs)
    _rename_class(['em-line', 'em-line-outside', 'underline', 'marker'], 'u', 'convert', dedupe=True)
    # Sub/superscript by class then by inline vertical-align style
    _rename_class(['sub', 'sub1', 'subscript', 'italic1'], 'sub', 'span')
    _rename_class(['super', 'super1', 'superscript', 'sup'], 'sup', 'span')
    _rename_style(r'vertical-align:\s*sub', 'sub', 'span')
    _rename_style(r'vertical-align:\s*super', 'sup', 'span')
    # Strikethrough by class then by text-decoration style
    _rename_class(['strike', 'strikethrough', 'del', 's', 'line-through'], 'del', 'span')
    _rename_style(r'text-decoration:\s*line-through', 'del', 'span')
    # Monospace/code by class then by font-family style (html2text -> backticks)
    _rename_class(['code', 'mono', 'monospace', 'tt', 'courier', 'fixed'], 'code', 'span')
    _rename_style(r'font-family:\s*monospace', 'code', 'span')
    # Small caps -> bold (Markdown has no small caps), by class then by style
    _rename_class(['smallcaps', 'sc', 'small-caps', 'smcp'], 'strong', 'convert')
    _rename_style(r'font-variant:\s*small-caps', 'strong', 'convert')
    _rename_class(['highlight', 'mark', 'highlighted', 'bg-yellow'], 'mark', 'span')
    _rename_class(['spaced', 'tenten', 'tracking', 'letterspaced'], 'strong', 'convert')  # letter-spacing -> bold
    # Smaller text -> <small>, by class then by font-size style
    _rename_class(['small', 'caption', 'footnote', 'smaller', 'fine-print'], 'small', 'span')
    _rename_style(r'font-size:\s*smaller', 'small', 'span')
    _rename_class(['bouten', 'emphasis-dot', 'boten', 'dot-emphasis'], 'strong', 'convert')  # Japanese bouten -> bold
    _rename_class(['warichu', 'waricyu', 'inline-note'], None, 'unwrap')  # keep text, drop wrapper
    # Blockquote classes -> <blockquote> (html2text -> "> " quotes)
    _rename_class(['quote', 'blockquote', 'pullquote', 'excerpt', 'citation', 'epigraph'], 'blockquote', 'block')

    # Code block classes - convert to <pre><code> structure
    # html2text will convert these to code blocks
    codeblock_classes = ['codeblock', 'pre', 'source-code', 'listing', 'program', 'syntax']
    for class_name in codeblock_classes:
        for elem in soup.find_all(class_=class_name):
            if elem.name in ['div', 'p', 'span']:
                # Wrap content in <code> and change to <pre>
                code_tag = soup.new_tag('code')
                for child in list(elem.children):
                    if hasattr(child, 'extract'):
                        code_tag.append(child.extract())
                    else:
                        code_tag.append(str(child))
                elem.clear()
                elem.append(code_tag)
                elem.name = 'pre'


def _process_gaiji(soup):
    """Convert gaiji (外字) italic-marker image pairs (tm/tu) into <em> spans."""
    # These use small images like tm2.png (start) and tu2.png (end) to mark italic text
    # Structure: <span><img src="tm2.png"/></span><span>text</span><span><img src="tu2.png"/></span>
    # Convert to: <em>text</em>
    gaiji_start_markers = ['tm2.png', 'tm.png']  # Italic start markers
    gaiji_end_markers = ['tu2.png', 'tu.png']    # Italic end markers

    def is_gaiji_marker(img, markers):
        """Check if an image is a gaiji marker."""
        if img is None:
            return False
        # Check if the element has been decomposed or is invalid
        try:
            src = img.get('src', '')
        except (AttributeError, TypeError):
            return False
        return any(marker in src for marker in markers)

    # Find all gaiji start markers and process them
    processed_start_imgs = set()
    for start_img in list(soup.find_all('img')):
        if start_img is None:
            continue
        if id(start_img) in processed_start_imgs:
            continue
        if not is_gaiji_marker(start_img, gaiji_start_markers):
            continue

        processed_start_imgs.add(id(start_img))

        # Get the parent element of the start marker
        start_parent = start_img.parent

        # Traverse sibling elements to find text and end marker
        current = start_parent.next_sibling if start_parent else None
        text_elements = []
        end_parent = None

        while current:
            # Check if this element contains an end marker
            if hasattr(current, 'find'):
                img = current.find('img')
                if img and is_gaiji_marker(img, gaiji_end_markers):
                    end_parent = current
                    break
                elif img and is_gaiji_marker(img, gaiji_start_markers):
                    # Another start marker - stop here
                    break

            # Collect elements between markers (could be text spans)
            text_elements.append(current)
            current = current.next_sibling

        if end_parent and text_elements:
            # Create <em> tag with collected content
            em_tag = soup.new_tag('em')

            # Extract content from text elements
            for elem in text_elements:
                if hasattr(elem, 'get_text'):
                    # It's a tag - get its text content
                    text = elem.get_text()
                    if text.strip():
                        em_tag.append(text)
                    elem.decompose()
                elif hasattr(elem, 'extract'):
                    # NavigableString
                    extracted = elem.extract()
                    if str(extracted).strip():
                        em_tag.append(extracted)

            # Replace start parent with em tag, remove end parent
            if start_parent and em_tag.get_text().strip():
                start_parent.replace_with(em_tag)
            elif start_parent:
                start_parent.decompose()
            end_parent.decompose()
        else:
            # No matching end marker found, just remove the start marker
            if start_parent:
                # Keep the parent but remove the image
                start_img.decompose()

    # Remove any remaining gaiji markers that weren't matched
    for img in list(soup.find_all('img')):
        if is_gaiji_marker(img, gaiji_start_markers) or is_gaiji_marker(img, gaiji_end_markers):
            img.decompose()


def _rewrite_image_srcs(soup, image_rename_map, image_src_map, base_dir):
    """Point <img>/<svg image> sources at images/… and tag gaiji/sizing images."""
    # Pre-process: Fix image src attributes in HTML before conversion
    # Also extract sizing info and mark special images
    for img in soup.find_all('img'):
        src = img.get('src', '')
        if src and not re.match(r'(https?://|data:)', src):
            src = unquote(src)
            # Resolve by source path when possible so images that share a
            # basename in different folders are not cross-wired
            final_filename = resolve_image_filename(
                src, base_dir, image_src_map, image_rename_map)
            img['src'] = f'images/{final_filename}'

        # Check for gaiji class (inline symbol images that should be 1em sized)
        # Variants: gaiji, gaiji-wide, gaiji-icon
        img_classes = img.get('class', [])
        if isinstance(img_classes, str):
            img_classes = img_classes.split()
        gaiji_classes = {'gaiji', 'gaiji-wide', 'gaiji-icon'}

        current_alt = img.get('alt', '')
        markers = []

        if gaiji_classes & set(img_classes):
            # Mark as gaiji for later processing
            markers.append('⟦GAIJI⟧')
        else:
            # Extract sizing info from HTML attributes, inline styles, and CSS classes
            sizing = extract_image_sizing(img)
            if sizing:
                # Encode sizing in alt text with marker
                markers.append(f'⟦SIZE:{sizing}⟧')

        if markers:
            img['alt'] = ''.join(markers) + current_alt

    # Handle SVG images with xlink:href (common in EPUB cover pages)
    for image_elem in soup.find_all('image'):
        # Check both xlink:href and href attributes
        href = image_elem.get('xlink:href') or image_elem.get('href', '')
        if href and not re.match(r'(https?://|data:)', href):
            href = unquote(href)
            final_filename = resolve_image_filename(
                href, base_dir, image_src_map, image_rename_map)
            # Convert SVG image to regular img tag for markdown conversion
            img_tag = soup.new_tag('img')
            img_tag['src'] = f'images/{final_filename}'
            img_tag['alt'] = ''
            image_elem.replace_with(img_tag)


def _unwrap_internal_links(soup):
    """Remove internal EPUB <a> links (footnote/cross-refs), keeping their text."""
    for a_tag in list(soup.find_all('a')):
        href = a_tag.get('href', '')
        # Check if it's an internal EPUB link (not external URL)
        if href and not href.startswith(('http://', 'https://', 'mailto:')):
            # It's an internal link - unwrap it (keep content, remove <a> tag)
            a_tag.unwrap()


def _preserve_unsupported_tags(soup):
    """Wrap tags html2text can't emit in placeholder markers (see _PLACEHOLDER_TAGS)."""
    # Preserve tags html2text can't represent (underline/sub/sup/strike/small/
    # mark): wrap their content in placeholder markers and drop the tag. The
    # markers survive html2text and are restored below.
    for find_target, start_marker, end_marker, _open, _close in _PLACEHOLDER_TAGS:
        for tag in soup.find_all(find_target):
            tag.insert(0, start_marker)
            tag.append(end_marker)
            tag.unwrap()


def _run_html2text(soup):
    """Configure html2text and convert the (pre-processed) soup to markdown."""
    from html2text import HTML2Text  # imported lazily; only the markdown path needs it
    h = HTML2Text()
    h.body_width = 0  # Don't wrap lines
    h.ignore_links = False
    h.ignore_images = False
    h.ignore_emphasis = False
    h.unicode_snob = True
    h.skip_internal_links = False
    h.ignore_tables = False  # Ensure tables are converted
    h.bypass_tables = False  # Process tables as markdown

    # Convert to markdown
    return h.handle(str(soup))


def _restore_placeholders(markdown):
    """Restore placeholder markers to their real tags (same table as preserve)."""
    for _find, start_marker, end_marker, open_tag, close_tag in _PLACEHOLDER_TAGS:
        markdown = restore_placeholder_tags(markdown, start_marker, end_marker,
                                            open_tag, close_tag)
    return markdown


def fix_orphaned_bold_markers(line):
    """Fix orphaned ** markers in a line by tracking open/close state."""
    if '**' not in line:
        return line

    markers = [(m.start(), m.end()) for m in re.finditer(r'\*\*', line)]
    if len(markers) % 2 == 0:
        return line  # Even number, assume all paired

    result = []
    last_end = 0
    is_open = False

    for i, (start, end) in enumerate(markers):
        result.append(line[last_end:start])
        before = line[max(0, start-1):start]
        after = line[end:end+1] if end < len(line) else ''

        if not is_open:
            if after and after not in ' \t\n':
                result.append('**')
                is_open = True
        else:
            if before and before not in ' \t\n':
                result.append('**')
                is_open = False

        last_end = end

    result.append(line[last_end:])

    if is_open:
        new_result = []
        found_last = False
        for part in reversed(result):
            if part == '**' and not found_last:
                found_last = True
                continue
            new_result.insert(0, part)
        result = new_result

    return ''.join(result)


def _fix_bold_markers(markdown):
    """Clean up bold (**) marker artifacts from fragmented source HTML."""
    # Fix bold/italic marker formatting issues from fragmented HTML
    # Remove empty bold markers
    markdown = re.sub(r'\*\*\s*\*\*', ' ', markdown)

    # Fix adjacent bold markers (end of one + start of another with no space)
    markdown = re.sub(r'\*{4,}', ' ', markdown)

    # Apply to all lines with potential issues
    lines = markdown.split('\n')
    for i, line in enumerate(lines):
        if '**' in line:
            lines[i] = fix_orphaned_bold_markers(line)
    markdown = '\n'.join(lines)

    # Final cleanup: merge adjacent bold phrases
    markdown = re.sub(r'\*\*([^*\n]+)\*\*\s+\*\*([^*\n]+)\*\*', r'**\1 \2**', markdown)
    return markdown


def _fix_image_paths(markdown, image_rename_map, images_dir, auto_scale_width, zoom_ratio):
    """Normalize markdown image refs to images/… and apply gaiji/size/zoom styling."""
    def fix_image_path(match):
        alt_text = match.group(1)
        image_path = match.group(2)

        # Check for special markers in alt text
        is_gaiji = False
        extracted_style = None

        # Check for gaiji marker
        if alt_text.startswith('⟦GAIJI⟧'):
            is_gaiji = True
            alt_text = alt_text[7:]  # Remove the marker

        # Check for size marker: ⟦SIZE:style_string⟧
        size_match = re.match(r'⟦SIZE:([^⟧]+)⟧(.*)', alt_text)
        if size_match:
            extracted_style = size_match.group(1)
            alt_text = size_match.group(2)

        # Skip absolute URLs (http://, https://, data:)
        if re.match(r'(https?://|data:)', image_path):
            return match.group(0)

        # Determine the final image path
        if image_path.startswith('images/'):
            final_path = image_path
        else:
            # URL decode the path
            image_path = unquote(image_path)
            # Extract just the filename
            original_filename = Path(image_path).name
            # Use renamed filename if exists
            final_filename = image_rename_map.get(original_filename, original_filename)
            # Build new path pointing to images/ folder
            final_path = f'images/{final_filename}'

        # Determine the style to apply (priority order)
        # 1. Gaiji images get special 1em sizing
        # 2. Extracted style from HTML attributes/classes
        # 3. Auto-scale based on actual image dimensions
        # 4. Zoom ratio if < 100%
        # 5. No styling (plain markdown)

        if is_gaiji:
            return f'<img src="{final_path}" alt="{alt_text}" style="height:1em;vertical-align:text-bottom;"/>'
        elif extracted_style:
            return f'<img src="{final_path}" alt="{alt_text}" style="{extracted_style}"/>'
        elif auto_scale_width and images_dir:
            # Try to read actual image dimensions and apply smart scaling
            image_filename = final_path.replace('images/', '')
            full_image_path = images_dir / image_filename
            dimensions = get_image_dimensions(full_image_path)
            if dimensions:
                width, height = dimensions
                smart_style = calculate_smart_scale(width, height, auto_scale_width)
                if smart_style:
                    return f'<img src="{final_path}" alt="{alt_text}" style="{smart_style}"/>'
            # No scaling needed, fall through to zoom/plain
            if zoom_ratio < 100:
                return f'<img src="{final_path}" alt="{alt_text}" style="zoom:{zoom_ratio}%;"/>'
            return f'![{alt_text}]({final_path})'
        elif zoom_ratio < 100:
            return f'<img src="{final_path}" alt="{alt_text}" style="zoom:{zoom_ratio}%;"/>'
        else:
            return f'![{alt_text}]({final_path})'

    # Match all markdown image patterns
    return re.sub(r'!\[(.*?)\]\(([^)]+)\)', fix_image_path, markdown)


def html_to_markdown(html_content, zoom_ratio=100, image_rename_map=None,
                     images_dir=None, auto_scale_width=None,
                     image_src_map=None, base_dir=None):
    """Convert HTML content to markdown.

    Args:
        html_content: HTML content to convert
        zoom_ratio: Image display size percentage (1-100)
        image_rename_map: Dict mapping original basenames to renamed filenames
                         (basename fallback for duplicate image names)
        images_dir: Path to images directory (for auto-scaling)
        auto_scale_width: Max width for auto-scaling (None to disable)
        image_src_map: Dict mapping resolved source paths to output filenames.
                       Used to resolve image references by path (avoids
                       cross-wiring images that share a basename).
        base_dir: Directory of the HTML file being converted, used to resolve
                  relative image references against image_src_map.
    """
    if image_rename_map is None:
        image_rename_map = {}

    soup = BeautifulSoup(html_content, 'html.parser')

    # Pre-process the parsed HTML into html2text-friendly markup, then convert
    # and post-process the markdown. Each phase is a separately testable helper.
    _normalize_list_styles(soup)
    _normalize_styling_classes(soup)
    _process_gaiji(soup)
    _rewrite_image_srcs(soup, image_rename_map, image_src_map, base_dir)
    _unwrap_internal_links(soup)
    _preserve_unsupported_tags(soup)
    markdown = _run_html2text(soup)
    markdown = _restore_placeholders(markdown)
    markdown = _fix_bold_markers(markdown)
    markdown = _fix_image_paths(markdown, image_rename_map, images_dir,
                                auto_scale_width, zoom_ratio)
    return markdown


def extract_epub(epub_file, extract_dir):
    """Extract an EPUB file to a directory."""
    epub_file = Path(epub_file)
    extract_dir = Path(extract_dir)

    if not epub_file.exists():
        raise FileNotFoundError(f"EPUB file not found: {epub_file}")

    if not zipfile.is_zipfile(epub_file):
        raise ValueError(f"Not a valid EPUB/ZIP file: {epub_file}")

    extract_dir.mkdir(parents=True, exist_ok=True)

    try:
        with zipfile.ZipFile(epub_file, 'r') as zf:
            # Guard against Zip-Slip: refuse any member that would resolve
            # outside extract_dir (belt-and-suspenders over CPython's own
            # stripping of leading slashes / .. components).
            extract_root = extract_dir.resolve()
            for member in zf.infolist():
                dest = (extract_dir / member.filename).resolve()
                if not dest.is_relative_to(extract_root):
                    raise ValueError(
                        f"Unsafe path in EPUB (Zip-Slip): {member.filename}")
            zf.extractall(extract_dir)
    except zipfile.BadZipFile as e:
        raise ValueError(f"Corrupted EPUB/ZIP file: {epub_file} - {e}")

    return extract_dir


def convert_epub_to_markdown(epub_source, output_dir, zoom_ratio=100, skip_titlepage=True,
                             split_chapters=False, auto_scale_width=None):
    """Convert an EPUB file or extracted directory to markdown.

    Args:
        epub_source: Path to .epub file or extracted directory
        output_dir: Directory to write output (will contain <name>.md and images/)
        zoom_ratio: Image display size percentage (1-100). Default: 100
        skip_titlepage: Skip files containing 'titlepage' in the path. Default: True
        split_chapters: Also export individual chapter files. Default: False
        auto_scale_width: Max width for auto-scaling images (None to disable)

    Returns:
        Path to the created markdown file
    """
    epub_source = Path(epub_source)
    output_dir = Path(output_dir)

    # Determine if we need to extract
    temp_dir = None
    if epub_source.is_file() and epub_source.suffix.lower() == '.epub':
        # Extract to temp directory
        temp_dir = tempfile.mkdtemp(prefix='epub_extract_')
        print(f"Extracting {epub_source.name}...")
        epub_path = extract_epub(epub_source, temp_dir)
        book_name = epub_source.stem
    elif epub_source.is_dir():
        epub_path = epub_source
        # Strip .epub suffix from directory names if present
        book_name = epub_source.name
        if book_name.lower().endswith('.epub'):
            book_name = book_name[:-5]  # Remove '.epub' suffix
    else:
        raise ValueError(f"Invalid EPUB source: {epub_source}")

    try:
        # Find and parse the OPF file
        opf_file = find_opf_file(epub_path)
        opf_dir = opf_file.parent

        # Safely get relative path for display
        try:
            opf_relative = opf_file.relative_to(epub_path)
        except ValueError:
            opf_relative = opf_file.name
        print(f"Found OPF file: {opf_relative}")

        metadata, spine_order, manifest_items = parse_opf(opf_file)

        # Warn if no content files found
        if not spine_order:
            print("Warning: No content files found in spine. The EPUB may be malformed.")

        # Create output directory
        output_dir.mkdir(parents=True, exist_ok=True)

        # Output file path
        output_file = output_dir / f"{book_name}.md"
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

        # Get chapter structure if splitting
        chapters = None
        chapter_contents = {}  # src_file -> list of markdown content
        chapters_dir = None
        if split_chapters:
            chapters = get_chapters_from_toc(manifest_items, opf_dir, spine_order)
            chapters_dir = output_dir / 'chapters'
            chapters_dir.mkdir(exist_ok=True)

        # Start building the markdown document
        markdown_content = []

        # Add title and metadata
        if 'title' in metadata:
            markdown_content.append(f"# {metadata['title']}\n")

        if 'authors' in metadata:
            markdown_content.append(f"**Authors:** {', '.join(metadata['authors'])}\n")

        if 'publisher' in metadata:
            markdown_content.append(f"**Publisher:** {metadata['publisher']}\n")

        if 'date' in metadata:
            markdown_content.append(f"**Date:** {metadata['date']}\n")

        markdown_content.append("\n---\n")

        # Process each file in spine order
        print(f"Processing {len(spine_order)} content files...")
        for i, file_path in enumerate(spine_order, 1):
            # Skip titlepage if configured
            if skip_titlepage and 'titlepage' in file_path.lower():
                continue

            # Resolve path relative to OPF directory
            full_path = opf_dir / file_path

            if not full_path.exists():
                print(f"Warning: {file_path} not found, skipping...")
                continue

            # Read and convert HTML to markdown
            html_content = read_file_with_encoding(full_path)
            md = html_to_markdown(html_content, zoom_ratio, image_rename_map,
                                  images_output_dir, auto_scale_width,
                                  image_src_map=image_src_map,
                                  base_dir=full_path.parent)

            # Normalize line endings and clean up whitespace
            md = md.replace('\r\n', '\n').replace('\r', '\n')
            md = clean_whitespace_lines(md)

            # Clean up nested bold/italic markers (e.g., ****text**** -> **text**)
            # Use [^*\n]+ to avoid matching across lines
            md = re.sub(r'\*{4,}([^*\n]+)\*{4,}', r'**\1**', md)
            md = re.sub(r'_{4,}([^_\n]+)_{4,}', r'_\1_', md)

            # Clean up adjacent bold markers: **text****text** -> **text text**
            md = re.sub(r'\*\*\*\*', ' ', md)

            # Clean up orphaned bold markers at end: **text**more** -> **text more**
            # Use [^*\n]+ to avoid matching across lines
            md = re.sub(r'\*\*([^*\n]+)\*\*([^*\s][^*\n]*)\*\*', r'**\1\2**', md)

            # Strip trailing whitespace from each content block
            md = md.strip()

            markdown_content.append(md)

            # Store for chapter splitting
            if split_chapters:
                if file_path not in chapter_contents:
                    chapter_contents[file_path] = []
                chapter_contents[file_path].append(md)

            if i % 10 == 0:
                print(f"Processed {i}/{len(spine_order)} files...")

        # Write the final markdown file
        final_markdown = '\n\n'.join(markdown_content)
        final_markdown = clean_whitespace_lines(final_markdown)

        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(final_markdown)

        print("\nConversion complete!")
        print(f"Markdown file: {output_file}")
        print(f"Images directory: {images_output_dir}")
        print(f"Total size: {len(final_markdown)} characters")

        # Write individual chapter files
        if split_chapters and chapters:
            write_chapter_files(chapters, chapter_contents, chapters_dir, book_name)

        return output_file

    finally:
        # Clean up temp directory
        if temp_dir:
            shutil.rmtree(temp_dir, ignore_errors=True)


def find_epub_files(directory):
    """Find all .epub files in a directory."""
    directory = Path(directory)
    return sorted(directory.glob('*.epub'))


def _zoom_arg(value):
    """argparse type for --zoom: an integer percentage in 1..100."""
    try:
        zoom = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"must be a number, got '{value}'")
    if zoom < 1 or zoom > 100:
        raise argparse.ArgumentTypeError(f"must be between 1 and 100, got {zoom}")
    return zoom


def main():
    """Main entry point with CLI argument parsing."""
    parser = argparse.ArgumentParser(
        prog='epub_to_markdown.py',
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
    # Optional WIDTH; a bare --auto-scale means the default 800px. The value is
    # captured as a string so that a source path argparse greedily consumes
    # (e.g. "--auto-scale book.epub") can be handed back to `sources` below.
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
        # isdecimal (not isdigit): guarantees int() accepts it — some digit-like
        # chars (e.g. '²') satisfy isdigit() but make int() raise.
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
        current_dir = Path('.')
        epub_files = find_epub_files(current_dir)
        if not epub_files:
            print("No EPUB files found in current directory.")
            print("\nUsage: python3 epub_to_markdown.py [options] [epub_file...]")
            print("       python3 epub_to_markdown.py --help")
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
            # Determine output directory
            if output_dir:
                # Use specified output directory with book name subfolder
                if source_path.suffix.lower() == '.epub':
                    book_output_dir = output_dir / source_path.stem
                else:
                    book_output_dir = output_dir / source_path.name
            else:
                # Create subfolder in current directory named after the book
                if source_path.suffix.lower() == '.epub':
                    book_output_dir = Path('.') / source_path.stem
                else:
                    book_output_dir = Path('.') / source_path.name

            convert_epub_to_markdown(
                source_path,
                book_output_dir,
                zoom_ratio=zoom_ratio,
                skip_titlepage=skip_titlepage,
                split_chapters=split_chapters,
                auto_scale_width=auto_scale_width
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
