import { QuartzComponent, QuartzComponentConstructor, QuartzComponentProps } from "./types"
import style from "./styles/backlinks.scss"
import { resolveRelative, simplifySlug } from "../util/path"
import { i18n } from "../i18n"
import { classNames } from "../util/lang"
import OverflowListFactory from "./OverflowList"
import { concatenateResources } from "../util/resources"

interface BacklinksOptions {
  hideWhenEmpty: boolean
  collapse: boolean
}

const defaultOptions: BacklinksOptions = {
  hideWhenEmpty: true,
  collapse: false,
}

let numBacklinks = 0

const script = `
const backlinksHeaders = document.querySelectorAll("button.backlinks-header")
for (const header of backlinksHeaders) {
  header.addEventListener("click", () => {
    header.classList.toggle("collapsed")
    const content = header.nextElementSibling
    if (content) {
      content.classList.toggle("collapsed")
    }
  })
}
`

export default ((opts?: Partial<BacklinksOptions>) => {
  const options: BacklinksOptions = { ...defaultOptions, ...opts }
  const { OverflowList, overflowListAfterDOMLoaded } = OverflowListFactory()

  const Backlinks: QuartzComponent = ({
    fileData,
    allFiles,
    displayClass,
    cfg,
  }: QuartzComponentProps) => {
    const slug = simplifySlug(fileData.slug!)
    const backlinkFiles = allFiles.filter((file) => file.links?.includes(slug))
    if (options.hideWhenEmpty && backlinkFiles.length == 0) {
      return null
    }

    const id = `backlinks-${numBacklinks++}`
    return (
      <div class={classNames(displayClass, "backlinks")}>
        <button
          type="button"
          class={options.collapse ? "collapsed backlinks-header" : "backlinks-header"}
          aria-controls={id}
          aria-expanded={!options.collapse}
        >
          <h3>{i18n(cfg.locale).components.backlinks.title}</h3>
          <svg
            xmlns="http://www.w3.org/2000/svg"
            width="24"
            height="24"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
            class="fold"
          >
            <polyline points="6 9 12 15 18 9"></polyline>
          </svg>
        </button>
        <OverflowList
          id={id}
          class={options.collapse ? "collapsed backlinks-content" : "backlinks-content"}
        >
          {backlinkFiles.length > 0 ? (
            backlinkFiles.map((f) => (
              <li>
                <a href={resolveRelative(fileData.slug!, f.slug!)} class="internal">
                  {f.frontmatter?.title}
                </a>
              </li>
            ))
          ) : (
            <li>{i18n(cfg.locale).components.backlinks.noBacklinksFound}</li>
          )}
        </OverflowList>
      </div>
    )
  }

  Backlinks.css = style
  Backlinks.afterDOMLoaded = concatenateResources(script, overflowListAfterDOMLoaded)

  return Backlinks
}) satisfies QuartzComponentConstructor
