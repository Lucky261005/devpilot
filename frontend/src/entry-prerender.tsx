/*
 * Build-time render of the front screen (scripts/prerender.mjs). The served /login HTML then
 * holds the real heading, landmarks and copy before any JavaScript runs; main.tsx hydrates it.
 * The tree must match what App renders for /login, or hydration falls back to a full render.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { renderToString } from 'react-dom/server'
import { Route, Routes, StaticRouter } from 'react-router-dom'
import { LoginPage } from './pages/LoginPage'

export function render(): string {
  return renderToString(
    <StrictMode>
      <QueryClientProvider client={new QueryClient()}>
        <StaticRouter location="/login">
          <Routes>
            <Route path="/login" element={<LoginPage />} />
          </Routes>
        </StaticRouter>
      </QueryClientProvider>
    </StrictMode>,
  )
}
