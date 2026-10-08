import { Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider } from '@/context/AuthContext'
import { ProtectedRoute } from '@/components/layout/ProtectedRoute'
import { AppLayout } from '@/components/layout/AppLayout'
import { LoginPage } from '@/pages/LoginPage'
import { RegisterPage } from '@/pages/RegisterPage'
import { ApprovalPage } from '@/pages/ApprovalPage'
import { PrivacyPage } from '@/pages/PrivacyPage'
import { TermsPage } from '@/pages/TermsPage'
import { DashboardPage } from '@/pages/DashboardPage'
import { AccountsPage } from '@/pages/AccountsPage'
import { CategoriesPage } from '@/pages/CategoriesPage'
import { PlanningPage } from '@/pages/PlanningPage'
import { PortfolioPage } from '@/pages/PortfolioPage'
import { PhysicalAssetsPage } from '@/pages/PhysicalAssetsPage'
import { InvoicesPage } from '@/pages/InvoicesPage'
import { TransactionsPage } from '@/pages/TransactionsPage'
import { ProfilePage } from '@/pages/ProfilePage'

function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/register" element={<RegisterPage />} />
        {/* Opened from the admin's email: the signed token in the URL hash is the credential. */}
        {/* Public on purpose: the register form links to them, before anyone has an account. */}
        <Route path="/privacy" element={<PrivacyPage />} />
        <Route path="/termini" element={<TermsPage />} />
        <Route path="/approvazione" element={<ApprovalPage />} />

        <Route element={<ProtectedRoute />}>
          <Route element={<AppLayout />}>
            <Route path="/" element={<DashboardPage />} />
            <Route path="/accounts" element={<AccountsPage />} />
            <Route path="/transactions" element={<TransactionsPage />} />
            <Route path="/categories" element={<CategoriesPage />} />
            {/* Budgets are archived: no route and no nav link, but the page,
                its hooks/API client and the backend endpoints are untouched.
                Re-enable by restoring the import + <Route path="/budgets">. */}
            <Route path="/planning" element={<PlanningPage />} />
            <Route path="/portfolio" element={<PortfolioPage />} />
            <Route path="/assets" element={<PhysicalAssetsPage />} />
            {/* Only linked when the profile's work type is P.IVA forfettaria;
                the page redirects to the profile otherwise. */}
            <Route path="/invoices" element={<InvoicesPage />} />
            <Route path="/profile" element={<ProfilePage />} />
          </Route>
        </Route>

        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AuthProvider>
  )
}

export default App
