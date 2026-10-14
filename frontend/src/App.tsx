import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./auth/AuthContext";
import { Layout } from "./components/Layout";
import { LoadingState } from "./components/States";
import { AgentDetailPage } from "./pages/AgentDetail";
import { AgentFormPage } from "./pages/AgentForm";
import { AgentsPage } from "./pages/Agents";
import { DashboardPage } from "./pages/Dashboard";
import { ExecutionDetailPage } from "./pages/ExecutionDetail";
import { ExecutionsPage } from "./pages/Executions";
import { Login } from "./pages/Login";
import { Register } from "./pages/Register";
import { SettingsPage } from "./pages/Settings";

function RequireAuth() {
  const { user, loading } = useAuth();
  if (loading) return <LoadingState label="Checking session" />;
  if (!user) return <Navigate to="/login" replace />;
  return <Layout />;
}

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/register" element={<Register />} />
      <Route element={<RequireAuth />}>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/agents" element={<AgentsPage />} />
        <Route path="/agents/new" element={<AgentFormPage />} />
        <Route path="/agents/:agentId" element={<AgentDetailPage />} />
        <Route path="/agents/:agentId/edit" element={<AgentFormPage />} />
        <Route path="/executions" element={<ExecutionsPage />} />
        <Route path="/executions/:taskId" element={<ExecutionDetailPage />} />
        <Route path="/settings" element={<SettingsPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
