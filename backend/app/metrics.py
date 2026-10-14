from prometheus_client import Counter, Gauge, Histogram

http_requests_total = Counter(
    "agentforge_http_requests_total",
    "Total HTTP requests handled by the API",
    ["method", "path", "status"],
)
http_request_duration_seconds = Histogram(
    "agentforge_http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "path"],
)
tasks_total = Counter(
    "agentforge_tasks_total",
    "Task state transitions recorded by workers",
    ["status"],
)
task_duration_seconds = Histogram(
    "agentforge_task_duration_seconds",
    "Time from task start to a terminal state",
)
queue_depth = Gauge(
    "agentforge_queue_depth",
    "Task ids currently waiting in the Redis list",
)
dead_letters_total = Counter(
    "agentforge_dead_letters_total",
    "Tasks moved to the dead-letter store",
)
tool_calls_total = Counter(
    "agentforge_tool_calls_total",
    "Allowlisted tool invocations",
    ["tool", "status"],
)
active_workers = Gauge(
    "agentforge_active_workers",
    "Workers that have published a recent heartbeat",
)
