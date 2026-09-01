/**
 * Turn a rendered Quartz page into a standalone document fit for sending to
 * someone outside the network.
 *
 * The note body is the shareable part; the page around it is not. Explorer,
 * graph, backlinks and search each enumerate the rest of the vault, and an
 * internal wiki-link both names a note the recipient has no business knowing
 * about and dead-ends the moment the file travels on its own. So we keep the
 * article, its title and its date, drop everything else, and unlink anything
 * that pointed back into the notes.
 *
 * This works against the DOM API rather than a hast tree so one implementation
 * can back both entry points - the in-page button (a live `document`) and the
 * CLI (jsdom over a built `public/*.html`). What you preview is what you send.
 *
 * Every asset the result needs is inlined as a data URI, so the output is a
 * single file that renders identically with no network and no server.
 */

export type LoadedAsset = { mime: string; bytes: Uint8Array }

/** Fetch an absolute URL (`https:` or `file:`); null if it can't be had. */
export type AssetLoader = (url: string) => Promise<LoadedAsset | null>

export type ShareOptions = {
  load: AssetLoader
  /** Absolute URL the page's relative links resolve against. */
  pageBase: string
}

const MIME_BY_EXT: Record<string, string> = {
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".gif": "image/gif",
  ".webp": "image/webp",
  ".svg": "image/svg+xml",
  ".avif": "image/avif",
  ".woff": "font/woff",
  ".woff2": "font/woff2",
  ".ttf": "font/ttf",
  ".otf": "font/otf",
  ".css": "text/css",
}

export function mimeFromUrl(url: string): string {
  const path = url.split(/[?#]/)[0].toLowerCase()
  const dot = path.lastIndexOf(".")
  return (dot >= 0 && MIME_BY_EXT[path.slice(dot)]) || "application/octet-stream"
}

function toBase64(bytes: Uint8Array): string {
  if (typeof Buffer !== "undefined") return Buffer.from(bytes).toString("base64")
  let binary = ""
  // Chunked so a large font doesn't blow the argument limit on `apply`.
  const chunk = 0x8000
  for (let i = 0; i < bytes.length; i += chunk) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunk))
  }
  return btoa(binary)
}

function toDataUri(asset: LoadedAsset): string {
  return `data:${asset.mime};base64,${toBase64(asset.bytes)}`
}

function resolve(url: string, base: string): string | null {
  try {
    return new URL(url, base).href
  } catch {
    return null
  }
}

/** A link that survives the trip: an external destination or a jump within this file. */
function isPortableLink(href: string): boolean {
  if (href.startsWith("#")) return true // footnotes, heading anchors - same document
  return /^(https?|mailto|tel):/i.test(href)
}

/** Replace an element with its own children, keeping the text in the flow. */
function unwrap(el: Element) {
  const parent = el.parentNode
  if (!parent) return
  while (el.firstChild) parent.insertBefore(el.firstChild, el)
  parent.removeChild(el)
}

/**
 * Strip everything from the article that only makes sense on the site: links
 * back into the vault, UI affordances, and the slug attributes that name other
 * notes even when nothing visibly links to them.
 */
function sanitizeArticle(article: Element) {
  // Affordances with nothing to act on once the page is a flat file: copy
  // buttons, "link to original" backrefs, and the little chain icon that
  // rehype-autolink-headings hangs off every heading.
  for (const el of article.querySelectorAll(
    '.clipboard-button, a.transclude-src, a[role="anchor"]',
  )) {
    el.remove()
  }

  for (const anchor of Array.from(article.querySelectorAll("a[href]"))) {
    const href = anchor.getAttribute("href") ?? ""
    if (isPortableLink(href)) {
      // Heading anchor links wrap the heading text itself - leaving them as
      // live `#` links is fine, but they shouldn't look clickable in a doc.
      if (anchor.classList.contains("internal")) anchor.classList.remove("internal")
      continue
    }
    unwrap(anchor)
  }

  // Anything still carrying a slug names another note. Popover data attributes
  // in particular embed the target's path even after the link is gone.
  for (const el of Array.from(article.querySelectorAll("[data-slug], [data-block]"))) {
    el.removeAttribute("data-slug")
    el.removeAttribute("data-block")
  }
}

/**
 * Recursively inline `url(...)` references inside a stylesheet.
 *
 * Fonts are the reason this exists: ET Bembo and the code face come off a CDN,
 * and a document that silently falls back to Times the moment the recipient is
 * offline is not "looks like my site".
 */
async function inlineCssAssets(
  css: string,
  cssUrl: string,
  opts: ShareOptions,
  seen: Set<string>,
): Promise<string> {
  const refs = new Map<string, string>()
  const pattern = /url\(\s*(['"]?)([^'")]+)\1\s*\)/g

  for (const match of css.matchAll(pattern)) {
    const raw = match[2].trim()
    if (raw.startsWith("data:") || refs.has(raw)) continue
    const abs = resolve(raw, cssUrl)
    if (!abs || seen.has(abs)) continue
    seen.add(abs)
    const asset = await opts.load(abs)
    if (asset) {
      refs.set(raw, toDataUri({ mime: asset.mime || mimeFromUrl(abs), bytes: asset.bytes }))
    }
  }

  return css.replace(pattern, (whole, _quote, raw: string) => {
    const replacement = refs.get(raw.trim())
    return replacement ? `url("${replacement}")` : whole
  })
}

/**
 * Stylesheets worth fetching only when the note actually uses what they carry.
 *
 * Both of these exist to ship webfonts, and the fonts dominate the file size -
 * KaTeX's set runs to about a megabyte, the code face to half of that. Sending
 * a client a 1.2 MB meeting summary for a monospace font nothing renders in is
 * the difference between an attachment and a nuisance.
 */
const CONDITIONAL_SHEETS: { pattern: RegExp; usedBy: string }[] = [
  { pattern: /katex/i, usedBy: ".katex" },
  { pattern: /fonts\.googleapis\.com|fira[-+ ]?code|plex[-+ ]?mono/i, usedBy: "code, pre" },
]

/**
 * Collect the page's stylesheets, inlining every asset they reference.
 */
async function collectCss(doc: Document, article: Element, opts: ShareOptions): Promise<string> {
  const seen = new Set<string>()
  const sheets: string[] = []

  for (const link of Array.from(doc.querySelectorAll<HTMLLinkElement>('link[rel="stylesheet"]'))) {
    const href = link.getAttribute("href")
    if (!href) continue

    const conditional = CONDITIONAL_SHEETS.find((c) => c.pattern.test(href))
    if (conditional && !article.querySelector(conditional.usedBy)) continue

    const abs = resolve(href, opts.pageBase)
    if (!abs || seen.has(abs)) continue
    seen.add(abs)

    const asset = await opts.load(abs)
    if (!asset) continue
    const text = new TextDecoder().decode(asset.bytes)
    sheets.push(await inlineCssAssets(text, abs, opts, seen))
  }

  for (const style of Array.from(doc.querySelectorAll("style"))) {
    const text = style.textContent ?? ""
    if (text.trim()) sheets.push(await inlineCssAssets(text, opts.pageBase, opts, seen))
  }

  return sheets.join("\n")
}

/** Turn every image in the article into a data URI so the file stands alone. */
async function inlineImages(article: Element, opts: ShareOptions) {
  for (const img of Array.from(article.querySelectorAll("img[src]"))) {
    const src = img.getAttribute("src")
    if (!src || src.startsWith("data:")) continue
    const abs = resolve(src, opts.pageBase)
    if (!abs) continue
    const asset = await opts.load(abs)
    if (!asset) continue
    img.setAttribute("src", toDataUri({ mime: asset.mime || mimeFromUrl(abs), bytes: asset.bytes }))
    img.removeAttribute("srcset")
    img.removeAttribute("loading")
  }
}

/**
 * Layout overrides for the shared file.
 *
 * The site's article styles are all scoped under `#quartz-root.page`, so the
 * output keeps that wrapper and everything - typography, code, callouts,
 * tables, math - comes along for free and stays in sync. Only the page grid
 * needs undoing, since there are no sidebars left to lay out.
 */
const SHARE_CSS = `
/* base.scss pins the viewport with \`width: 100vw\` and clips the overflow so a
   wide element can't spawn a horizontal scrollbar next to the sticky header.
   Neither concern survives here, and 100vw counts the scrollbar gutter - left
   in place it overflows the document by exactly that much. */
html { width: auto; overflow-x: visible; }

#quartz-root.page > #quartz-body {
  display: block;
  max-width: 46rem;
  margin: 0 auto;
  padding: 0 1.5rem 4rem;
}
#quartz-root.page > #quartz-body > .center { max-width: 100%; }
.page-header { margin-top: 3rem; }
h1.article-title { margin: 0 0 0.4rem; }
.share-meta {
  color: var(--gray);
  font-size: 0.85rem;
  margin: 0 0 2.5rem;
  border-bottom: 1px solid var(--lightgray);
  padding-bottom: 1.5rem;
}
article img, article svg { max-width: 100%; height: auto; }
article a { color: var(--secondary); }

@media all and (max-width: 800px) {
  #quartz-root.page > #quartz-body { padding: 0 1.1rem 3rem; }
  .page-header { margin-top: 1.75rem; }
}

@page { margin: 18mm 16mm; }
@media print {
  #quartz-root.page > #quartz-body { max-width: none; padding: 0; }
  .page-header { margin-top: 0; }
  article pre, article table, article figure, article blockquote, article img {
    break-inside: avoid;
  }
  article h1, article h2, article h3 { break-after: avoid; }
  /* A data-URI href printed after every link is noise in a document. */
  a::after { content: none !important; }
}
`

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
}

export type ShareResult = { title: string; html: string }

/**
 * Build the standalone document. `doc` is a fully rendered Quartz page, live
 * or parsed; it is never mutated.
 */
export async function buildShareDocument(
  doc: Document,
  opts: ShareOptions,
): Promise<ShareResult> {
  const source = doc.querySelector("article")
  if (!source) throw new Error("no <article> on this page - nothing to share")

  const article = source.cloneNode(true) as Element
  sanitizeArticle(article)
  await inlineImages(article, opts)

  const title =
    doc.querySelector("h1.article-title")?.textContent?.trim() || doc.title.trim() || "Untitled"
  const date = doc.querySelector(".page-header .content-meta")?.textContent?.trim() ?? ""

  const css = await collectCss(doc, article, opts)
  const lang = doc.documentElement.getAttribute("lang") || "en"

  // Pinned to the light theme: this is a document, and it is as likely to be
  // printed or turned into a PDF as it is to be read on a screen.
  const html = `<!DOCTYPE html>
<html lang="${escapeHtml(lang)}" saved-theme="light">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>${escapeHtml(title)}</title>
<style>${css}</style>
<style>${SHARE_CSS}</style>
</head>
<body>
<div id="quartz-root" class="page">
<div id="quartz-body">
<div class="center">
<div class="page-header">
<h1 class="article-title">${escapeHtml(title)}</h1>
${date ? `<p class="share-meta">${escapeHtml(date)}</p>` : ""}
</div>
${article.outerHTML}
</div>
</div>
</div>
</body>
</html>
`

  return { title, html }
}

/** A filesystem-safe stem for the shared file, derived from the note title. */
export function shareFilename(title: string): string {
  const slug = title
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
  return slug || "shared-note"
}
