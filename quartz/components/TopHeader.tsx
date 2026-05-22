import { QuartzComponent, QuartzComponentConstructor, QuartzComponentProps } from "./types"
import { classNames } from "../util/lang"

export interface TopHeaderOptions {
  left: QuartzComponent[]
  center: QuartzComponent[]
  right: QuartzComponent[]
}

export default ((opts: TopHeaderOptions) => {
  const allComponents = [...opts.left, ...opts.center, ...opts.right]

  const TopHeader: QuartzComponent = (props: QuartzComponentProps) => {
    return (
      <div class="top-header">
        <div class="top-header-left">
          <button
            type="button"
            class="hamburger-btn mobile-only"
            aria-label="Open menu"
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              width="24"
              height="24"
              viewBox="0 0 24 24"
              stroke-width="2"
              stroke="currentColor"
              fill="none"
              stroke-linecap="round"
              stroke-linejoin="round"
            >
              <line x1="4" x2="20" y1="12" y2="12" />
              <line x1="4" x2="20" y1="6" y2="6" />
              <line x1="4" x2="20" y1="18" y2="18" />
            </svg>
          </button>
          {opts.left.map((Component) => (
            <Component {...props} />
          ))}
        </div>
        <div class="top-header-center">
          {opts.center.map((Component) => (
            <Component {...props} />
          ))}
        </div>
        <div class="top-header-right">
          {opts.right.map((Component) => (
            <Component {...props} />
          ))}
        </div>
      </div>
    )
  }

  // Aggregate CSS from all child components
  const childCss = allComponents
    .map((c) => c.css)
    .filter((css): css is string => typeof css === "string")
    .join("\n")

  TopHeader.css = childCss + `
.top-header {
  grid-area: grid-top-header;
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  align-items: center;
  padding: 1rem 2rem;
  gap: 1rem;
  background: var(--light);
}

.top-header-left {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  justify-self: start;
}

.top-header-left .page-title {
  margin: 0;
}

/* Hamburger button */
.hamburger-btn {
  display: none;
  background: transparent;
  border: none;
  cursor: pointer;
  padding: 0.25rem;
  color: var(--darkgray);
}

.hamburger-btn:hover {
  color: var(--dark);
}

.top-header-center {
  text-align: center;
  min-width: 0;
  max-width: 100%;
  overflow: hidden;
  justify-self: center;
}

.top-header-center h1.article-title {
  margin: 0;
  font-size: 1.2rem;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 100%;
}

.top-header-right {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  justify-self: end;
}

/* Search bar styling in header */
.top-header-right .search {
  flex-grow: 0;
}

@media all and (max-width: 800px) {
  .top-header {
    padding: 0.75rem 1rem;
    grid-template-columns: auto 1fr auto;
  }

  .hamburger-btn {
    display: flex;
    align-items: center;
    justify-content: center;
  }

  /* Hide site title on mobile - it goes in the drawer */
  .top-header-left .page-title {
    display: none;
  }

  /* Hide title in header on mobile - it shows in article body instead */
  .top-header-center {
    display: none;
  }

  /* Collapse search to icon on mobile */
  .top-header-right .search {
    width: auto !important;
    min-width: auto !important;
    max-width: none !important;
  }

  .top-header-right .search .search-button {
    width: auto !important;
    padding: 0.25rem;
    border: none;
  }

  .top-header-right .search .search-button p {
    display: none !important;
  }

  /* Hide reader mode on mobile - doesn't make sense */
  .top-header-right .readermode {
    display: none !important;
  }
}

/* Reader mode - collapse search to icon */
:root[reader-mode="on"] .top-header-right .search .search-button p {
  display: none;
}

:root[reader-mode="on"] .top-header-right .search .search-button {
  width: auto;
  padding: 0.25rem;
}
`

  // Aggregate beforeDOMLoaded scripts from child components
  const childBeforeDOMLoaded = allComponents
    .map((c) => c.beforeDOMLoaded)
    .filter((s): s is string => typeof s === "string")
    .join("\n")

  if (childBeforeDOMLoaded) {
    TopHeader.beforeDOMLoaded = childBeforeDOMLoaded
  }

  // Aggregate afterDOMLoaded scripts from child components
  const childAfterDOMLoaded = allComponents
    .map((c) => c.afterDOMLoaded)
    .filter((s): s is string => typeof s === "string")
    .join("\n")

  TopHeader.afterDOMLoaded = childAfterDOMLoaded + `
document.addEventListener("nav", () => {
  const hamburger = document.querySelector(".hamburger-btn")
  const explorer = document.querySelector(".explorer")
  const sidebar = document.querySelector(".sidebar.left")

  if (!hamburger || !explorer || !sidebar) return

  // Always close drawer on page navigation
  explorer.classList.add("collapsed")
  document.documentElement.classList.remove("mobile-no-scroll")

  const closeDrawer = () => {
    explorer.classList.add("collapsed")
    document.documentElement.classList.remove("mobile-no-scroll")
  }

  const openDrawer = () => {
    explorer.classList.remove("collapsed")
    document.documentElement.classList.add("mobile-no-scroll")
  }

  const toggleDrawer = (e) => {
    e.stopPropagation()
    if (explorer.classList.contains("collapsed")) {
      openDrawer()
    } else {
      closeDrawer()
    }
  }

  hamburger.addEventListener("click", toggleDrawer)
  window.addCleanup(() => hamburger.removeEventListener("click", toggleDrawer))

  // Add close button to drawer if not exists
  if (!sidebar.querySelector(".drawer-close")) {
    const closeBtn = document.createElement("button")
    closeBtn.className = "drawer-close"
    closeBtn.setAttribute("aria-label", "Close menu")
    closeBtn.innerHTML = \`<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>\`
    sidebar.insertBefore(closeBtn, sidebar.firstChild)
    closeBtn.addEventListener("click", closeDrawer)
    window.addCleanup(() => closeBtn.removeEventListener("click", closeDrawer))
  }

  // Close drawer when clicking outside of it
  const handleOutsideClick = (e) => {
    if (!explorer.classList.contains("collapsed") &&
        !sidebar.contains(e.target) &&
        !hamburger.contains(e.target)) {
      closeDrawer()
    }
  }
  document.addEventListener("click", handleOutsideClick)
  window.addCleanup(() => document.removeEventListener("click", handleOutsideClick))
})
`

  return TopHeader
}) satisfies QuartzComponentConstructor<TopHeaderOptions>
