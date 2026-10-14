import { FormEvent, useState } from "react";
import { api, type User } from "../api/client";
import { useAuth } from "../auth/AuthContext";

export function SettingsPage() {
  const { user, refreshUser, logout } = useAuth();
  const [fullName, setFullName] = useState(user?.full_name ?? "");
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  async function saveProfile(event: FormEvent) {
    event.preventDefault();
    setError("");
    setMessage("");
    try {
      await api<User>("/api/v1/auth/me", { method: "PATCH", body: { full_name: fullName } });
      await refreshUser();
      setMessage("Profile updated.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Update failed");
    }
  }

  async function savePassword(event: FormEvent) {
    event.preventDefault();
    setError("");
    setMessage("");
    try {
      await api("/api/v1/auth/change-password", {
        method: "POST",
        body: { current_password: currentPassword, new_password: newPassword },
      });
      setCurrentPassword("");
      setNewPassword("");
      setMessage("Password updated.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Password change failed");
    }
  }

  return (
    <div className="page narrow">
      <header className="page-head">
        <div>
          <p className="eyebrow">Settings</p>
          <h1>Account</h1>
        </div>
      </header>
      <section className="panel">
        <h2>Profile</h2>
        <dl className="facts">
          <div>
            <dt>Email</dt>
            <dd>{user?.email}</dd>
          </div>
          <div>
            <dt>Role</dt>
            <dd>{user?.role}</dd>
          </div>
        </dl>
        <form className="stack-form" onSubmit={saveProfile}>
          <label>
            Name
            <input value={fullName} onChange={(event) => setFullName(event.target.value)} required />
          </label>
          <button className="button" type="submit">
            Save profile
          </button>
        </form>
      </section>
      <section className="panel">
        <h2>Password</h2>
        <form className="stack-form" onSubmit={savePassword}>
          <label>
            Current password
            <input
              type="password"
              value={currentPassword}
              onChange={(event) => setCurrentPassword(event.target.value)}
              required
            />
          </label>
          <label>
            New password
            <input
              type="password"
              value={newPassword}
              minLength={8}
              maxLength={72}
              onChange={(event) => setNewPassword(event.target.value)}
              required
            />
          </label>
          <button className="button secondary" type="submit">
            Change password
          </button>
        </form>
      </section>
      {message ? <p className="success">{message}</p> : null}
      {error ? <p className="form-error">{error}</p> : null}
      <section className="panel">
        <h2>API</h2>
        <p>
          Interactive reference: <a href="/docs">/docs</a>
        </p>
        <p className="fine">Readiness: <a href="/ready">/ready</a>. Metrics: <a href="/metrics">/metrics</a>.</p>
        <button className="button ghost" type="button" onClick={() => void logout()}>
          Log out
        </button>
      </section>
    </div>
  );
}
