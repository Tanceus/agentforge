import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, apiFetch, type Page, type RecordItem, type TaskDetail } from "../api/client";
import { StatusBadge } from "../components/StatusBadge";
import { ErrorState, LoadingState } from "../components/States";
import { formatTime } from "../lib/format";

const TERMINAL = new Set(["completed", "failed", "cancelled"]);

export function ExecutionDetailPage() {
  const { taskId } = useParams();
  const [task, setTask] = useState<TaskDetail | null>(null);
  const [records, setRecords] = useState<RecordItem[]>([]);
  const [error, setError] = useState("");
  const [live, setLive] = useState(false);

  useEffect(() => {
    if (!taskId) return;
    const controller = new AbortController();
    let cancelled = false;

    async function follow() {
      setError("");
      try {
        const response = await apiFetch(`/api/v1/tasks/${taskId}/events`, {
          headers: { Accept: "text/event-stream" },
          signal: controller.signal,
        });
        if (!response.ok || !response.body) {
          const fallback = await api<TaskDetail>(`/api/v1/tasks/${taskId}`);
          if (!cancelled) setTask(fallback);
          return;
        }
        setLive(true);
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        while (!cancelled) {
          const chunk = await reader.read();
          if (chunk.done) break;
          buffer += decoder.decode(chunk.value, { stream: true });
          const parts = buffer.split("\n\n");
          buffer = parts.pop() ?? "";
          for (const part of parts) {
            const dataLine = part
              .split("\n")
              .filter((line) => line.startsWith("data:"))
              .map((line) => line.slice(5).trim())
              .join("");
            if (!dataLine) continue;
            const payload = JSON.parse(dataLine) as TaskDetail;
            if (!cancelled) setTask(payload);
          }
        }
      } catch (err) {
        if (!cancelled && !(err instanceof DOMException && err.name === "AbortError")) {
          setError(err instanceof Error ? err.message : "Live updates stopped");
          try {
            const fallback = await api<TaskDetail>(`/api/v1/tasks/${taskId}`);
            if (!cancelled) setTask(fallback);
          } catch {
            /* the error state already explains the failure */
          }
        }
      } finally {
        if (!cancelled) setLive(false);
      }
    }

    void follow();
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [taskId]);

  useEffect(() => {
    if (!task?.id) return;
    api<Page<RecordItem>>(`/api/v1/records?task_id=${task.id}`)
      .then((page) => setRecords(page.items))
      .catch(() => setRecords([]));
  }, [task?.id, task?.status]);

  async function act(path: "cancel" | "retry") {
    if (!taskId) return;
    setError("");
    try {
      const next = await api<TaskDetail>(`/api/v1/tasks/${taskId}/${path}`, { method: "POST" });
      setTask(next);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Action failed");
    }
  }

  if (error && !task) return <ErrorState message={error} />;
  if (!task) return <LoadingState label="Connecting to live status" />;
  const terminal = TERMINAL.has(task.status);

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <p className="eyebrow">Execution</p>
          <h1>{task.title}</h1>
          <p className="lede">
            {task.agent_name ? <Link to={`/agents/${task.agent_id}`}>{task.agent_name}</Link> : "Agent"} ·{" "}
            {live && !terminal ? <span className="live">Live</span> : "Settled"}
          </p>
        </div>
        <div className="button-row">
          <StatusBadge status={task.status} />
          {!terminal ? (
            <button className="button secondary" type="button" onClick={() => void act("cancel")}>
              Cancel
            </button>
          ) : null}
          {task.status === "failed" ? (
            <button className="button" type="button" onClick={() => void act("retry")}>
              Retry
            </button>
          ) : null}
        </div>
      </header>
      {error ? <p className="form-error">{error}</p> : null}
      <section className="stat-grid">
        <article>
          <span>Attempt</span>
          <strong>{task.attempt}</strong>
        </article>
        <article>
          <span>Max retries</span>
          <strong>{task.max_retries}</strong>
        </article>
        <article>
          <span>Dead letter</span>
          <strong>{task.dead_letter ? "Yes" : "No"}</strong>
        </article>
        <article>
          <span>Finished</span>
          <strong className="time">{formatTime(task.finished_at)}</strong>
        </article>
      </section>
      <section className="split">
        <div className="panel">
          <h2>Result</h2>
          {task.result?.summary ? <p>{task.result.summary}</p> : <p className="muted">No result yet.</p>}
          {task.error ? (
            <pre className="log error-log">{task.error}</pre>
          ) : null}
        </div>
        <div className="panel">
          <h2>Input</h2>
          <pre className="log">{JSON.stringify(task.input, null, 2)}</pre>
        </div>
      </section>
      <section className="panel">
        <div className="panel-head">
          <h2>Steps and logs</h2>
          <span className="muted">{task.steps.length} recorded</span>
        </div>
        {task.steps.length === 0 ? <p className="muted">The worker has not recorded a step yet.</p> : null}
        <ol className="steps">
          {task.steps.map((step) => (
            <li key={step.id}>
              <div className="step-head">
                <strong>
                  {step.step_index + 1}. {step.name}
                </strong>
                <StatusBadge status={step.status} />
                <small>{formatTime(step.started_at)}</small>
              </div>
              {step.error ? <pre className="log error-log">{step.error}</pre> : null}
              {step.output ? <pre className="log">{JSON.stringify(step.output, null, 2)}</pre> : null}
            </li>
          ))}
        </ol>
      </section>
      {records.length > 0 ? (
        <section className="panel">
          <h2>Stored records</h2>
          {records.map((record) => (
            <pre className="log" key={record.id}>
              {record.collection}: {JSON.stringify(record.data, null, 2)}
            </pre>
          ))}
        </section>
      ) : null}
    </div>
  );
}
