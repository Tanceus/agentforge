import { FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type Page, type Task } from "../api/client";
import { StatusBadge } from "../components/StatusBadge";
import { EmptyState, ErrorState, LoadingState, Pager } from "../components/States";
import { formatTime } from "../lib/format";

const STATUSES = ["", "pending", "queued", "running", "completed", "failed", "cancelled"];

export function ExecutionsPage() {
  const [page, setPage] = useState(1);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const [data, setData] = useState<Page<Task> | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  function load(nextPage = page) {
    setLoading(true);
    const params = new URLSearchParams({ page: String(nextPage), page_size: "12" });
    if (query.trim()) params.set("q", query.trim());
    if (status) params.set("status", status);
    api<Page<Task>>(`/api/v1/tasks?${params.toString()}`)
      .then((payload) => {
        setData(payload);
        setError("");
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    load(page);
    // Search is submitted explicitly so the query is not a dependency.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, status]);

  function onSearch(event: FormEvent) {
    event.preventDefault();
    setPage(1);
    load(1);
  }

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <p className="eyebrow">Executions</p>
          <h1>History</h1>
        </div>
      </header>
      <form className="filters" onSubmit={onSearch}>
        <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search title or message" />
        <select
          value={status}
          onChange={(event) => {
            setStatus(event.target.value);
            setPage(1);
          }}
        >
          {STATUSES.map((item) => (
            <option key={item || "all"} value={item}>
              {item || "All statuses"}
            </option>
          ))}
        </select>
        <button className="button secondary" type="submit">
          Search
        </button>
      </form>
      {error ? <ErrorState message={error} onRetry={() => load(page)} /> : null}
      {loading && !data ? <LoadingState label="Loading executions" /> : null}
      {data && data.total === 0 ? (
        <EmptyState title="No executions" body="Tasks you run will stay in PostgreSQL and show up here." />
      ) : null}
      {data && data.items.length > 0 ? (
        <div className="panel">
          <table>
            <thead>
              <tr>
                <th>Task</th>
                <th>Status</th>
                <th>Attempt</th>
                <th>Created</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((task) => (
                <tr key={task.id}>
                  <td>
                    <Link to={`/executions/${task.id}`}>{task.title}</Link>
                    {task.dead_letter ? <div className="muted">Dead letter</div> : null}
                  </td>
                  <td>
                    <StatusBadge status={task.status} />
                  </td>
                  <td>{task.attempt}</td>
                  <td>{formatTime(task.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <Pager page={data.page} pageSize={data.page_size} total={data.total} onPage={setPage} />
        </div>
      ) : null}
    </div>
  );
}
