import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

const LINKS = [
  { to: "/", label: "Overview", end: true },
  { to: "/agents", label: "Agents", end: false },
  { to: "/executions", label: "Executions", end: false },
  { to: "/settings", label: "Settings", end: false },
];

export function Layout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="mark">AF</span>
          <div>
            <strong>AgentForge</strong>
            <small>Task control</small>
          </div>
        </div>
        <nav>
          {LINKS.map((link) => (
            <NavLink key={link.to} to={link.to} end={link.end} className={({ isActive }) => (isActive ? "active" : "")}>
              {link.label}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-foot">
          <div className="who">
            <strong>{user?.full_name}</strong>
            <small>{user?.email}</small>
          </div>
          <button
            className="button ghost"
            type="button"
            onClick={() => {
              void logout().then(() => navigate("/login"));
            }}
          >
            Log out
          </button>
        </div>
      </aside>
      <main className="content">
        <Outlet />
      </main>
    </div>
  );
}
