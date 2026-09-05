export type DiagnosticLevel = "debug" | "info" | "warn" | "error";

export interface DiagnosticEntry {
  sequence: number;
  sessionId: string;
  timestampMs: number;
  level: DiagnosticLevel;
  category: string;
  event: string;
  message: string;
  fields: Record<string, unknown>;
}

export interface DiagnosticSnapshot {
  enabled: boolean;
  sessionId: string;
  entries: DiagnosticEntry[];
}

export interface DiagnosticEvent {
  level: DiagnosticLevel;
  category: string;
  event: string;
  message: string;
  fields?: Record<string, unknown>;
}

export interface DiagnosticsService {
  readonly includePathsSupported: boolean;
  readonly persistenceLabel: string;
  record(event: DiagnosticEvent): void;
  snapshot(): Promise<DiagnosticSnapshot>;
  clear(): Promise<void>;
  export(includePaths: boolean): Promise<string | null>;
}

const WEB_DIAGNOSTICS_KEY = "watchcraftDiagnostics";
const MAX_WEB_ENTRIES = 500;

function safeStoredEntries(): DiagnosticEntry[] {
  try {
    const value: unknown = JSON.parse(window.localStorage.getItem(WEB_DIAGNOSTICS_KEY) ?? "[]");
    if (!Array.isArray(value)) return [];
    return value.filter((entry): entry is DiagnosticEntry => Boolean(
      entry
      && typeof entry === "object"
      && typeof (entry as DiagnosticEntry).sequence === "number"
      && typeof (entry as DiagnosticEntry).message === "string",
    )).slice(-MAX_WEB_ENTRIES);
  } catch {
    return [];
  }
}

export class WebDiagnosticsService implements DiagnosticsService {
  readonly includePathsSupported = false;
  readonly persistenceLabel = "Stored only in this browser";
  private entries = safeStoredEntries();
  private readonly sessionId = `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  private nextSequence = (this.entries.at(-1)?.sequence ?? 0) + 1;

  constructor() {
    this.record({
      level: "info",
      category: "system",
      event: "session.started",
      message: "Watchcraft Web diagnostics session started",
      fields: {
        userAgent: navigator.userAgent,
        language: navigator.language,
        locationUrl: window.location.href,
      },
    });
  }

  record(event: DiagnosticEvent): void {
    this.entries.push({
      sequence: this.nextSequence++,
      sessionId: this.sessionId,
      timestampMs: Date.now(),
      level: event.level,
      category: event.category,
      event: event.event,
      message: event.message,
      fields: event.fields ?? {},
    });
    this.entries = this.entries.slice(-MAX_WEB_ENTRIES);
    try {
      window.localStorage.setItem(WEB_DIAGNOSTICS_KEY, JSON.stringify(this.entries));
    } catch {
      // Diagnostics remain available in memory if browser storage is unavailable.
    }
  }

  async snapshot(): Promise<DiagnosticSnapshot> {
    return { enabled: true, sessionId: this.sessionId, entries: [...this.entries] };
  }

  async clear(): Promise<void> {
    this.entries = [];
    try {
      window.localStorage.removeItem(WEB_DIAGNOSTICS_KEY);
    } catch {
      // Clearing the in-memory entries is still useful without browser storage.
    }
  }

  async export(_includePaths: boolean): Promise<string> {
    const contents = this.entries.map((entry) => JSON.stringify(entry)).join("\n");
    const blob = new Blob([contents, contents ? "\n" : ""], { type: "application/x-ndjson" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "watchcraft-web-diagnostics.jsonl";
    link.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 0);
    return link.download;
  }
}

function consoleFields(values: unknown[]): Record<string, unknown> {
  return {
    arguments: values.map((value) => {
      if (value instanceof Error) {
        return { name: value.name, message: value.message, stack: value.stack };
      }
      try {
        return JSON.parse(JSON.stringify(value)) as unknown;
      } catch {
        return String(value);
      }
    }),
  };
}

export function installBrowserDiagnostics(service: DiagnosticsService): () => void {
  const originals = {
    debug: console.debug,
    error: console.error,
    info: console.info,
    log: console.log,
    warn: console.warn,
  };
  const levels: Array<keyof typeof originals> = ["debug", "info", "log", "warn", "error"];
  for (const method of levels) {
    console[method] = (...values: unknown[]) => {
      originals[method](...values);
      service.record({
        level: method === "log" ? "info" : method,
        category: "browser",
        event: `console.${method}`,
        message: values.map(String).join(" ").slice(0, 1_000),
        fields: consoleFields(values),
      });
    };
  }

  const onError = (event: ErrorEvent): void => service.record({
    level: "error",
    category: "browser",
    event: "window.error",
    message: event.message || "Unhandled browser error",
    fields: { filename: event.filename, line: event.lineno, column: event.colno, stack: event.error?.stack },
  });
  const onRejection = (event: PromiseRejectionEvent): void => service.record({
    level: "error",
    category: "browser",
    event: "promise.unhandledRejection",
    message: event.reason instanceof Error ? event.reason.message : String(event.reason),
    fields: event.reason instanceof Error ? { name: event.reason.name, stack: event.reason.stack } : {},
  });
  window.addEventListener("error", onError);
  window.addEventListener("unhandledrejection", onRejection);
  return () => {
    for (const method of levels) console[method] = originals[method];
    window.removeEventListener("error", onError);
    window.removeEventListener("unhandledrejection", onRejection);
  };
}

export function formatDiagnosticEntry(entry: DiagnosticEntry): string {
  const timestamp = new Date(entry.timestampMs).toISOString();
  const fields = Object.keys(entry.fields).length > 0 ? ` ${JSON.stringify(entry.fields)}` : "";
  return `${timestamp} ${entry.level.toUpperCase()} [${entry.category}] ${entry.event} — ${entry.message}${fields}`;
}
