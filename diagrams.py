#!/usr/bin/env python3
"""Compile LaTeX and D2 diagram sources to SVG for the published site.

Quartz renders math with KaTeX, which covers `$...$` and the amsmath
environments but knows nothing about TikZ, pgfplots, forest, circuitikz or
tikz-cd - org exports those verbatim and the page ends up showing raw
backslash soup. D2 blocks fail the other way round: Emacs writes an SVG next
to the note, but the `#+RESULTS:` link is relative to the org tree and never
reaches content/.

Both are fixed by compiling the source here. Renders are keyed by content
hash and cached, so a rebuild only pays for diagrams that actually changed.
Callers `rewrite_diagrams()` during preprocessing (cheap - it only reserves
filenames), then `flush()` once to compile everything that missed the cache.
"""

import hashlib
import os
import re
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

CACHE_DIR = Path(__file__).parent / ".diagram-cache"
# Bumped whenever a change here would produce different output for unchanged
# source, so the content-hash cache doesn't serve up stale SVGs.
RENDER_VERSION = "2"
TEXBIN = Path("/Library/TeX/texbin")  # MacTeX; the Homebrew builds can't do TikZ
RENDER_TIMEOUT = 180

# Mirrors `ads/latex-drawing-preamble` in ~/git/emacs/readme.org. Inline
# previews, `latex' babel blocks and this all have to render identically, so
# the two copies must stay in step.
LATEX_PREAMBLE = r"""\usepackage{tikz}
\usepackage{pgfplots}
\usepackage{circuitikz}
\usepackage{forest}
\usepackage{tikz-cd}
\usepackage{amsmath}
\usepackage{amssymb}
\usetikzlibrary{automata,positioning,arrows.meta,shapes.geometric,calc,fit,
  trees,decorations.pathmorphing,backgrounds,matrix,chains}
\pgfplotsset{compat=1.18}"""

# Environments KaTeX cannot render, so they have to become images. Math
# environments are deliberately absent - `fix_math_environments` in filter.py
# hands those to KaTeX instead, which keeps them selectable text.
DRAWING_ENVS = ("tikzpicture", "tikzcd", "forest", "circuitikz")

SRC_LANGS = {"latex", "d2"}

SRC_BEGIN_RE = re.compile(r"^[ \t]*#\+begin_src[ \t]+([A-Za-z0-9_+-]+)(.*)$", re.I)
SRC_END_RE = re.compile(r"^[ \t]*#\+end_src[ \t]*$", re.I)
BLOCK_BEGIN_RE = re.compile(r"^[ \t]*#\+begin_([A-Za-z0-9_-]+)", re.I)
RESULTS_RE = re.compile(r"^[ \t]*#\+RESULTS(\[[^\]]*\])?:", re.I)
ENV_BEGIN_RE = re.compile(r"^[ \t]*\\begin\{(" + "|".join(DRAWING_ENVS) + r")\}")

# slug -> (kind, source). Kept for the whole run so `restore_failed` can put
# the original source back when a render blows up.
_sources: dict[str, tuple[str, str]] = {}
_pending: dict[str, tuple[str, str]] = {}


def cache_path(slug: str) -> Path:
    return CACHE_DIR / slug


def request(kind: str, body: str) -> str:
    """Reserve an SVG for KIND source BODY and return its attachment slug."""
    digest = hashlib.sha256(
        "\0".join((RENDER_VERSION, kind, LATEX_PREAMBLE, body)).encode()
    ).hexdigest()[:16]
    slug = f"diagram-{digest}.svg"
    _sources[slug] = (kind, body)
    if not cache_path(slug).exists():
        _pending[slug] = (kind, body)
    return slug


def flush(max_workers: int = 4) -> tuple[int, set[str]]:
    """Render every reserved-but-uncached diagram. Returns (rendered, failed)."""
    if not _pending:
        return 0, set()

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    jobs = sorted(_pending.items())
    _pending.clear()

    def run(job):
        slug, (kind, body) = job
        try:
            renderer = _render_latex if kind == "latex" else _render_d2
            renderer(body, cache_path(slug))
            return slug, None
        except Exception as e:
            return slug, str(e)

    failed = set()
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        for slug, error in pool.map(run, jobs):
            if error:
                failed.add(slug)
                cache_path(slug).unlink(missing_ok=True)
                print(f"  ! {slug}: {error}")

    return len(jobs) - len(failed), failed


def prune() -> int:
    """Drop cached SVGs nothing asked for this run - i.e. edited-away sources."""
    if not CACHE_DIR.is_dir():
        return 0
    stale = [p for p in CACHE_DIR.glob("diagram-*.svg") if p.name not in _sources]
    for path in stale:
        path.unlink(missing_ok=True)
    return len(stale)


def restore_failed(content: str, failed: set[str]) -> str:
    """Put the original source back where a render failed.

    Better a visible code block than a broken <img> - the note still carries
    its content and the build log says which diagram needs looking at.
    """
    if not failed:
        return content

    def replace(match):
        slug = match.group(1).replace("USCORE", "_")
        if slug not in failed:
            return match.group(0)
        kind, body = _sources[slug]
        return f"#+begin_src {kind}\n{body}\n#+end_src"

    return re.sub(r"IMGATTACH:([^:]+):ENDIMG", replace, content)


def rewrite_diagrams(content: str, attachments_map: dict) -> str:
    """Replace diagram sources in org CONTENT with attachment placeholders.

    Handles `latex`/`d2` babel blocks (honouring `:exports`) and bare drawing
    environments sitting in the buffer as inline-preview fragments. Every
    other block type is copied through untouched, which is also what keeps a
    stray `\\begin{tikzpicture}` inside an example block from being compiled.
    """
    lines = content.split("\n")
    out: list[str] = []
    i, n = 0, len(lines)

    def reserve(kind: str, body: str) -> str:
        slug = request(kind, body)
        attachments_map[slug] = cache_path(slug)
        return f"IMGATTACH:{slug}:ENDIMG"

    while i < n:
        line = lines[i]

        src = SRC_BEGIN_RE.match(line)
        if src and src.group(1).lower() in SRC_LANGS:
            lang, header = src.group(1).lower(), src.group(2)
            end = _find(lines, i + 1, SRC_END_RE.match)
            if end is None:  # unterminated block - not ours to fix
                out.append(line)
                i += 1
                continue
            body = "\n".join(lines[i + 1:end])
            after = _skip_results(lines, end + 1)
            exports = (_header_value(header, "exports") or "code").lower()
            if exports in ("results", "both"):
                if exports == "both":
                    out.extend(lines[i:end + 1])
                out.append(reserve(lang, body))
            else:
                # Code-only block: keep the source, but drop the `#+RESULTS:`
                # link, which points at a file outside content/.
                out.extend(lines[i:end + 1])
            i = after
            continue

        block = BLOCK_BEGIN_RE.match(line)
        if block:
            end = _find(lines, i + 1, _end_of(block.group(1)))
            stop = n if end is None else end + 1
            out.extend(lines[i:stop])
            i = stop
            continue

        env = ENV_BEGIN_RE.match(line)
        if env:
            end = _find(lines, i + 1, _latex_end_of(env.group(1)))
            if end is None:
                out.append(line)
                i += 1
                continue
            out.append(reserve("latex", "\n".join(lines[i:end + 1])))
            i = end + 1
            continue

        out.append(line)
        i += 1

    return "\n".join(out)


def _find(lines, start, matches):
    for i in range(start, len(lines)):
        if matches(lines[i]):
            return i
    return None


def _end_of(name: str):
    pattern = re.compile(r"^[ \t]*#\+end_" + re.escape(name) + r"[ \t]*$", re.I)
    return pattern.match


def _latex_end_of(env: str):
    return re.compile(r"^[ \t]*\\end\{" + re.escape(env) + r"\}").match


def _header_value(header: str, key: str) -> str | None:
    m = re.search(rf":{key}[ \t]+(\S+)", header)
    return m.group(1) if m else None


def _skip_results(lines: list[str], i: int) -> int:
    """Index just past a `#+RESULTS:` block following a src block, if any."""
    j = i
    while j < len(lines) and not lines[j].strip():
        j += 1
    if j >= len(lines) or not RESULTS_RE.match(lines[j]):
        return i
    j += 1
    block = BLOCK_BEGIN_RE.match(lines[j]) if j < len(lines) else None
    if block:
        end = _find(lines, j + 1, _end_of(block.group(1)))
        return len(lines) if end is None else end + 1
    while j < len(lines) and lines[j].strip():  # a link, a table, plain output
        j += 1
    return j


def _render_latex(body: str, dest: Path):
    document = "\n".join((
        r"\documentclass[preview,border=4pt]{standalone}",
        LATEX_PREAMBLE,
        r"\begin{document}",
        body,
        r"\end{document}",
        "",
    ))
    env = dict(os.environ, PATH=f"{TEXBIN}{os.pathsep}{os.environ.get('PATH', '')}")

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "d.tex").write_text(document)
        tex = subprocess.run(
            ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", "d.tex"],
            cwd=tmp, env=env, capture_output=True, text=True, timeout=RENDER_TIMEOUT,
        )
        if not (tmp / "d.pdf").exists():
            raise RuntimeError(_tex_error(tex.stdout))
        subprocess.run(
            ["pdftocairo", "-svg", "d.pdf", "out.svg"],
            cwd=tmp, env=env, capture_output=True, text=True,
            timeout=RENDER_TIMEOUT, check=True,
        )
        shutil.move(tmp / "out.svg", dest)


def _render_d2(body: str, dest: Path):
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out.svg"
        result = subprocess.run(
            ["d2", "--pad", "20", "-", str(out)],
            input=body, capture_output=True, text=True, timeout=RENDER_TIMEOUT,
        )
        if not out.exists():
            raise RuntimeError((result.stderr or result.stdout).strip()[:200])
        out.write_text(_with_intrinsic_size(out.read_text()))
        shutil.move(out, dest)


ROOT_SVG_RE = re.compile(r"<svg\b[^>]*>")
VIEWBOX_RE = re.compile(r'viewBox\s*=\s*"\s*[\d.eE+-]+[\s,]+[\d.eE+-]+[\s,]+'
                        r'([\d.eE+-]+)[\s,]+([\d.eE+-]+)\s*"')


def _with_intrinsic_size(svg: str) -> str:
    """Put `width`/`height` back on a root `<svg>` that only has a `viewBox`.

    d2 sizes its root element purely by viewBox, which leaves the SVG with an
    aspect ratio but no intrinsic size. Quartz's `base.scss` sets
    `content-visibility: auto` on every img, and a replaced element with no
    intrinsic size collapses under it - the diagram is in the DOM and simply
    never paints. pdftocairo's LaTeX output carries a real width/height, which
    is why only the d2 diagrams went missing.
    """
    root = ROOT_SVG_RE.search(svg)
    if not root or re.search(r'\bwidth\s*=', root.group(0)):
        return svg
    box = VIEWBOX_RE.search(root.group(0))
    if not box:
        return svg
    sized = root.group(0)[:-1].rstrip() + f' width="{box.group(1)}" height="{box.group(2)}">'
    return svg[:root.start()] + sized + svg[root.end():]


def _tex_error(log: str) -> str:
    """The first TeX error line, which is the only useful part of the log."""
    for line in log.split("\n"):
        if line.startswith("!"):
            return line.strip()[:200]
    return "pdflatex produced no PDF"
