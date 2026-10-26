import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query'
import { lazy, Suspense } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import { ErrorBox, Spinner } from './components/ui'
import { ApiError, api } from './lib/api'
import { useTitle } from './lib/useTitle'
import { LoginPage } from './pages/LoginPage'

// Signed-in pages load on demand, so the front screen ships only what it needs.
const RepositoriesPage = lazy(() =>
  import('./pages/RepositoriesPage').then((m) => ({ default: m.RepositoriesPage })),
)
const RepositoryPage = lazy(() =>
  import('./pages/RepositoryPage').then((m) => ({ default: m.RepositoryPage })),
)
const ReviewPage = lazy(() => import('./pages/ReviewPage').then((m) => ({ default: m.ReviewPage })))
const SettingsPage = lazy(() =>
  import('./pages/SettingsPage').then((m) => ({ default: m.SettingsPage })),
)

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: (n, e) => !(e instanceof ApiError && e.status >= 400 && e.status < 500) && n < 2,
      refetchOnWindowFocus: false,
    },
  },
})

function NotFound() {
  useTitle('Page not found')
  return <p className="text-muted">Page not found.</p>
}

function Authed() {
  const me = useQuery({ queryKey: ['me'], queryFn: api.me })
  if (me.isLoading) return <Spinner label="Checking session" />
  if (me.error instanceof ApiError && me.error.status === 401)
    return <Navigate to="/login" replace />
  if (me.error)
    return (
      <div className="p-6">
        <ErrorBox error={me.error} />
      </div>
    )
  return (
    <Layout user={me.data!}>
      <Suspense fallback={<Spinner label="Loading page" />}>
        <Routes>
          <Route path="/" element={<RepositoriesPage />} />
          <Route path="/repositories/:id" element={<RepositoryPage />} />
          <Route path="/reviews/:id" element={<ReviewPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </Suspense>
    </Layout>
  )
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/*" element={<Authed />} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  )
}
