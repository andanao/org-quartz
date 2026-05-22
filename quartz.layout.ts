import { PageLayout, SharedLayout } from "./quartz/cfg"
import * as Component from "./quartz/components"

// components shared across all pages
export const sharedPageComponents: SharedLayout = {
  head: Component.Head(),
  header: [],
  afterBody: [],
  footer: Component.Footer({
    links: {
      GitHub: "https://github.com/andanao/org-quartz",
    },
  }),
  topHeader: Component.TopHeader({
    left: [Component.PageTitle()],
    center: [Component.ArticleTitle()],
    right: [Component.Search(), Component.Darkmode(), Component.ReaderMode()],
  }),
}

// components for pages that display a single page (e.g. a single note)
export const defaultContentPageLayout: PageLayout = {
  beforeBody: [
    Component.MobileOnly(Component.ArticleTitle()),
    Component.Flex({
      components: [
        { Component: Component.TagList(), grow: true, align: "center" },
        { Component: Component.ContentMeta({ showReadingTime: false }), align: "center" },
      ],
      gap: "1rem",
    }),
  ],
  left: [
    // Show TOC, Backlinks, and Graph in left sidebar on tablet and mobile (in drawer)
    Component.MobileOnly(Component.PageTitle()),
    Component.MobileOnly(Component.Search()),
    Component.MobileOnly(Component.TableOfContents()),
    Component.MobileOnly(Component.Backlinks()),
    Component.MobileOnly(Component.Graph()),
    Component.TabletOnly(Component.TableOfContents()),
    Component.TabletOnly(Component.Backlinks()),
    Component.Explorer({
      filterFn: (node) => {
        // Hide pages tagged with "ppl" and the tags folder
        if (node.slugSegment === "tags") return false
        if (node.data?.tags?.includes("ppl")) return false
        return true
      },
      sortFn: (a, b) => {
        // K2/work files first
        const aIsK2 = a.data?.tags?.includes("k2") ?? false
        const bIsK2 = b.data?.tags?.includes("k2") ?? false
        if (aIsK2 && !bIsK2) return -1
        if (!aIsK2 && bIsK2) return 1
        // Folders before files
        if (a.isFolder && !b.isFolder) return -1
        if (!a.isFolder && b.isFolder) return 1
        // Sort by date (most recent first)
        const aDate = a.data?.date
        const bDate = b.data?.date
        if (aDate && bDate) {
          return new Date(bDate).getTime() - new Date(aDate).getTime()
        }
        if (aDate) return -1
        if (bDate) return 1
        return a.displayName.localeCompare(b.displayName, undefined, {
          numeric: true,
          sensitivity: "base",
        })
      },
    }),
  ],
  right: [
    Component.DesktopOnly(Component.Graph()),
    Component.DesktopOnly(Component.TableOfContents()),
    Component.DesktopOnly(Component.Backlinks()),
  ],
}

// components for pages that display lists of pages  (e.g. tags or folders)
export const defaultListPageLayout: PageLayout = {
  beforeBody: [Component.ContentMeta()],
  left: [
    Component.Explorer({
      filterFn: (node) => {
        // Hide pages tagged with "ppl" and the tags folder
        if (node.slugSegment === "tags") return false
        if (node.data?.tags?.includes("ppl")) return false
        return true
      },
      sortFn: (a, b) => {
        // K2/work files first
        const aIsK2 = a.data?.tags?.includes("k2") ?? false
        const bIsK2 = b.data?.tags?.includes("k2") ?? false
        if (aIsK2 && !bIsK2) return -1
        if (!aIsK2 && bIsK2) return 1
        // Folders before files
        if (a.isFolder && !b.isFolder) return -1
        if (!a.isFolder && b.isFolder) return 1
        // Sort by date (most recent first)
        const aDate = a.data?.date
        const bDate = b.data?.date
        if (aDate && bDate) {
          return new Date(bDate).getTime() - new Date(aDate).getTime()
        }
        if (aDate) return -1
        if (bDate) return 1
        return a.displayName.localeCompare(b.displayName, undefined, {
          numeric: true,
          sensitivity: "base",
        })
      },
    }),
  ],
  right: [],
}
