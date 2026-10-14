import { errorMessage } from "../lib/format";

const ACCESS_KEY = "agentforge_access_token";
const REFRESH_KEY = "agentforge_refresh_token";

export function getAccessToken(): string | null {
  return localStorage.getItem(ACCESS_KEY);
}

export function getRefreshToken(): string | null {
  return localStorage.getItem(REFRESH_KEY);
}

export function setTokens(access: string, refresh: string): void {
  localStorage.setItem(ACCESS_KEY, access);
  localStorage.setItem(REFRESH_KEY, refresh);
}

export function clearTokens(): void {
  localStorage.removeItem(ACCESS_KEY);
  localStorage.removeItem(REFRESH_KEY);
}

export class ApiError extends Error {
  status: number;
  code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

type RequestOptions = {
  method?: string;
  body?: unknown;
  headers?: Record<string, string>;
  signal?: AbortSignal;
  raw?: boolean;
};

async function refreshAccessToken(): Promise<boolean> {
  const refresh = getRefreshToken();
  if (!refresh) return false;
  const response = await fetch("/api/v1/auth/refresh", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refresh }),
  });
  if (!response.ok) {
    clearTokens();
    return false;
  }
  const payload = (await response.json()) as { access_token: string; refresh_token: string };
  setTokens(payload.access_token, payload.refresh_token);
  return true;
}

export async function apiFetch(path: string, options: RequestOptions = {}, retry = true): Promise<Response> {
  const headers: Record<string, string> = { ...(options.headers ?? {}) };
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  const token = getAccessToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  const response = await fetch(path, {
    method: options.method ?? "GET",
    headers,
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
    signal: options.signal,
  });
  if (response.status === 401 && retry && !path.startsWith("/api/v1/auth/")) {
    const refreshed = await refreshAccessToken();
    if (refreshed) return apiFetch(path, options, false);
  }
  return response;
}

export async function api<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const response = await apiFetch(path, options);
  if (response.status === 204) return undefined as T;
  const text = await response.text();
  const payload = text ? (JSON.parse(text) as unknown) : null;
  if (!response.ok) {
    const code =
      payload && typeof payload === "object" && "error" in payload
        ? String((payload as { error?: { code?: string } }).error?.code ?? "error")
        : "error";
    throw new ApiError(response.status, code, errorMessage(payload));
  }
  return payload as T;
}

export type User = {
  id: string;
  email: string;
  full_name: string;
  role: string;
  is_active: boolean;
  created_at: string;
};

export type TokenResponse = {
  access_token: string;
  refresh_token: string;
  expires_in: number;
  user: User;
};

export type Agent = {
  id: string;
  owner_id: string;
  name: string;
  description: string;
  system_prompt: string;
  provider: string | null;
  model: string | null;
  tools: string[];
  status: string;
  max_retries: number;
  timeout_seconds: number;
  created_at: string;
  updated_at: string;
};

export type TaskStep = {
  id: string;
  step_index: number;
  kind: string;
  name: string;
  status: string;
  input: Record<string, unknown> | null;
  output: Record<string, unknown> | null;
  error: string | null;
  started_at: string;
  finished_at: string | null;
};

export type Task = {
  id: string;
  agent_id: string;
  owner_id: string;
  idempotency_key: string;
  title: string;
  input: Record<string, unknown>;
  status: string;
  result: { summary?: string } | null;
  error: string | null;
  attempt: number;
  max_retries: number;
  dead_letter: boolean;
  cancel_requested: boolean;
  created_at: string;
  updated_at: string;
  queued_at: string | null;
  started_at: string | null;
  finished_at: string | null;
};

export type TaskDetail = Task & {
  steps: TaskStep[];
  agent_name: string | null;
};

export type Page<T> = {
  items: T[];
  total: number;
  page: number;
  page_size: number;
};

export type Activity = {
  id: string;
  event_type: string;
  message: string;
  created_at: string;
  agent_id: string | null;
  task_id: string | null;
};

export type Dashboard = {
  tasks_by_status: Record<string, number>;
  agents_by_status: Record<string, number>;
  recent_activity: Activity[];
  recent_tasks: Task[];
  system: {
    api: string;
    database: string;
    redis: string;
    queue_depth: number;
    active_workers: number;
    llm_provider: string;
  };
};

export type RecordItem = {
  id: string;
  collection: string;
  data: Record<string, unknown>;
  created_at: string;
  task_id: string | null;
};

export const TOOL_OPTIONS = [
  { id: "text_transform", label: "Text transform", detail: "Trim, classify, count, and reshape text" },
  { id: "branch", label: "Conditional branch", detail: "Choose a value from a comparison" },
  { id: "http_request", label: "HTTP request", detail: "Fetch a public URL with SSRF checks" },
  { id: "store_record", label: "Store record", detail: "Save a JSON record for this tenant" },
] as const;
