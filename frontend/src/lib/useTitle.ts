import { useEffect } from 'react'

export const APP_TITLE = 'DevPilot'
const DEFAULT_TITLE = 'DevPilot: code review made provable' // index.html, the sign-in landing page

/** Sets the tab title to "<page> | DevPilot"; null restores the landing-page title. */
export function useTitle(page: string | null) {
  useEffect(() => {
    document.title = page ? `${page} | ${APP_TITLE}` : DEFAULT_TITLE
  }, [page])
}
