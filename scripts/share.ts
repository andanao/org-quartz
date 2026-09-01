#!/usr/bin/env -S npx tsx
/**
 * Export one built note as a standalone file to send to someone outside the
 * network.
 *
 *   ./scripts/share.sh "Acme kickoff"          -> share/acme-kickoff.html
 *   ./scripts/share.sh acme-kickoff --pdf      -> ... and .pdf
 *
 * The stripping itself lives in quartz/share/strip.ts and is shared verbatim
 * with the in-page share button; this file only supplies a DOM (jsdom over the
 * built page) and an asset loader that reads from disk instead of the network.
 * Remote assets - the CDN webfonts - are cached so repeated exports are offline
 * and instant.
 */
import { existsSync, readFileSync } from "fs"
import { mkdir, readFile, readdir, writeFile } from "fs/promises"
import { createHash } from "crypto"
import { spawnSync } from "child_process"
import path from "path"
import { fileURLToPath, pathToFileURL } from "url"
import { JSDOM } from "jsdom"

import { buildShareDocument, mimeFromUrl, shareFilename } from "../quartz/share/strip"
import type { AssetLoader } from "../quartz/share/strip"

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..")
const PUBLIC_DIR = path.join(ROOT, "public")
const CACHE_DIR = path.join(ROOT, ".share-cache")

const CHROME_CANDIDATES = [
  process.env.CHROME,
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  "/Applications/Chromium.app/Contents/MacOS/Chromium",
  "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
  "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
  "/usr/bin/google-chrome",
  "/usr/bin/chromium",
].filter((p): p is string => Boolean(p))

function die(message: string): never {
  console.error(message)
  process.exit(1)
}

/** Title of a built page, for matching a human-typed argument against. */
function pageTitle(html: string): string {
  const h1 = html.match(/<h1 class="article-title[^"]*">([^<]*)<\/h1>/)
  if (h1) return decodeEntities(h1[1])
  const title = html.match(/<title>([^<]*)<\/title>/)
  return title ? decodeEntities(title[1]) : ""
}

function decodeEntities(text: string): string {
  return text
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&amp;/g, "&")
}

/**
 * Resolve the argument to exactly one built page: a slug hit wins outright,
 * otherwise fall back to a case-insensitive title match. Ambiguity is reported
 * rather than guessed at - exporting the wrong note to a client is the one
 * failure mode worth being loud about.
 */
async function findPage(query: string): Promise<string> {
  const direct = path.join(PUBLIC_DIR, `${query.replace(/\.html$/, "")}.html`)
  if (existsSync(direct)) return direct

  const entries = (await readdir(PUBLIC_DIR)).filter((f) => f.endsWith(".html"))
  const needle = query.toLowerCase()
  const matches: { file: string; title: string; exact: boolean }[] = []

  for (const file of entries) {
    const full = path.join(PUBLIC_DIR, file)
    const title = pageTitle(readFileSync(full, "utf8"))
    const lower = title.toLowerCase()
    if (lower === needle) matches.push({ file: full, title, exact: true })
    else if (lower.includes(needle)) matches.push({ file: full, title, exact: false })
  }

  const exact = matches.filter((m) => m.exact)
  const pool = exact.length ? exact : matches

  if (pool.length === 0) die(`No built page matches "${query}". Run ./scripts/build.sh first?`)
  if (pool.length > 1) {
    console.error(`"${query}" matches ${pool.length} notes:\n`)
    for (const m of pool) {
      console.error(`  ${path.basename(m.file, ".html").padEnd(44)} ${m.title}`)
    }
    die("\nRe-run with the slug from the left column.")
  }
  return pool[0].file
}

/** Reads `file:` URLs off disk and caches everything else by URL hash. */
const loadAsset: AssetLoader = async (url) => {
  if (url.startsWith("file:")) {
    try {
      const bytes = await readFile(fileURLToPath(url))
      return { mime: mimeFromUrl(url), bytes: new Uint8Array(bytes) }
    } catch {
      console.warn(`  ! missing asset: ${path.relative(ROOT, fileURLToPath(url))}`)
      return null
    }
  }

  const key = createHash("sha256").update(url).digest("hex").slice(0, 32)
  const cached = path.join(CACHE_DIR, key)
  const metaPath = `${cached}.mime`
  if (existsSync(cached) && existsSync(metaPath)) {
    return {
      mime: await readFile(metaPath, "utf8"),
      bytes: new Uint8Array(await readFile(cached)),
    }
  }

  try {
    const res = await fetch(url)
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const bytes = new Uint8Array(await res.arrayBuffer())
    const mime = res.headers.get("content-type")?.split(";")[0].trim() || mimeFromUrl(url)
    await mkdir(CACHE_DIR, { recursive: true })
    await writeFile(cached, bytes)
    await writeFile(metaPath, mime)
    return { mime, bytes }
  } catch (err) {
    console.warn(`  ! couldn't fetch ${url} (${(err as Error).message}) - falling back`)
    return null
  }
}

function renderPdf(htmlPath: string, pdfPath: string) {
  const chrome = CHROME_CANDIDATES.find((p) => existsSync(p))
  if (!chrome) {
    die("No Chrome-family browser found for PDF export. Set CHROME=/path/to/binary.")
  }

  const result = spawnSync(
    chrome,
    [
      "--headless=new",
      "--disable-gpu",
      "--no-pdf-header-footer",
      // Lets the inlined webfonts load and lay out before the snapshot.
      "--virtual-time-budget=8000",
      `--print-to-pdf=${pdfPath}`,
      pathToFileURL(htmlPath).href,
    ],
    { stdio: ["ignore", "ignore", "pipe"] },
  )

  if (result.status !== 0 || !existsSync(pdfPath)) {
    die(`Chrome failed to render the PDF:\n${result.stderr?.toString() ?? ""}`)
  }
}

async function main() {
  const argv = process.argv.slice(2)
  const wantPdf = argv.includes("--pdf")
  const outFlag = argv.indexOf("--out")
  const outDir = outFlag >= 0 ? path.resolve(argv[outFlag + 1]) : path.join(ROOT, "share")
  const query = argv
    .filter((a, i) => !a.startsWith("--") && !(outFlag >= 0 && i === outFlag + 1))
    .join(" ")
    .trim()

  if (!query) {
    die("usage: ./scripts/share.sh <note title or slug> [--pdf] [--out DIR]")
  }
  if (!existsSync(PUBLIC_DIR)) {
    die("No public/ directory - run ./scripts/build.sh first.")
  }

  const pagePath = await findPage(query)
  const pageUrl = pathToFileURL(pagePath).href
  console.log(`Sharing ${path.relative(ROOT, pagePath)}`)

  const dom = new JSDOM(await readFile(pagePath, "utf8"), { url: pageUrl })
  const { title, html } = await buildShareDocument(dom.window.document, {
    load: loadAsset,
    pageBase: pageUrl,
  })

  await mkdir(outDir, { recursive: true })
  const stem = shareFilename(title)
  const htmlPath = path.join(outDir, `${stem}.html`)
  await writeFile(htmlPath, html)
  const kb = (Buffer.byteLength(html) / 1024).toFixed(0)
  console.log(`  ${path.relative(ROOT, htmlPath)}  (${kb} KB, self-contained)`)

  if (wantPdf) {
    const pdfPath = path.join(outDir, `${stem}.pdf`)
    renderPdf(htmlPath, pdfPath)
    console.log(`  ${path.relative(ROOT, pdfPath)}`)
  }
}

main().catch((err) => die(err instanceof Error ? err.message : String(err)))
