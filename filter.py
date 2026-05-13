#!/usr/bin/env python3
"""Filter and export org files to Hugo-compatible markdown."""

import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

PERSONAL_DIR = Path.home() / "git/org/personal"
K2_DIR = Path.home() / "git/org/k2"
CONTENT_DIR = Path(__file__).parent / "content"
EXPORT_EL = Path(__file__).parent / "export.el"

EXCLUDE_TAGS = {"private", "monthly", "ppl"}  # Tags that exclude a file from publishing
EXCLUDE_DIRS = {"daily", ".git"}  # Keep data/ for attachments


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


def preprocess_org_file(org_file: Path, attachments_map: dict, roam_map: dict = None) -> str:
    """Preprocess org file content - convert attachment, ID, and roam links."""
    content = org_file.read_text()
    roam_map = roam_map or {}

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

    # Normalize multi-line links: join lines within [[...]] brackets
    def join_multiline_links(text):
        result = []
        i = 0
        while i < len(text):
            if text[i:i+2] == '[[':
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
                        available_attachments[f.name] = f
                        attachments_map[f.name] = f

        # Replace [[attachment:file]] with placeholder
        # Escape underscores to prevent org subscript interpretation
        def replace_attach(match):
            filename = match.group(1)
            if filename in available_attachments:
                escaped = filename.replace('_', 'USCORE')
                return f'IMGATTACH:{escaped}:ENDIMG'
            return match.group(0)

        content = re.sub(r'\[\[attachment:([^\]]+)\]\]', replace_attach, content)

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


def filter_and_export(source_dirs: list[Path], output_dir: Path, parallel: int = 1):
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

    # Collect and preprocess files
    files_to_export = []
    skipped = 0

    print("Collecting and preprocessing files...")
    for source_dir in source_dirs:
        for org_file in source_dir.rglob("*.org"):
            if any(part in EXCLUDE_DIRS for part in org_file.parts):
                continue
            if has_excluded_tag(org_file):
                skipped += 1
                continue
            files_to_export.append(org_file)

    print(f"Found {len(files_to_export)} files, skipped {skipped} excluded")

    # Preprocess all files (fast - pure Python)
    print("Preprocessing attachments...")
    file_pairs = []  # (staged_org, output_md)
    for org_file in files_to_export:
        slug = get_slug(org_file)
        staged = staging_dir / f"{slug}.org"
        output = output_dir / f"{slug}.md"

        content = preprocess_org_file(org_file, attachments_map, roam_map)
        staged.write_text(content)
        file_pairs.append((str(staged), str(output)))

    print(f"Preprocessed {len(file_pairs)} files, found {len(attachments_map)} attachments")

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
    for filename, src_path in attachments_map.items():
        dest = attachments_dir / filename
        if not dest.exists():
            shutil.copy2(src_path, dest)
    print(f"Copied {len(attachments_map)} attachments")

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

    # Clean up any remaining broken link markers
    print("Cleaning up unresolved links...")
    cleanup_broken_links(output_dir)

    # Fix wiki-links inside HTML tables
    print("Fixing links in HTML tables...")
    fix_wikilinks_in_html(output_dir)

    # Copy index.md if it exists
    index_src = Path(__file__).parent / "index.md"
    if index_src.exists():
        shutil.copy2(index_src, output_dir / "index.md")
        print("Copied index.md")


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


def fix_attachment_placeholders(output_dir: Path):
    """Convert IMGATTACH:file:ENDIMG placeholders to markdown syntax."""
    pattern = re.compile(r'IMGATTACH:([^:]+):ENDIMG')
    img_extensions = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.bmp'}

    fixed = 0
    for md_file in output_dir.glob("*.md"):
        content = md_file.read_text()
        original = content

        def replace_placeholder(match):
            # Unescape underscores
            filename = match.group(1).replace('USCORE', '_')
            ext = Path(filename).suffix.lower()
            if ext in img_extensions:
                return f'![{filename}](/attachments/{filename})'
            else:
                return f'[{filename}](/attachments/{filename})'

        content = pattern.sub(replace_placeholder, content)
        if content != original:
            md_file.write_text(content)
            fixed += 1

    print(f"Fixed attachment placeholders in {fixed} files")


def copy_only(source_dirs: list[Path], output_dir: Path):
    """Copy org files without converting (for testing)."""
    shutil.rmtree(output_dir, ignore_errors=True)
    output_dir.mkdir(parents=True)

    copied = 0
    skipped = 0

    for source_dir in source_dirs:
        for org_file in source_dir.rglob("*.org"):
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
    else:
        sources = [PERSONAL_DIR]

    if copy_mode:
        copy_only(sources, CONTENT_DIR)
    else:
        filter_and_export(sources, CONTENT_DIR)
