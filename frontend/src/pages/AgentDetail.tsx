import { FormEvent, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, type Agent, type Page, type Task, type TaskDetail } from "../api/client";
import { StatusBadge } from "../components/StatusBadge";
import { EmptyState, ErrorState, LoadingState } from "../components/States";
import { formatTime, newIdempotencyKey } from "../lib/format";

export function AgentDetailPage() {
  const { agentId } = useParams();
  const navigate = useNavigate();
  const [agent, setAgent] = useState<Agent | null>(null);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("Urgent: customer cannot log in to the billing portal");
  const [url, setUrl] = useState("");
  const [pending, setPending] = useState(false);

  function load() {
    if (!agentId) return;
    setError("");
    Promise.all([
      api<Agent>(`/api/v1/agents/${agentId}`),
      api<Page<Task>>(`/api/v1/tasks?agent_id=${agentId}&page_size=8`),
    ])
      .then(([nextAgent, page]) => {
        setAgent(nextAgent);
        setTasks(page.items);
      })
      .catch((err: Error) => setError(err.message));
  }

  useEffect(() => {
    load();
  }, [agentId]);

  async function setStatus(action: "start" | "pause") {
    if (!agentId) return;
    setError("");
    try {
      const next = await api<Agent>(`/api/v1/agents/${agentId}/${action}`, { method: "POST" });
      setAgent(next);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Update failed");
    }
  }

  async function archive() {
    if (!agentId || !window.confirm("Archive this agent? It will disappear from your list.")) return;
    await api(`/api/v1/agents/${agentId}`, { method: "DELETE" });
    navigate("/agents");
  }

  async function runTask(event: FormEvent) {
    event.preventDefault();
    if (!agentId) return;
    setPending(true);
    setError("");
    const input: Record<string, string> = { text: message };
    if (url.trim()) input.url = url.trim();
    try {
      const task = await api<TaskDetail>(`/api/v1/agents/${agentId}/tasks`, {
        method: "POST",
        body: { input, idempotency_key: newIdempotencyKey() },
      });
      navigate(`/executions/${task.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not queue the task");
    } finally {
      setPending(false);
    }
  }

  if (error && !agent) return <ErrorState message={error} onRetry={load} />;
  if (!agent) return <LoadingState label="Loading agent" />;

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <p className="eyebrow">Agent</p>
          <h1>{agent.name}</h1>
          <p className="lede">{agent.description || "No description"}</p>
        </div>
        <div className="button-row">
          <StatusBadge status={agent.status} />
          {agent.status !== "active" ? (
            <button className="button" type="button" onClick={() => void setStatus("start")}>
              Start
            </button>
          ) : (
            <button className="button secondary" type="button" onClick={() => void setStatus("pause")}>
              Pause
            </button>
          )}
          <Link className="button secondary" to={`/agents/${agent.id}/edit`}>
            Edit
          </Link>
          <button className="button ghost" type="button" onClick={() => void archive()}>
            Archive
          </button>
        </div>
      </header>
      {error ? <p className="form-error">{error}</p> : null}
      <section className="split">
        <div className="panel">
          <h2>Definition</h2>
          <dl className="facts">
            <div>
              <dt>Provider</dt>
              <dd>{agent.provider || "server default"}</dd>
            </div>
            <div>
              <dt>Model</dt>
              <dd>{agent.model || "server default"}</dd>
            </div>
            <div>
              <dt>Retries</dt>
              <dd>{agent.max_retries}</dd>
            </div>
            <div>
              <dt>Timeout</dt>
              <dd>{agent.timeout_seconds}s</dd>
            </div>
          </dl>
          <p className="prompt">{agent.system_prompt}</p>
          <div className="chips">
            {agent.tools.map((tool) => (
              <span key={tool}>{tool}</span>
            ))}
          </div>
        </div>
        <form className="panel" onSubmit={runTask}>
          <h2>Run a task</h2>
          <label>
            Message
            <textarea value={message} onChange={(event) => setMessage(event.target.value)} rows={5} required />
          </label>
          {agent.tools.includes("http_request") ? (
            <label>
              Public URL
              <input value={url} onChange={(event) => setUrl(event.target.value)} placeholder="https://example.com" />
            </label>
          ) : null}
          <button className="button" type="submit" disabled={pending || agent.status !== "active"}>
            {pending ? "Queueing…" : "Run task"}
          </button>
          {agent.status !== "active" ? <p className="fine">Start the agent before queueing work.</p> : null}
        </form>
      </section>
      <section className="panel">
        <div className="panel-head">
          <h2>Recent executions</h2>
        </div>
        {tasks.length === 0 ? (
          <EmptyState title="No executions" body="Run a task to see status, steps, and stored records." />
        ) : (
          <table>
            <thead>
              <tr>
                <th>Task</th>
                <th>Status</th>
                <th>Created</th>
              </tr>
            </thead>
            <tbody>
              {tasks.map((task) => (
                <tr key={task.id}>
                  <td>
                    <Link to={`/executions/${task.id}`}>{task.title}</Link>
                  </td>
                  <td>
                    <StatusBadge status={task.status} />
                  </td>
                  <td>{formatTime(task.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
