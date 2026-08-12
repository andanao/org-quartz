// Reader mode is the default so a shared link opens as a clean page instead of
// a wall of chrome. The always-visible header keeps the highlighted toggle
// around as the hint that there's more here. Once someone flips it, their
// choice sticks. Applied here (beforeDOMLoaded) so there's no flash of the
// full layout on first paint.
const readerModeStorageKey = "reader-mode"
let isReaderMode = localStorage.getItem(readerModeStorageKey) !== "off"
document.documentElement.setAttribute("reader-mode", isReaderMode ? "on" : "off")

const emitReaderModeChangeEvent = (mode: "on" | "off") => {
  const event: CustomEventMap["readermodechange"] = new CustomEvent("readermodechange", {
    detail: { mode },
  })
  document.dispatchEvent(event)
}

document.addEventListener("nav", () => {
  const switchReaderMode = () => {
    isReaderMode = !isReaderMode
    const newMode = isReaderMode ? "on" : "off"
    document.documentElement.setAttribute("reader-mode", newMode)
    localStorage.setItem(readerModeStorageKey, newMode)
    emitReaderModeChangeEvent(newMode)
  }

  for (const readerModeButton of document.getElementsByClassName("readermode")) {
    readerModeButton.addEventListener("click", switchReaderMode)
    window.addCleanup(() => readerModeButton.removeEventListener("click", switchReaderMode))
  }

  // Set initial state
  document.documentElement.setAttribute("reader-mode", isReaderMode ? "on" : "off")
})
