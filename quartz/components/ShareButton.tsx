// @ts-ignore
import shareScript from "./scripts/share.inline"
import styles from "./styles/share.scss"
import { QuartzComponent, QuartzComponentConstructor, QuartzComponentProps } from "./types"
import { classNames } from "../util/lang"

/**
 * Controls for exporting the current note as a standalone file to send to
 * someone outside the network. Renders hidden and is revealed by the inline
 * script only for a browser that has opted in via `?share=1`.
 *
 * Add it to `afterBody` from a build that sets `QUARTZ_SHARE_UI` - the public
 * build leaves it out entirely, so neither the markup nor the script ships.
 */
const ShareButton: QuartzComponent = ({ displayClass }: QuartzComponentProps) => {
  return (
    <div class={classNames(displayClass, "share-tools")} hidden>
      <div class="share-actions">
        <button type="button" data-share="html">
          <svg
            xmlns="http://www.w3.org/2000/svg"
            width="16"
            height="16"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
            aria-hidden="true"
          >
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
            <polyline points="7 10 12 15 17 10" />
            <line x1="12" y1="15" x2="12" y2="3" />
          </svg>
          Share page
        </button>
        <button type="button" data-share="pdf">
          <svg
            xmlns="http://www.w3.org/2000/svg"
            width="16"
            height="16"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
            aria-hidden="true"
          >
            <polyline points="6 9 6 2 18 2 18 9" />
            <path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2" />
            <rect x="6" y="14" width="12" height="8" />
          </svg>
          PDF
        </button>
      </div>
      <p class="share-status" role="status" aria-live="polite"></p>
    </div>
  )
}

ShareButton.afterDOMLoaded = shareScript
ShareButton.css = styles

export default (() => ShareButton) satisfies QuartzComponentConstructor
