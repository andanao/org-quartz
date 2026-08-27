#!/usr/bin/env python3
"""Filter and export org files to Hugo-compatible markdown."""

import re
import shutil
import subprocess
import tempfile
import urllib.parse
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import diagrams

PERSONAL_DIR = Path.home() / "git/org/personal"
K2_DIR = Path.home() / "git/org/k2"
EMACS_CONFIG = Path.home() / "git/emacs/readme.org"  # Public emacs config
KONFIG_CONFIG = Path.home() / "git/konfig/readme.org"  # Work config (combined only)
CONTENT_DIR = Path(__file__).parent / "content"
EXPORT_EL = Path(__file__).parent / "export.el"

EXCLUDE_TAGS = {"private", "monthly", "ppl", "yof", "love", "cui"}  # Tags that exclude a file from publishing
EXCLUDE_DIRS = {"daily", ".git"}  # Keep data/ for attachments
IMG_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp"}

# `[[file:img/x.svg]]`, `[[./img/x.svg][alt]]` - a relative path to an image,
# as opposed to an absolute one, a URL, or an `id:`/`attachment:` link.
REL_IMG_LINK_RE = re.compile(
    r'\[\[(?:file:)?(?!/|[A-Za-z][A-Za-z0-9+.-]*:)'
    r'([^\]\n]+\.(?:png|jpe?g|gif|webp|svg|bmp))\](?:\[[^\]]*\])?\]',
    re.IGNORECASE,
)


def slugify_attachment_name(filename: str) -> str:
    """Slugify an attachment filename to match Quartz's static-asset slugifier.

    Quartz rewrites spaces (and other non-URL-safe chars) in copied asset
    filenames, but the markdown link keeps the original name, breaking the link.
    We pre-slugify to characters Quartz leaves untouched ([A-Za-z0-9._-]) so the
    copied file and the emitted link stay identical.
    """
    p = Path(filename)
    stem, ext = p.stem, p.suffix
    stem = re.sub(r"[^A-Za-z0-9._-]", "-", stem)  # whitespace and unsafe chars -> hyphen
    stem = re.sub(r"-+", "-", stem).strip("-")
    return (stem or "file") + ext


def get_file_tags(file_path: Path) -> set[str]:
    """Extract filetags from org file."""
    try:
        with open(file_path, "r") as f:
            in_drawer = False
            for line in f:
                stripped = line.strip()
                # Track PROPERTIES drawer
                if stripped == ":PROPERTIES:":
                    in_drawer = True
                    continue
                if stripped == ":END:":
                    in_drawer = False
                    continue
                if in_drawer:
                    continue
                # Check for filetags (case-insensitive)
                if line.lower().startswith("#+filetags:"):
                    # Handle both :tag: and tag: formats (tags separated by colons)
                    tag_part = line.split(":", 1)[1].strip().lower()
                    # Split by colons and filter empty strings
                    tags = [t.strip() for t in tag_part.split(":") if t.strip()]
                    return set(tags)
                # Stop at first non-header, non-empty line
                if not line.startswith("#") and stripped:
                    break
    except Exception:
        pass
    return set()


def has_excluded_tag(file_path: Path) -> bool:
    """Check if file has any excluded tags."""
    return bool(get_file_tags(file_path) & EXCLUDE_TAGS)




def strip_org_links(text: str) -> str:
    """Remove org link markup, keeping only the description or URL."""
    # [[url][description]] -> description
    text = re.sub(r'\[\[[^\]]+\]\[([^\]]+)\]\]', r'\1', text)
    # [[url]] -> url (but clean it up)
    text = re.sub(r'\[\[([^\]]+)\]\]', r'\1', text)
    return text


def get_title_from_org(org_file: Path) -> str | None:
    """Extract #+title: from org file, stripping any links."""
    try:
        with open(org_file, "r") as f:
            for line in f:
                if line.lower().startswith("#+title:"):
                    title = line.split(":", 1)[1].strip()
                    # Strip any org links from the title
                    return strip_org_links(title)
                # Stop after first non-header line
                if not line.startswith("#") and not line.startswith(":") and line.strip():
                    break
    except Exception:
        pass
    return None


def get_date_from_filename(org_file: Path) -> str | None:
    """Extract date from org-roam filename (YYYYMMDDHHMMSS-title.org)."""
    name = org_file.stem
    match = re.match(r"^(\d{4})(\d{2})(\d{2})\d{6}-", name)
    if match:
        return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
    return None


def get_date_from_mtime(org_file: Path) -> str:
    """Get modification date from file's mtime."""
    from datetime import datetime
    mtime = org_file.stat().st_mtime
    return datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")


def get_slug(org_file: Path) -> str:
    """Generate a URL-friendly slug from org title or filename."""
    # Try to get title first
    title = get_title_from_org(org_file)
    if title:
        name = title
    else:
        name = org_file.stem
        # Remove timestamp prefix if present (YYYYMMDDHHMMSS-)
        if re.match(r"^\d{14}-", name):
            name = name[15:]

    # Convert to lowercase, replace spaces/underscores with hyphens
    slug = re.sub(r"[_\s]+", "-", name.lower())
    # Remove non-alphanumeric characters except hyphens
    slug = re.sub(r"[^a-z0-9-]", "", slug)
    # Collapse multiple hyphens
    slug = re.sub(r"-+", "-", slug)
    # Strip leading/trailing hyphens
    slug = slug.strip("-")
    return slug or "untitled"


def get_roam_aliases(org_file: Path) -> list[str]:
    """Extract ROAM_ALIASES from org file."""
    aliases = []
    try:
        with open(org_file, "r") as f:
            for line in f:
                if ":ROAM_ALIASES:" in line:
                    # Get everything after ROAM_ALIASES:
                    alias_str = line.split(":ROAM_ALIASES:", 1)[1].strip()
                    # Parse quoted strings and bare words
                    # Match "quoted strings" or bare_words
                    aliases = re.findall(r'"([^"]+)"|(\S+)', alias_str)
                    # Flatten tuples and filter empty
                    aliases = [a[0] or a[1] for a in aliases if a[0] or a[1]]
                    break
                # Stop after PROPERTIES drawer
                if line.strip() == ":END:":
                    break
    except Exception:
        pass
    return aliases


def build_roam_map(source_dirs: list[Path], exclude_dirs: set) -> dict[str, str]:
    """Build a map of roam names (titles + aliases) -> slugs."""
    roam_map = {}

    for source_dir in source_dirs:
        for org_file in source_dir.rglob("*.org"):
            # Skip Emacs temp/lock files
            if org_file.name.startswith(".#") or org_file.name.startswith("#"):
                continue
            if any(part in exclude_dirs for part in org_file.parts):
                continue

            slug = get_slug(org_file)

            # Add title
            title = get_title_from_org(org_file)
            if title:
                roam_map[title.lower()] = slug

            # Add aliases
            for alias in get_roam_aliases(org_file):
                roam_map[alias.lower()] = slug

    return roam_map


HEADING_RE = re.compile(r"^(\*+)\s")
TRANSCLUDE_RE = re.compile(r"(?im)^[ \t]*#\+transclude:[ \t]*(.*)$")
TRANSCLUDE_MAX_DEPTH = 3
# File-level keywords never make sense inlined into a host file - a stray
# #+title: mid-document would fight with the host's own title.
TRANSCLUDE_DROP_KEYWORDS = re.compile(
    r"(?i)^#\+(title|filetags|date|author|identifier|category|setupfile|startup|options|export_\w+):"
)


def build_id_index(source_dirs: list[Path]) -> dict[str, tuple[Path, int]]:
    """Map org ID -> (file, heading line index) for transclusion targets.

    Heading line index is -1 when the ID belongs to the file rather than a
    heading (i.e. it sits in the pre-first-heading PROPERTIES drawer), meaning
    the whole file is the transclusion target.

    Unlike `build_roam_map` this indexes excluded dirs too - resolution and
    publishability are separate questions, and `_transclude_source_excluded`
    handles the latter.
    """
    index = {}
    for source_dir in source_dirs:
        if not source_dir.exists():
            continue
        for org_file in source_dir.rglob("*.org"):
            if org_file.name.startswith(".#") or org_file.name.startswith("#"):
                continue
            if ".git" in org_file.parts:
                continue
            try:
                lines = org_file.read_text().split("\n")
            except Exception:
                continue
            in_block = _block_line_mask(lines)
            heading_line = -1
            for i, line in enumerate(lines):
                if i not in in_block and HEADING_RE.match(line):
                    heading_line = i
                    continue
                m = re.match(r"^\s*:ID:\s*(\S+)\s*$", line)
                if m:
                    index.setdefault(m.group(1).lower(), (org_file, heading_line))
    return index


def _block_line_mask(lines: list[str]) -> set[int]:
    """Line indices sitting inside #+begin_.../#+end_... blocks.

    Used so a line starting with `*` inside a src or example block is not
    mistaken for a heading - the emacs config notes are full of those.
    """
    inside = set()
    depth = 0
    for i, line in enumerate(lines):
        stripped = line.strip().lower()
        if stripped.startswith("#+begin_"):
            depth += 1
            inside.add(i)
        elif stripped.startswith("#+end_"):
            depth = max(0, depth - 1)
            inside.add(i)
        elif depth:
            inside.add(i)
    return inside


def _subtree_lines(lines: list[str], start: int) -> list[str]:
    """Lines of the subtree whose heading is at index `start`."""
    in_block = _block_line_mask(lines)
    level = len(HEADING_RE.match(lines[start]).group(1))
    for i in range(start + 1, len(lines)):
        m = HEADING_RE.match(lines[i])
        if m and i not in in_block and len(m.group(1)) <= level:
            return lines[start:i]
    return lines[start:]


def _strip_drawers(lines: list[str]) -> list[str]:
    """Drop :PROPERTIES:/:LOGBOOK: style drawers."""
    out, in_drawer = [], False
    for line in lines:
        stripped = line.strip().upper()
        if in_drawer:
            if stripped == ":END:":
                in_drawer = False
            continue
        if re.match(r"^:[A-Z_]+:$", stripped) and stripped != ":END:":
            in_drawer = True
            continue
        out.append(line)
    return out


def _first_quote_block(lines: list[str]) -> list[str] | None:
    """The first #+begin_quote...#+end_quote block, inclusive."""
    start = None
    for i, line in enumerate(lines):
        stripped = line.strip().lower()
        if start is None and stripped.startswith("#+begin_quote"):
            start = i
        elif start is not None and stripped.startswith("#+end_quote"):
            return lines[start:i + 1]
    return None


def _shift_heading_level(lines: list[str], level: int) -> list[str]:
    """Re-level headings so the shallowest one sits at `level`."""
    in_block = _block_line_mask(lines)
    depths = [
        len(m.group(1))
        for i, m in ((i, HEADING_RE.match(l)) for i, l in enumerate(lines))
        if m and i not in in_block
    ]
    if not depths:
        return lines
    delta = level - min(depths)
    if delta == 0:
        return lines
    out = []
    for i, line in enumerate(lines):
        m = HEADING_RE.match(line)
        if m and i not in in_block:
            stars = max(1, len(m.group(1)) + delta)
            line = "*" * stars + line[len(m.group(1)):]
        out.append(line)
    return out


def _heading_tags(heading: str) -> set[str]:
    """Tags trailing an org heading, e.g. `* Title :work:private:`."""
    m = re.search(r"\s:([A-Za-z0-9_@#%:]+):\s*$", heading)
    return {t.lower() for t in m.group(1).split(":") if t} if m else set()


def _transclude_source_excluded(src: Path, heading: str | None) -> bool:
    """Whether a transclusion source is off-limits for publishing.

    Transcluding inlines the source's text into a published page, so anything
    we would refuse to publish on its own must not leak in this way either.
    """
    if any(part in EXCLUDE_DIRS for part in src.parts):
        return True
    if has_excluded_tag(src):
        return True
    if heading and _heading_tags(heading) & EXCLUDE_TAGS:
        return True
    return False


def _resolve_transclude_target(link: str, org_file: Path, id_index: dict) -> tuple[Path, list[str]] | None:
    """Resolve a transclusion link to (source file, target lines)."""
    link = link.strip()

    if link.lower().startswith("id:"):
        entry = id_index.get(link[3:].strip().lower())
        if not entry:
            return None
        src, heading_line = entry
        try:
            lines = src.read_text().split("\n")
        except Exception:
            return None
        if heading_line < 0:
            return src, lines
        if heading_line >= len(lines) or not HEADING_RE.match(lines[heading_line]):
            return None  # source moved since the index was built
        return src, _subtree_lines(lines, heading_line)

    if link.lower().startswith("file:"):
        path_part = link[5:].strip()
        search = None
        if "::" in path_part:
            path_part, search = path_part.split("::", 1)
        src = Path(path_part).expanduser()
        if not src.is_absolute():
            src = (org_file.parent / src).resolve()
        if not src.is_file():
            return None
        try:
            lines = src.read_text().split("\n")
        except Exception:
            return None
        if not search:
            return src, lines
        target = search.lstrip("*").strip().lower()
        in_block = _block_line_mask(lines)
        for i, line in enumerate(lines):
            if i in in_block or not HEADING_RE.match(line):
                continue
            title = HEADING_RE.sub("", line, count=1)
            title = re.sub(r"\s:([A-Za-z0-9_@#%:]+):\s*$", "", title).strip()
            if title.lower() == target:
                return src, _subtree_lines(lines, i)
        return None

    return None


def expand_transclusions(content: str, org_file: Path, id_index: dict,
                         depth: int = 0, skipped: list = None) -> str:
    """Inline `#+transclude:` directives so their content reaches the export.

    org-transclusion resolves these live in the editor; the batch exporter
    never loads it, so without this the keyword is just an unknown keyword and
    ox-md drops it (content silently missing from the published page).

    Supports the flags actually in use: `:only-quote` (a custom flag from the
    emacs config that grabs the source's first quote block), `:only-contents`,
    `:exclude-elements` and `:level`.
    """
    if "#+transclude:" not in content.lower():
        return content
    if depth >= TRANSCLUDE_MAX_DEPTH:
        return TRANSCLUDE_RE.sub("", content)

    def replace(match):
        directive = match.group(1).strip()
        link_match = re.match(r"\[\[([^\]]+)\](?:\[([^\]]*)\])?\]", directive)
        if not link_match:
            return ""
        link = link_match.group(1)
        options = directive[link_match.end():]

        resolved = _resolve_transclude_target(link, org_file, id_index)
        if not resolved:
            if skipped is not None:
                skipped.append(f"{org_file.name}: unresolved transclude {link}")
            return ""
        src, lines = resolved

        heading = lines[0] if lines and HEADING_RE.match(lines[0]) else None
        if _transclude_source_excluded(src, heading):
            if skipped is not None:
                skipped.append(f"{org_file.name}: excluded transclude source {src.name}")
            return ""

        if ":only-quote" in options:
            quote = _first_quote_block(lines)
            if quote is None:
                if skipped is not None:
                    skipped.append(f"{org_file.name}: no quote block in {src.name}")
                return ""
            lines = quote
        else:
            if ":only-contents" in options and heading:
                lines = lines[1:]
            lines = _strip_drawers(lines)
            lines = [l for l in lines if not TRANSCLUDE_DROP_KEYWORDS.match(l)]
            level_match = re.search(r":level\s+(\d+)", options)
            if level_match:
                lines = _shift_heading_level(lines, int(level_match.group(1)))

        body = "\n".join(lines).strip("\n")
        if not body:
            return ""
        # Recurse so a transcluded note can itself transclude, relative to its
        # own location.
        return expand_transclusions(body, src, id_index, depth + 1, skipped)

    return TRANSCLUDE_RE.sub(replace, content)


def preprocess_org_file(org_file: Path, attachments_map: dict, roam_map: dict = None,
                        extra_tags: list[str] = None, id_index: dict = None,
                        transclude_skips: list = None) -> str:
    """Preprocess org file content - convert attachment, ID, and roam links."""
    content = org_file.read_text()
    roam_map = roam_map or {}
    extra_tags = extra_tags or []

    # Add extra tags to filetags line (only in header, first 20 lines)
    if extra_tags:
        extra_tags_str = ":" + ":".join(extra_tags) + ":"
        lines = content.split('\n')
        header_lines = lines[:20]
        header_text = '\n'.join(header_lines)

        # Check if filetags exists in header only
        if re.search(r'(?i)^#\+filetags:', header_text, re.MULTILINE):
            # Append to existing filetags in header
            for i, line in enumerate(header_lines):
                if line.lower().startswith('#+filetags:'):
                    lines[i] = line.rstrip() + extra_tags_str
                    break
            content = '\n'.join(lines)
        else:
            # Add filetags line after title
            content = re.sub(
                r'(#\+title:[^\n]*\n)',
                rf'\1#+filetags: {extra_tags_str}\n',
                content,
                flags=re.IGNORECASE
            )

    # Add date from filename or filesystem mtime
    if "#+date:" not in content.lower():
        date = get_date_from_filename(org_file) or get_date_from_mtime(org_file)
        # Insert after title line
        content = re.sub(
            r'(#\+title:[^\n]*\n)',
            rf'\1#+DATE: {date}\n',
            content,
            flags=re.IGNORECASE
        )

    # Inline org-transclusion content before any link/attachment rewriting, so
    # transcluded text goes through the same pipeline as the host file's own.
    if id_index is not None:
        content = expand_transclusions(content, org_file, id_index, skipped=transclude_skips)

    # Compile TikZ/D2 sources to SVG. Runs after transclusion so diagrams that
    # arrive from another note render too, and before link rewriting so the
    # placeholders it leaves behind go through the attachment path.
    content = diagrams.rewrite_diagrams(content, attachments_map)

    # Normalize multi-line links: join lines within [[...]] brackets
    # Skip code blocks to avoid mangling elisp with org link syntax
    def join_multiline_links(text):
        result = []
        i = 0
        in_src_block = False
        while i < len(text):
            # Check for src block start/end
            if text[i:i+12].lower() == '#+begin_src ':
                in_src_block = True
            elif text[i:i+10].lower() == '#+end_src':
                in_src_block = False

            # Only process links outside of src blocks
            if not in_src_block and text[i:i+2] == '[[':
                # Find the closing ]]
                start = i
                depth = 0
                j = i
                while j < len(text):
                    if text[j:j+2] == '[[':
                        depth += 1
                        j += 2
                    elif text[j:j+2] == ']]':
                        depth -= 1
                        j += 2
                        if depth == 0:
                            break
                    else:
                        j += 1
                # Extract the link and normalize whitespace
                link = text[start:j]
                # Replace newlines and multiple spaces with single space
                link = re.sub(r'\s+', ' ', link)
                result.append(link)
                i = j
            else:
                result.append(text[i])
                i += 1
        return ''.join(result)

    content = join_multiline_links(content)

    # Find the data dir for this file's repo
    data_dir = org_file.parent / "data"

    if data_dir.exists():
        # Find ALL IDs in the file (file-level and heading-level)
        all_ids = re.findall(r'^:ID:\s*(.+)$', content, re.MULTILINE)

        # Build map of available attachments from all ID directories
        available_attachments = {}
        for file_id in all_ids:
            file_id = file_id.strip()
            # Attachment dirs are data/ID[:2]/ID[2:]/
            prefix = file_id[:2]
            rest = file_id[2:]
            attach_dir = data_dir / prefix / rest

            if attach_dir.exists():
                for f in attach_dir.iterdir():
                    if f.is_file():
                        # Map original name -> slug so links match the copied file
                        slug = slugify_attachment_name(f.name)
                        available_attachments[f.name] = slug
                        attachments_map[slug] = f

        # Replace [[attachment:file]] with placeholder
        # Escape underscores to prevent org subscript interpretation
        def replace_attach(match):
            filename = match.group(1)
            if filename in available_attachments:
                slug = available_attachments[filename]
                escaped = slug.replace('_', 'USCORE')
                return f'IMGATTACH:{escaped}:ENDIMG'
            return match.group(0)

        content = re.sub(r'\[\[attachment:([^\]]+)\]\]', replace_attach, content)

    # Relative image links, e.g. `[[file:img/plot.svg]]` written by a babel
    # block's `#+RESULTS:`. Emacs resolves them against the note's directory;
    # Quartz only sees content/, so copy the target in as an attachment.
    def replace_relative_image(match):
        target = (org_file.parent / match.group(1)).resolve()
        if not target.is_file():
            return match.group(0)
        slug = slugify_attachment_name(target.name)
        attachments_map[slug] = target
        return f'IMGATTACH:{slug.replace("_", "USCORE")}:ENDIMG'

    content = REL_IMG_LINK_RE.sub(replace_relative_image, content)

    # Clean up the title line - strip all links, keep just text
    def clean_title_line(match):
        title_content = match.group(1)
        # Strip [[id:uuid][desc]] -> desc
        title_content = re.sub(r'\[\[id:[^\]]+\]\[([^\]]+)\]\]', r'\1', title_content)
        # Strip [[url][desc]] -> desc
        title_content = re.sub(r'\[\[[^\]]+\]\[([^\]]+)\]\]', r'\1', title_content)
        # Strip [[link]] -> link
        title_content = re.sub(r'\[\[([^\]]+)\]\]', r'\1', title_content)
        return f'#+title:{title_content}'

    content = re.sub(r'(?i)#\+title:(.*)', clean_title_line, content)

    # Replace [[id:uuid][Description]] with placeholder that preserves description
    # Use ::: as separator to avoid conflict with table | characters
    def replace_id_link(match):
        uuid = match.group(1)
        desc = match.group(2) if match.group(2) else ""
        return f'IDLINK:::{uuid}:::{desc}:::ENDIDLINK'

    # Match [[id:uuid][description]] or [[id:uuid]]
    content = re.sub(
        r'\[\[id:([a-fA-F0-9-]+)\](?:\[([^\]]*)\])?\]',
        replace_id_link,
        content
    )

    # Replace [[roam:Name][Description]] or [[roam:Name]] with resolved links
    def replace_roam_link(match):
        name = match.group(1)
        desc = match.group(2) if match.group(2) else name
        slug = roam_map.get(name.lower())
        if slug:
            return f'ROAMLINK:::{slug}:::{desc}:::ENDROAMLINK'
        # Not found - use placeholder so it gets cleaned up later
        return f'ROAMLINK:::NOTFOUND:::{desc}:::ENDROAMLINK'

    # Match [[roam:Name][desc]] or [[roam:Name]]
    content = re.sub(
        r'\[\[roam:([^\]]+)\](?:\[([^\]]*)\])?\]',
        replace_roam_link,
        content
    )

    return content


def export_file(org_file: Path, output_dir: Path, attachments_map: dict) -> tuple[bool, str]:
    """Export a single org file to markdown using Emacs."""
    slug = get_slug(org_file)
    output_file = output_dir / f"{slug}.md"

    # Preprocess to handle attachments
    try:
        preprocessed = preprocess_org_file(org_file, attachments_map)
    except Exception as e:
        return False, f"{org_file.name}: preprocess error: {e}"

    # Write preprocessed content to temp file
    temp_org = output_dir / f".tmp_{slug}.org"
    try:
        temp_org.write_text(preprocessed)

        result = subprocess.run(
            [
                "emacs", "--batch", "-l", str(EXPORT_EL),
                "--eval", f'(org-to-md "{temp_org}" "{output_file}")'
            ],
            capture_output=True,
            text=True,
            timeout=30
        )

        temp_org.unlink(missing_ok=True)

        if result.returncode == 0:
            return True, str(org_file)
        else:
            return False, f"{org_file.name}: {result.stderr[:200]}"
    except subprocess.TimeoutExpired:
        temp_org.unlink(missing_ok=True)
        return False, f"{org_file.name}: timeout"
    except Exception as e:
        temp_org.unlink(missing_ok=True)
        return False, f"{org_file.name}: {e}"


def build_id_map(output_dir: Path) -> dict[str, str]:
    """Build a map of UUID -> filename from exported markdown files."""
    id_map = {}
    for md_file in output_dir.glob("*.md"):
        try:
            with open(md_file, "r") as f:
                in_frontmatter = False
                for line in f:
                    if line.strip() == "---":
                        if in_frontmatter:
                            break  # End of frontmatter
                        in_frontmatter = True
                        continue
                    if in_frontmatter and line.startswith("id:"):
                        uuid = line.split(":", 1)[1].strip().strip('"')
                        id_map[uuid.lower()] = md_file.stem
                        break
        except Exception:
            pass
    return id_map


def fix_id_links(output_dir: Path, id_map: dict[str, str]):
    """Replace IDLINK:::uuid:::desc:::ENDIDLINK with wiki-links preserving description."""
    pattern = re.compile(r'IDLINK:::([a-fA-F0-9-]+):::(.+?):::ENDIDLINK')
    fixed_count = 0

    for md_file in output_dir.glob("*.md"):
        try:
            content = md_file.read_text()
            original = content

            def replace_link(match):
                uuid = match.group(1).lower()
                desc = match.group(2).strip()
                if uuid in id_map:
                    slug = id_map[uuid]
                    if desc:
                        # Always preserve the original description
                        return f"[[{slug}|{desc}]]"
                    else:
                        return f"[[{slug}]]"
                # Link not found - just show the description text
                return desc if desc else ""

            content = pattern.sub(replace_link, content)

            if content != original:
                md_file.write_text(content)
                fixed_count += 1
        except Exception:
            pass

    return fixed_count


def fix_broken_links(output_dir: Path, id_map: dict[str, str]):
    """Replace [BROKEN LINK: UUID] with actual links (legacy format)."""
    pattern = re.compile(r"\[BROKEN LINK: ([a-fA-F0-9-]+)\]")
    fixed_count = 0

    for md_file in output_dir.glob("*.md"):
        try:
            content = md_file.read_text()
            original = content

            def replace_link(match):
                uuid = match.group(1).lower()
                if uuid in id_map:
                    slug = id_map[uuid]
                    return f"[[{slug}]]"
                return match.group(0)

            content = pattern.sub(replace_link, content)

            if content != original:
                md_file.write_text(content)
                fixed_count += 1
        except Exception:
            pass

    return fixed_count


def fix_roam_links(output_dir: Path):
    """Replace ROAMLINK:::slug:::desc:::ENDROAMLINK with wiki-links."""
    pattern = re.compile(r'ROAMLINK:::([^:]+):::(.+?):::ENDROAMLINK')
    fixed_count = 0

    for md_file in output_dir.glob("*.md"):
        try:
            content = md_file.read_text()
            original = content

            def replace_link(match):
                slug = match.group(1)
                desc = match.group(2).strip()
                if slug == "NOTFOUND":
                    # Unresolved roam link - just show the text
                    return desc
                if desc:
                    return f"[[{slug}|{desc}]]"
                else:
                    return f"[[{slug}]]"

            content = pattern.sub(replace_link, content)

            if content != original:
                md_file.write_text(content)
                fixed_count += 1
        except Exception:
            pass

    return fixed_count


def filter_and_export(source_dirs: list[Path], output_dir: Path, parallel: int = 1, include_konfig: bool = False, mode: str = "personal"):
    """Filter and export non-private org files to markdown."""
    shutil.rmtree(output_dir, ignore_errors=True)
    output_dir.mkdir(parents=True)

    attachments_map = {}
    staging_dir = output_dir / ".staging"
    staging_dir.mkdir(parents=True, exist_ok=True)

    # Build roam map for title/alias -> slug resolution
    print("Building roam link map...")
    roam_map = build_roam_map(source_dirs, EXCLUDE_DIRS)
    print(f"Found {len(roam_map)} roam names/aliases")

    # Build ID index for org-transclusion targets
    print("Building transclusion ID index...")
    id_index = build_id_index(source_dirs)
    print(f"Indexed {len(id_index)} IDs")
    transclude_skips = []

    # Collect and preprocess files
    files_to_export = []  # (org_file, extra_tags)
    skipped = 0

    print("Collecting and preprocessing files...")
    for source_dir in source_dirs:
        # Add k2 tag for files from K2_DIR
        extra_tags = ["k2"] if source_dir == K2_DIR else []
        for org_file in source_dir.rglob("*.org"):
            # Skip Emacs temp/lock files
            if org_file.name.startswith(".#") or org_file.name.startswith("#"):
                continue
            if any(part in EXCLUDE_DIRS for part in org_file.parts):
                continue
            if has_excluded_tag(org_file):
                skipped += 1
                continue
            files_to_export.append((org_file, extra_tags))

    # Add config files
    if EMACS_CONFIG.exists():
        files_to_export.append((EMACS_CONFIG, ["config"]))
        print("Added emacs config")
    if include_konfig and KONFIG_CONFIG.exists():
        files_to_export.append((KONFIG_CONFIG, ["config", "k2"]))
        print("Added konfig (work config)")

    print(f"Found {len(files_to_export)} files, skipped {skipped} excluded")

    # Preprocess all files (fast - pure Python)
    print("Preprocessing attachments...")
    file_pairs = []  # (staged_org, output_md)
    staged_contents = []  # (staged_org, content) - written after diagrams render
    for org_file, extra_tags in files_to_export:
        slug = get_slug(org_file)
        staged = staging_dir / f"{slug}.org"
        output = output_dir / f"{slug}.md"

        content = preprocess_org_file(org_file, attachments_map, roam_map, extra_tags,
                                      id_index, transclude_skips)
        staged_contents.append((staged, content))
        file_pairs.append((str(staged), str(output)))

    print(f"Preprocessed {len(file_pairs)} files, found {len(attachments_map)} attachments")
    if transclude_skips:
        print(f"Skipped {len(transclude_skips)} transclusions:")
        for note in transclude_skips:
            print(f"  - {note}")

    # Compile any diagram that missed the cache, then stage. Staging waits on
    # the render so a failed one can have its source put back before export.
    print("Rendering diagrams...")
    rendered, failed = diagrams.flush()
    print(f"Rendered {rendered} diagrams, {len(failed)} failed, "
          f"pruned {diagrams.prune()} stale")

    for staged, content in staged_contents:
        staged.write_text(diagrams.restore_failed(content, failed))

    # Batch export with Emacs (single process)
    print("Exporting to markdown (batch)...")
    batch_file = staging_dir / "batch.txt"
    batch_file.write_text("\n".join(f"{inp}\t{out}" for inp, out in file_pairs))

    result = subprocess.run(
        ["emacs", "--batch", "-l", str(EXPORT_EL),
         "--eval", f'(batch-export-from-file "{batch_file}")'],
        capture_output=True, text=True, timeout=300
    )

    # Count successes
    exported = sum(1 for _, out in file_pairs if Path(out).exists())
    print(f"Exported {exported}/{len(file_pairs)} files")

    if result.returncode != 0:
        print(f"Emacs errors: {result.stderr[:500]}")

    # Cleanup staging
    shutil.rmtree(staging_dir)

    # Copy attachments
    print("Copying attachments...")
    attachments_dir = output_dir / "attachments"
    attachments_dir.mkdir(parents=True, exist_ok=True)
    copied = 0
    for filename, src_path in attachments_map.items():
        dest = attachments_dir / filename
        if dest.exists() or not src_path.exists():  # a diagram whose render failed
            continue
        shutil.copy2(src_path, dest)
        # copy2 preserves the source mode, and these end up in a web root
        # served by another user - anything group/other-unreadable 403s.
        dest.chmod(0o644)
        copied += 1
    print(f"Copied {copied} attachments")

    # Post-process: resolve ID links
    print("Resolving ID links...")
    id_map = build_id_map(output_dir)
    fixed = fix_id_links(output_dir, id_map)
    print(f"Resolved links in {fixed} files ({len(id_map)} IDs mapped)")

    # Resolve roam links
    print("Resolving roam links...")
    roam_fixed = fix_roam_links(output_dir)
    print(f"Resolved roam links in {roam_fixed} files")

    # Also fix any legacy broken link format
    fix_broken_links(output_dir, id_map)

    print("Fixing attachment placeholders...")
    fix_attachment_placeholders(output_dir)

    print("Wrapping bare math environments...")
    fix_math_environments(output_dir)

    # Rewrite local file: links that point into org-attach data/ dirs
    print("Fixing local file: attachment links...")
    fix_file_links(output_dir, attachments_dir)

    # Strip org :ATTACH: tags leaked onto headings
    print("Stripping :ATTACH: heading tags...")
    strip_attach_heading_tags(output_dir)

    # Clean up any remaining broken link markers
    print("Cleaning up unresolved links...")
    cleanup_broken_links(output_dir)

    # Fix wiki-links inside HTML tables
    print("Fixing links in HTML tables...")
    fix_wikilinks_in_html(output_dir)

    # Copy mode-specific index.md
    index_src = Path(__file__).parent / f"index-{mode}.md"
    if index_src.exists():
        shutil.copy2(index_src, output_dir / "index.md")
        print(f"Copied index-{mode}.md")


def copy_attachments(source_dirs: list[Path], output_dir: Path):
    """Copy attachment directories (data/) to output."""
    attachments_dir = output_dir / "attachments"
    attachments_dir.mkdir(parents=True, exist_ok=True)

    copied = 0
    for source_dir in source_dirs:
        data_dir = source_dir / "data"
        if not data_dir.exists():
            continue

        for item in data_dir.rglob("*"):
            if item.is_file():
                # Flatten structure: data/XX/UUID/file.png -> attachments/file.png
                dest = attachments_dir / item.name
                # Handle duplicates by prefixing with parent dir
                if dest.exists():
                    dest = attachments_dir / f"{item.parent.name}_{item.name}"
                shutil.copy2(item, dest)
                copied += 1

    print(f"Copied {copied} attachments")
    return attachments_dir


def cleanup_broken_links(output_dir: Path):
    """Remove [BROKEN LINK: ...] markers for links to daily/private files."""
    # Match both UUID and roam: style broken links
    pattern = re.compile(r'\[BROKEN LINK: [^\]]+\]')
    cleaned = 0
    for md_file in output_dir.glob("*.md"):
        content = md_file.read_text()
        original = content
        content = pattern.sub('', content)
        if content != original:
            md_file.write_text(content)
            cleaned += 1
    print(f"Cleaned up {cleaned} files with unresolved links")


def fix_wikilinks_in_html(output_dir: Path):
    """Convert [[slug]] and [[slug|text]] inside HTML to proper <a> tags."""
    # Match wiki-links that are inside HTML (between < and >)
    pattern_with_text = re.compile(r'\[\[([a-z0-9-]+)\|([^\]]+)\]\]')
    pattern_simple = re.compile(r'\[\[([a-z0-9-]+)\]\]')

    fixed = 0
    for md_file in output_dir.glob("*.md"):
        content = md_file.read_text()
        original = content

        # Only fix wiki-links that appear inside HTML tags (tables, etc.)
        # Check if file has HTML content
        if '<table' in content or '<td' in content:
            # Replace [[slug|text]] with <a href="/slug">text</a>
            content = pattern_with_text.sub(r'<a href="/\1">\2</a>', content)
            # Replace [[slug]] with <a href="/slug">slug</a>
            content = pattern_simple.sub(r'<a href="/\1">\1</a>', content)

        if content != original:
            md_file.write_text(content)
            fixed += 1

    print(f"Fixed wiki-links in HTML for {fixed} files")


def strip_attach_heading_tags(output_dir: Path):
    """Remove org :ATTACH: tags that leak onto exported markdown headings.

    Org-attach adds an :ATTACH: tag to headings with attachments; ox/emacs export
    leaves it on the line, e.g. `## Hosted tool     :ATTACH:`. Strip the ATTACH
    token from the trailing tag cluster (keeping any other tags).
    """
    heading_tag = re.compile(r'^(#{1,6} .*?)[ \t]+(:[A-Za-z0-9_@#%:]+:)[ \t]*$')
    fixed = 0

    for md_file in output_dir.glob("*.md"):
        lines = md_file.read_text().split('\n')
        changed = False
        for i, line in enumerate(lines):
            m = heading_tag.match(line)
            if not m:
                continue
            tags = [t for t in m.group(2).split(':') if t]
            if 'ATTACH' not in tags:
                continue
            tags = [t for t in tags if t != 'ATTACH']
            lines[i] = f"{m.group(1)} :{':'.join(tags)}:" if tags else m.group(1)
            changed = True
        if changed:
            md_file.write_text('\n'.join(lines))
            fixed += 1

    print(f"Stripped :ATTACH: heading tags in {fixed} files")


# amsmath environments KaTeX can render, but only inside math delimiters.
MATH_ENVS = (
    "align", "alignat", "aligned", "alignedat", "cases", "darray", "dcases",
    "eqnarray", "equation", "flalign", "gather", "gathered", "multline",
    "rcases", "split", "subarray",
)
MATH_ENV_BEGIN_RE = re.compile(
    r"^\\begin\{(" + "|".join(MATH_ENVS) + r")(\*?)\}\s*$"
)


def fix_math_environments(output_dir: Path):
    """Wrap bare `\\begin{align*}`-style blocks in `$$` so KaTeX picks them up.

    Org exports a LaTeX environment verbatim, but Quartz's math transformer
    only looks inside `$...$` and `$$...$$`, so an unwrapped environment ships
    to the browser as literal backslashes.
    """
    fixed = 0
    for md_file in output_dir.glob("*.md"):
        lines = md_file.read_text().split("\n")
        out, changed = [], False
        in_fence = in_math = False

        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()
            if stripped.startswith("```"):
                in_fence = not in_fence
            elif stripped == "$$":
                in_math = not in_math

            begin = None if (in_fence or in_math) else MATH_ENV_BEGIN_RE.match(line)
            if begin:
                env = begin.group(1) + begin.group(2)
                end = f"\\end{{{env}}}"
                close = next((j for j in range(i + 1, len(lines))
                              if lines[j].strip() == end), None)
                if close is not None:
                    out.extend(["$$", *lines[i:close + 1], "$$"])
                    changed = True
                    i = close + 1
                    continue

            out.append(line)
            i += 1

        if changed:
            md_file.write_text("\n".join(out))
            fixed += 1

    print(f"Wrapped math environments in {fixed} files")


def fix_attachment_placeholders(output_dir: Path):
    """Convert IMGATTACH:file:ENDIMG placeholders to markdown syntax."""
    pattern = re.compile(r'IMGATTACH:([^:]+):ENDIMG')

    fixed = 0
    for md_file in output_dir.glob("*.md"):
        content = md_file.read_text()
        original = content

        def replace_placeholder(match):
            # Unescape underscores
            filename = match.group(1).replace('USCORE', '_')
            ext = Path(filename).suffix.lower()
            if ext in IMG_EXTENSIONS:
                return f'![{filename}](/attachments/{filename})'
            else:
                return f'[{filename}](/attachments/{filename})'

        content = pattern.sub(replace_placeholder, content)
        if content != original:
            md_file.write_text(content)
            fixed += 1

    print(f"Fixed attachment placeholders in {fixed} files")


def fix_file_links(output_dir: Path, attachments_dir: Path):
    """Rewrite local `file:` links that resolve to org-attach attachments.

    Some notes link attachments as absolute file: URIs instead of
    `[[attachment:]]`, in two shapes:
      1. Directly into a data/ dir: `[desc](file:///.../data/57/UUID/report.pdf)`
      2. To a bare basename elsewhere (e.g. the repo root) whose file is
         actually an org-attachment already synced into attachments/:
         `[desc](file:///.../org-quartz/gravitas_mission_planner.html)`
    Quartz cannot resolve a file: URI and drops the link, so rewrite both to
    `/attachments/<slug>` (copying case 1 if needed; case 2 is already synced
    via the note's :ID: dir). Links to files that are neither (e.g. source code
    references) are left untouched.
    """
    pattern = re.compile(r'\[([^\]]*)\]\((file:[^)]+)\)')
    fixed = 0
    copied = 0

    for md_file in output_dir.glob("*.md"):
        content = md_file.read_text()
        original = content

        def replace_link(match):
            nonlocal copied
            text = match.group(1)
            uri = match.group(2)
            # file:///abs -> /abs, file:/abs -> /abs, then url-decode
            path = Path(urllib.parse.unquote(re.sub(r'^file:/*', '/', uri)))
            slug = slugify_attachment_name(path.name)
            dest = attachments_dir / slug

            if "data" in path.parts and path.is_file():
                # Case 1: direct link into an org-attach data/ dir
                if not dest.exists():
                    shutil.copy2(path, dest)
                    copied += 1
            elif not dest.exists():
                # Not an attachment we recognise (e.g. source-code link) - skip
                return match.group(0)
            # else Case 2: basename already synced as an attachment - reuse it

            # Quartz serves .html/.htm assets without their extension; match that
            url = slug
            if Path(slug).suffix.lower() in {".html", ".htm"}:
                url = slug[: -len(Path(slug).suffix)]

            if path.suffix.lower() in IMG_EXTENSIONS:
                return f'![{text}](/attachments/{url})'
            return f'[{text or slug}](/attachments/{url})'

        content = pattern.sub(replace_link, content)
        if content != original:
            md_file.write_text(content)
            fixed += 1

    print(f"Rewrote file: links in {fixed} files ({copied} attachments copied)")


def copy_only(source_dirs: list[Path], output_dir: Path):
    """Copy org files without converting (for testing)."""
    shutil.rmtree(output_dir, ignore_errors=True)
    output_dir.mkdir(parents=True)

    copied = 0
    skipped = 0

    for source_dir in source_dirs:
        for org_file in source_dir.rglob("*.org"):
            # Skip Emacs temp/lock files
            if org_file.name.startswith(".#") or org_file.name.startswith("#"):
                continue
            if any(part in EXCLUDE_DIRS for part in org_file.parts):
                continue
            if has_excluded_tag(org_file):
                skipped += 1
                continue

            slug = get_slug(org_file)
            dest = output_dir / f"{slug}.org"
            shutil.copy2(org_file, dest)
            copied += 1

    print(f"Copied {copied} files, skipped {skipped} private files")


if __name__ == "__main__":
    import sys

    mode = sys.argv[1] if len(sys.argv) > 1 else "personal"
    copy_mode = "--copy" in sys.argv  # For testing without Emacs export

    if mode == "combined":
        sources = [PERSONAL_DIR, K2_DIR]
        include_konfig = True
    else:
        sources = [PERSONAL_DIR]
        include_konfig = False

    if copy_mode:
        copy_only(sources, CONTENT_DIR)
    else:
        filter_and_export(sources, CONTENT_DIR, include_konfig=include_konfig, mode=mode)
