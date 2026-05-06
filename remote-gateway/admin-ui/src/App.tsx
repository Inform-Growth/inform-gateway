import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { QueryClientProvider } from '@tanstack/react-query';
import { Toaster } from '@/components/ui/sonner';
import { queryClient } from '@/lib/queryClient';
import { captureTokenFromUrl } from '@/lib/auth';
import { AppShell } from '@/components/layout/AppShell';
import DashboardPage from '@/routes/DashboardPage';
import ToolCallsPage from '@/routes/tool-calls/ToolCallsPage';
import TasksPage from '@/routes/tasks/TasksPage';
import OperatorsPage from '@/routes/operators/OperatorsPage';
import ToolsPage from '@/routes/tools/ToolsPage';
import SkillsPage from '@/routes/skills/SkillsPage';
import ToolHintsPage from '@/routes/tool-hints/ToolHintsPage';
import SettingsPage from '@/routes/SettingsPage';
import LoginPage from '@/routes/LoginPage';

captureTokenFromUrl();

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter basename="/admin">
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route element={<AppShell />}>
            <Route index element={<Navigate to="/dashboard" replace />} />
            <Route path="/dashboard"  element={<DashboardPage />} />
            <Route path="/tool-calls" element={<ToolCallsPage />} />
            <Route path="/tasks"      element={<TasksPage />} />
            <Route path="/operators"  element={<OperatorsPage />} />
            <Route path="/tools"      element={<ToolsPage />} />
            <Route path="/skills"     element={<SkillsPage />} />
            <Route path="/tool-hints" element={<ToolHintsPage />} />
            <Route path="/settings"   element={<SettingsPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
      <Toaster richColors position="top-right" />
    </QueryClientProvider>
  );
}
