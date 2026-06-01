import { createBrowserRouter, Navigate } from 'react-router';
import { LoginPage } from './pages/LoginPage';
import { DashboardPage } from './pages/DashboardPage';
import { ContractListPage } from './pages/ContractListPage';
import { ContractUploadPage } from './pages/ContractUploadPage';
import { ParsingProgressPage } from './pages/ParsingProgressPage';
import { BatchReviewPage } from './pages/BatchReviewPage';
import { ReportPage } from './pages/ReportPage';
import { AdminPage } from './pages/AdminPage';
import { ReviewWorkspacePage } from './pages/ReviewWorkspacePage';

/**
 * 路由结构遵循 frontend_arch-spec-v1.0.md 第二章
 * P01: /login
 * P02: /dashboard
 * P03: /contracts
 * P04: /contracts/upload （静态子路由，优先级高于 :id 动态路由）
 * P05: /contracts/:id/parsing
 * P06: /contracts/:id/fields
 * P07: /contracts/:id/scanning
 * P08: /contracts/:id/review
 * P09: /contracts/:id/batch
 * P10: /contracts/:id/report
 * Parsed document: /contracts/:id/document
 * P11: /admin
 */
export const router = createBrowserRouter([
  { path: '/login', Component: LoginPage },
  { path: '/dashboard', Component: DashboardPage },
  { path: '/contracts', Component: ContractListPage },
  { path: '/contracts/upload', Component: ContractUploadPage },
  { path: '/contracts/:id/parsing', Component: ParsingProgressPage },
  { path: '/contracts/:id/fields', Component: ReviewWorkspacePage },
  { path: '/contracts/:id/scanning', Component: ReviewWorkspacePage },
  { path: '/contracts/:id/document', Component: ReviewWorkspacePage },
  { path: '/contracts/:id/review', Component: ReviewWorkspacePage },
  { path: '/contracts/:id/batch', Component: BatchReviewPage },
  { path: '/contracts/:id/report', Component: ReportPage },
  { path: '/admin', Component: AdminPage },
  { path: '/', element: <Navigate to="/login" replace /> },
  { path: '*', element: <Navigate to="/login" replace /> },
]);
