import { buildShareDocument, mimeFromUrl, shareFilename } from "../../share/strip"
import type { AssetLoader } from "../../share/strip"

/**
 * Browser half of the share feature: same stripping code the CLI runs, driven
 * off the live document instead of a file on disk.
 *
 * The controls stay hidden until you've visited the page once with `?share=1`,
 * which is remembered. That's cosmetic rather than a security boundary - the
 * button only repackages a page its viewer is already reading - so the real
 * guard is that the component isn't compiled into the public build at all.
 */
const TOGGLE_KEY = "share-tools"

const loadAsset: AssetLoader = async (url) => {
  try {
    const res = await fetch(url)
    if (!res.ok) return null
    const bytes = new Uint8Array(await res.arrayBuffer())
    const mime = res.headers.get("content-type")?.split(";")[0].trim()
    return { mime: mime || mimeFromUrl(url), bytes }
  } catch {
    return null
  }
}

const buildForThisPage = () =>
  buildShareDocument(document, { load: loadAsset, pageBase: window.location.href })

function download(html: string, filename: string) {
  const url = URL.createObjectURL(new Blob([html], { type: "text/html" }))
  const anchor = document.createElement("a")
  anchor.href = url
  anchor.download = filename
  anchor.click()
  // Revoking synchronously can cancel the download on some browsers.
  setTimeout(() => URL.revokeObjectURL(url), 30_000)
}

/**
 * Prefer the native share sheet when it can take files - on a phone that means
 * the note goes straight into Mail or Messages instead of landing in Downloads
 * for you to go find.
 */
async function deliver(html: string, filename: string) {
  const file = new File([html], filename, { type: "text/html" })
  if (navigator.canShare?.({ files: [file] })) {
    try {
      await navigator.share({ files: [file], title: filename })
      return
    } catch (err) {
      // A cancelled share sheet is a decision, not a failure to fall back from.
      if (err instanceof DOMException && err.name === "AbortError") return
    }
  }
  download(html, filename)
}

/**
 * Print the stripped document rather than the page, so the PDF matches what a
 * recipient of the HTML would see. A detached iframe keeps the current page's
 * scroll position and state untouched.
 */
function printDocument(html: string) {
  const frame = document.createElement("iframe")
  frame.setAttribute("aria-hidden", "true")
  frame.style.cssText = "position:fixed;inset:0;width:0;height:0;border:0;opacity:0"
  frame.srcdoc = html
  frame.onload = () => {
    const win = frame.contentWindow
    if (!win) return
    // Give inlined webfonts a chance to land before the print snapshot.
    const go = () => {
      win.focus()
      win.print()
      setTimeout(() => frame.remove(), 60_000)
    }
    win.document.fonts?.ready.then(go).catch(go) ?? go()
  }
  document.body.appendChild(frame)
}

document.addEventListener("nav", () => {
  const container = document.querySelector<HTMLElement>(".share-tools")
  if (!container) return
  // Shared across every page layout, but only a note has something to export.
  if (!document.querySelector("article")) return

  const params = new URLSearchParams(window.location.search)
  if (params.has("share")) {
    const on = params.get("share") !== "0"
    on ? localStorage.setItem(TOGGLE_KEY, "on") : localStorage.removeItem(TOGGLE_KEY)
  }
  if (localStorage.getItem(TOGGLE_KEY) !== "on") return
  container.removeAttribute("hidden")

  const status = container.querySelector<HTMLElement>(".share-status")
  const buttons = Array.from(container.querySelectorAll<HTMLButtonElement>("button[data-share]"))

  const run = async (button: HTMLButtonElement) => {
    const mode = button.dataset.share
    buttons.forEach((b) => (b.disabled = true))
    if (status) status.textContent = "Preparing…"
    try {
      const { title, html } = await buildForThisPage()
      if (mode === "pdf") {
        printDocument(html)
        if (status) status.textContent = ""
      } else {
        await deliver(html, `${shareFilename(title)}.html`)
        if (status) status.textContent = ""
      }
    } catch (err) {
      console.error(err)
      if (status) status.textContent = "Couldn't build the file — see the console."
    } finally {
      buttons.forEach((b) => (b.disabled = false))
    }
  }

  for (const button of buttons) {
    const onClick = () => void run(button)
    button.addEventListener("click", onClick)
    window.addCleanup(() => button.removeEventListener("click", onClick))
  }
})
