import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type Dashboard } from "../api/client";
import { StatusBadge } from "../components/StatusBadge";
import { EmptyState, ErrorState, LoadingState } from "../components/States";
import { formatTime, sumCounts } from "../lib/format";

export function DashboardPage() {
  const [data, setData] = useState<Dashboard | null>(null);
  const [error, setError] = useState("");

  function load() {
    setError("");
    api<Dashboard>("/api/v1/dashboard")
      .then(setData)
      .catch((err: Error) => setError(err.message));
  }

  useEffect(() => {
    load();
    const timer = window.setInterval(load, 5000);
    return () => window.clearInterval(timer);
  }, []);

  if (error && !data) return <ErrorState message={error} onRetry={load} />;
  if (!data) return <LoadingState label="Loading overview" />;

  const taskTotal = sumCounts(data.tasks_by_status);
  const agentTotal = sumCounts(data.agents_by_status);
  const maxStatus = Math.max(...Object.values(data.tasks_by_status), 1);

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <p className="eyebrow">Overview</p>
          <h1>Workspace</h1>
        </div>
        <Link className="button" to="/agents/new">
          New agent
        </Link>
      </header>
      {error ? <p className="form-error">{error}</p> : null}
      <section className="stat-grid">
        <article>
          <span>Agents</span>
          <strong>{agentTotal}</strong>
        </article>
        <article>
          <span>Tasks</span>
          <strong>{taskTotal}</strong>
        </article>
        <article>
          <span>Queue depth</span>
          <strong>{data.system.queue_depth}</strong>
        </article>
        <article>
          <span>Workers</span>
          <strong>{data.system.active_workers}</strong>
        </article>
      </section>
      <section className="split">
        <div className="panel">
          <div className="panel-head">
            <h2>Task status</h2>
            <span className="muted">From your executions</span>
          </div>
          {taskTotal === 0 ? (
            <EmptyState title="No tasks yet" body="Create an agent and run the demo message to populate this chart." />
          ) : (
            <ul className="bars">
              {Object.entries(data.tasks_by_status).map(([status, count]) => (
                <li key={status}>
                  <div className="bar-label">
                    <StatusBadge status={status} />
                    <span>{count}</span>
                  </div>
                  <div className="bar-track">
                    <div style={{ width: `${(count / maxStatus) * 100}%` }} />
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className="panel">
          <div className="panel-head">
            <h2>System</h2>
            <span className="muted">Live checks</span>
          </div>
          <ul className="health-list">
            <li>
              <span>API</span>
              <StatusBadge status={data.system.api === "ok" ? "completed" : "failed"} />
            </li>
            <li>
              <span>Database</span>
              <StatusBadge status={data.system.database === "ok" ? "completed" : "failed"} />
            </li>
            <li>
              <span>Redis</span>
              <StatusBadge status={data.system.redis === "ok" ? "completed" : "failed"} />
            </li>
            <li>
              <span>LLM provider</span>
              <strong>{data.system.llm_provider}</strong>
            </li>
          </ul>
        </div>
      </section>
      <section className="split">
        <div className="panel">
          <div className="panel-head">
            <h2>Recent tasks</h2>
            <Link to="/executions">View all</Link>
          </div>
          {data.recent_tasks.length === 0 ? (
            <EmptyState title="Nothing has run" body="Executions appear here as soon as a task is queued." />
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Task</th>
                  <th>Status</th>
                  <th>Updated</th>
                </tr>
              </thead>
              <tbody>
                {data.recent_tasks.map((task) => (
                  <tr key={task.id}>
                    <td>
                      <Link to={`/executions/${task.id}`}>{task.title}</Link>
                    </td>
                    <td>
                      <StatusBadge status={task.status} />
                    </td>
                    <td>{formatTime(task.updated_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
        <div className="panel">
          <div className="panel-head">
            <h2>Activity</h2>
          </div>
          {data.recent_activity.length === 0 ? (
            <EmptyState title="No activity" body="Creates, runs, retries, and failures will be listed here." />
          ) : (
            <ul className="activity">
              {data.recent_activity.map((item) => (
                <li key={item.id}>
                  <strong>{item.message}</strong>
                  <small>{formatTime(item.created_at)}</small>
                </li>
              ))}
            </ul>
          )}
        </div>
      </section>
    </div>
  );
}
