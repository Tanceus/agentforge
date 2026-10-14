import { FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type Agent, type Page } from "../api/client";
import { StatusBadge } from "../components/StatusBadge";
import { EmptyState, ErrorState, LoadingState, Pager } from "../components/States";
import { formatTime } from "../lib/format";

export function AgentsPage() {
  const [page, setPage] = useState(1);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const [data, setData] = useState<Page<Agent> | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  function load(nextPage = page) {
    setLoading(true);
    setError("");
    const params = new URLSearchParams({ page: String(nextPage), page_size: "10" });
    if (query.trim()) params.set("q", query.trim());
    if (status) params.set("status", status);
    api<Page<Agent>>(`/api/v1/agents?${params.toString()}`)
      .then(setData)
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    load(page);
    // eslint is not configured; query changes submit explicitly.
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
          <p className="eyebrow">Agents</p>
          <h1>Your agents</h1>
        </div>
        <Link className="button" to="/agents/new">
          New agent
        </Link>
      </header>
      <form className="filters" onSubmit={onSearch}>
        <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search name or description" />
        <select
          value={status}
          onChange={(event) => {
            setStatus(event.target.value);
            setPage(1);
          }}
        >
          <option value="">All statuses</option>
          <option value="draft">Draft</option>
          <option value="active">Active</option>
          <option value="paused">Paused</option>
        </select>
        <button className="button secondary" type="submit">
          Search
        </button>
      </form>
      {error ? <ErrorState message={error} onRetry={() => load(page)} /> : null}
      {loading && !data ? <LoadingState label="Loading agents" /> : null}
      {data && data.total === 0 ? (
        <EmptyState
          title="No agents match"
          body="Create an agent, choose its tools, and start it before queueing work."
          action={
            <Link className="button" to="/agents/new">
              Create an agent
            </Link>
          }
        />
      ) : null}
      {data && data.items.length > 0 ? (
        <div className="panel">
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Status</th>
                <th>Tools</th>
                <th>Updated</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((agent) => (
                <tr key={agent.id}>
                  <td>
                    <Link to={`/agents/${agent.id}`}>{agent.name}</Link>
                    <div className="muted">{agent.description || "No description"}</div>
                  </td>
                  <td>
                    <StatusBadge status={agent.status} />
                  </td>
                  <td>{agent.tools.join(", ")}</td>
                  <td>{formatTime(agent.updated_at)}</td>
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
