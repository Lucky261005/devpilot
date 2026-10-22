import { useEffect, type RefObject } from 'react'

/** Where the fixed scan line sits, as a fraction of the viewport height. Matches .lp-scan. */
export const SCAN_AT = 0.62
const LINE_PX = 28 // the page's ruled line height, as in .lp background

/**
 * The front screen's one driver: scroll position. It sets the gutter readout (which "line" of the
 * page the scan line is on) and marks every [data-stamp] / [data-reveal] element as scanned once
 * it crosses the scan line, unmarking it when the reader scrolls back above it.
 */
export function useScanLine(root: RefObject<HTMLElement | null>) {
  useEffect(() => {
    const el = root.current
    if (!el) return
    let ctx: { revert: () => void } | undefined
    let cancelled = false
    // GSAP loads after first paint so it never delays the sign-in form.
    Promise.all([import('gsap'), import('gsap/ScrollTrigger')]).then(
      ([{ gsap }, { ScrollTrigger }]) => {
        if (cancelled) return
        gsap.registerPlugin(ScrollTrigger)
        el.dataset.scan = 'on' // verdicts start hidden only once the driver is running
        ctx = gsap.context(() => {
          const write = () => {
            const n = Math.max(1, Math.round((scrollY + innerHeight * SCAN_AT) / LINE_PX))
            // looked up on every write, so a re-rendered readout (hot reload) is never stale
            const readout = el.querySelector('.lp-scan-readout')
            if (readout) readout.textContent = `L${String(n).padStart(3, '0')}`
          }
          write()
          ScrollTrigger.create({ start: 0, end: 'max', onUpdate: write, onRefresh: write })
          el.querySelectorAll<HTMLElement>('[data-stamp], [data-reveal]').forEach((target) =>
            ScrollTrigger.create({
              trigger: target,
              start: `top ${SCAN_AT * 100}%`,
              toggleClass: 'is-scanned',
            }),
          )
        }, el)
      },
    )
    return () => {
      cancelled = true
      ctx?.revert()
      delete el.dataset.scan
    }
  }, [root])
}
