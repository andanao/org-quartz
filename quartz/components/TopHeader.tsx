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
/* Always on screen: the tools (reader mode, search, theme) never scroll away,
   and on a shared link the highlighted reader-mode toggle is the cue that
   there's a whole site behind the page you landed on. */
.top-header {
  position: sticky;
  top: 0;
  z-index: 101;
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  align-items: center;
  padding: 1rem 2rem;
  gap: 1rem;
  background: var(--light);
  border-bottom: 1px solid transparent;
  transition: border-color 0.2s ease;
}

/* Hairline only once content has scrolled under it, so a page at rest stays
   clean. */
.top-header.scrolled {
  border-bottom-color: var(--lightgray);
}

.top-header-left {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  justify-self: stretch;
}

/* Site title now lives on the right */
.top-header-right .page-title {
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

/* Search bar styling in header (now in the left tool cluster). Let it grow to
   fill the left column (capped) so it reads as a proper search bar instead of
   shrinking to just the icon + label. */
.top-header-left .search {
  flex: 1 1 auto;
  min-width: 12rem;
  max-width: 20rem;
}

.top-header-left .search > .search-button {
  width: 100%;
}

@media all and (max-width: 800px) {
  /* Flex row so the hamburger can pin left and the tools slide to the right */
  .top-header {
    display: flex;
    align-items: center;
    padding: 0.75rem 1rem;
  }

  .top-header-left {
    flex: 1 1 auto;
    gap: 0.75rem;
  }

  .top-header-left .hamburger-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    margin-right: auto; /* push the tool cluster to the right edge */
  }

  /* Center (article title) shows in the body; site title lives in the drawer */
  .top-header-center,
  .top-header-right {
    display: none;
  }

  /* Collapse search to icon on mobile */
  .top-header-left .search {
    flex: 0 0 auto !important;
    width: auto !important;
    min-width: auto !important;
    max-width: none !important;
  }

  .top-header-left .search .search-button {
    width: auto !important;
    padding: 0.25rem;
    border: none;
  }

  .top-header-left .search .search-button p {
    display: none !important;
  }

  /* Hide reader mode on mobile - doesn't make sense */
  .top-header-left .readermode {
    display: none !important;
  }
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
  const header = document.querySelector(".top-header")

  if (header) {
    // The sticky sidebars and anchor scroll-padding key off --header-height, so
    // publish the real measurement instead of trusting the CSS fallback.
    const setHeaderHeight = () => {
      document.documentElement.style.setProperty("--header-height", header.offsetHeight + "px")
    }
    setHeaderHeight()
    const headerResize = new ResizeObserver(setHeaderHeight)
    headerResize.observe(header)
    window.addCleanup(() => headerResize.disconnect())

    const onScroll = () => header.classList.toggle("scrolled", window.scrollY > 4)
    onScroll()
    window.addEventListener("scroll", onScroll, { passive: true })
    window.addCleanup(() => window.removeEventListener("scroll", onScroll))
  }

  const hamburger = document.querySelector(".hamburger-btn")
  const sidebar = document.querySelector(".sidebar.left")
  const page = document.querySelector(".page")

  if (!hamburger || !sidebar || !page) return

  // Backdrop lives at the page level (outside the transformed drawer) so it can
  // dim the whole viewport. Create it once and reuse it across SPA navigations.
  let backdrop = page.querySelector(".drawer-backdrop")
  if (!backdrop) {
    backdrop = document.createElement("div")
    backdrop.className = "drawer-backdrop"
    page.appendChild(backdrop)
  }

  // The drawer's open/closed state is a single explicit class on the sidebar.
  // Nothing else drives it, so resizing across the mobile breakpoint can never
  // accidentally pop it open.
  const closeDrawer = () => {
    sidebar.classList.remove("drawer-open")
    document.documentElement.classList.remove("mobile-no-scroll")
    backdrop.classList.remove("open")
  }

  const openDrawer = () => {
    sidebar.classList.add("drawer-open")
    document.documentElement.classList.add("mobile-no-scroll")
    backdrop.classList.add("open")
  }

  const toggleDrawer = (e) => {
    e.stopPropagation()
    if (sidebar.classList.contains("drawer-open")) {
      closeDrawer()
    } else {
      openDrawer()
    }
  }

  // Always start closed on navigation. (On tablet/desktop the class is inert,
  // so this is safe everywhere.)
  closeDrawer()

  hamburger.addEventListener("click", toggleDrawer)
  window.addCleanup(() => hamburger.removeEventListener("click", toggleDrawer))

  // If the window grows past the mobile breakpoint while the drawer is open,
  // tear it down so we never leave a stray backdrop or scroll-lock behind.
  const onResize = () => {
    if (!hamburger.checkVisibility()) closeDrawer()
  }
  window.addEventListener("resize", onResize)
  window.addCleanup(() => window.removeEventListener("resize", onResize))

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

  // Tapping the backdrop closes the drawer
  backdrop.addEventListener("click", closeDrawer)
  window.addCleanup(() => backdrop.removeEventListener("click", closeDrawer))
})
`

  return TopHeader
}) satisfies QuartzComponentConstructor<TopHeaderOptions>
