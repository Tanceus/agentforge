import { FormEvent, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { TOOL_OPTIONS, api, type Agent } from "../api/client";
import { ErrorState, LoadingState } from "../components/States";

const DEFAULT_PROMPT =
  "Triage the customer message. Classify urgency, branch priority versus standard, and store the record.";

export function AgentFormPage() {
  const { agentId } = useParams();
  const navigate = useNavigate();
  const editing = Boolean(agentId);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [systemPrompt, setSystemPrompt] = useState(DEFAULT_PROMPT);
  const [tools, setTools] = useState<string[]>(["text_transform", "branch", "store_record"]);
  const [maxRetries, setMaxRetries] = useState(2);
  const [timeoutSeconds, setTimeoutSeconds] = useState(60);
  const [provider, setProvider] = useState("");
  const [model, setModel] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(editing);
  const [pending, setPending] = useState(false);

  useEffect(() => {
    if (!agentId) return;
    api<Agent>(`/api/v1/agents/${agentId}`)
      .then((agent) => {
        setName(agent.name);
        setDescription(agent.description);
        setSystemPrompt(agent.system_prompt);
        setTools(agent.tools);
        setMaxRetries(agent.max_retries);
        setTimeoutSeconds(agent.timeout_seconds);
        setProvider(agent.provider ?? "");
        setModel(agent.model ?? "");
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, [agentId]);

  function toggleTool(tool: string) {
    setTools((current) => (current.includes(tool) ? current.filter((item) => item !== tool) : [...current, tool]));
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setPending(true);
    setError("");
    const body = {
      name,
      description,
      system_prompt: systemPrompt,
      tools,
      max_retries: maxRetries,
      timeout_seconds: timeoutSeconds,
      provider: provider || null,
      model: model || null,
    };
    try {
      const agent = editing
        ? await api<Agent>(`/api/v1/agents/${agentId}`, { method: "PATCH", body })
        : await api<Agent>("/api/v1/agents", { method: "POST", body });
      navigate(`/agents/${agent.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setPending(false);
    }
  }

  if (loading) return <LoadingState label="Loading agent" />;
  if (error && editing && !name) return <ErrorState message={error} />;

  return (
    <div className="page narrow">
      <header className="page-head">
        <div>
          <p className="eyebrow">{editing ? "Edit" : "Create"}</p>
          <h1>{editing ? "Edit agent" : "New agent"}</h1>
        </div>
        <Link to={editing ? `/agents/${agentId}` : "/agents"}>Back</Link>
      </header>
      <form className="stack-form" onSubmit={onSubmit}>
        <label>
          Name
          <input value={name} onChange={(event) => setName(event.target.value)} required maxLength={120} />
        </label>
        <label>
          Description
          <input value={description} onChange={(event) => setDescription(event.target.value)} maxLength={2000} />
        </label>
        <label>
          System prompt
          <textarea value={systemPrompt} onChange={(event) => setSystemPrompt(event.target.value)} required rows={5} />
        </label>
        <fieldset>
          <legend>Tools</legend>
          {TOOL_OPTIONS.map((tool) => (
            <label key={tool.id} className="check">
              <input type="checkbox" checked={tools.includes(tool.id)} onChange={() => toggleTool(tool.id)} />
              <span>
                <strong>{tool.label}</strong>
                <small>{tool.detail}</small>
              </span>
            </label>
          ))}
        </fieldset>
        <div className="inline-fields">
          <label>
            Max retries
            <input
              type="number"
              min={0}
              max={10}
              value={maxRetries}
              onChange={(event) => setMaxRetries(Number(event.target.value))}
            />
          </label>
          <label>
            Timeout seconds
            <input
              type="number"
              min={5}
              max={300}
              value={timeoutSeconds}
              onChange={(event) => setTimeoutSeconds(Number(event.target.value))}
            />
          </label>
        </div>
        <div className="inline-fields">
          <label>
            Provider
            <select value={provider} onChange={(event) => setProvider(event.target.value)}>
              <option value="">Use server default</option>
              <option value="mock">Mock</option>
              <option value="openai">OpenAI-compatible</option>
            </select>
          </label>
          <label>
            Model
            <input value={model} onChange={(event) => setModel(event.target.value)} placeholder="mock-triage-v1" />
          </label>
        </div>
        {error ? <p className="form-error">{error}</p> : null}
        <button className="button" type="submit" disabled={pending || tools.length === 0}>
          {pending ? "Saving…" : editing ? "Save changes" : "Create agent"}
        </button>
      </form>
    </div>
  );
}
