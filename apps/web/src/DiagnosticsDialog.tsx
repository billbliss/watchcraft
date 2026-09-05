import { useEffect, useMemo, useState, type MouseEvent, type ReactElement } from "react";
import {
  formatDiagnosticEntry,
  type DiagnosticEntry,
  type DiagnosticsService,
} from "./diagnostics";

interface DiagnosticsDialogProps {
  onClose: () => void;
  service: DiagnosticsService;
}

export function DiagnosticsDialog({ onClose, service }: DiagnosticsDialogProps): ReactElement {
  const [entries, setEntries] = useState<DiagnosticEntry[]>([]);
  const [category, setCategory] = useState("all");
  const [includePaths, setIncludePaths] = useState(false);
  const [status, setStatus] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    const refresh = (): void => {
      void service.snapshot().then((snapshot) => {
        if (active) setEntries(snapshot.entries);
      }).catch((error: unknown) => {
        if (active) setStatus(error instanceof Error ? error.message : String(error));
      });
    };
    refresh();
    const interval = window.setInterval(refresh, 750);
    return () => {
      active = false;
      window.clearInterval(interval);
    };
  }, [service]);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent): void {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  const categories = useMemo(
    () => [...new Set(entries.map((entry) => entry.category))].sort(),
    [entries],
  );
  const visibleEntries = category === "all"
    ? entries
    : entries.filter((entry) => entry.category === category);
  const errors = entries.filter((entry) => entry.level === "error").length;
  const warnings = entries.filter((entry) => entry.level === "warn").length;

  function closeFromBackdrop(event: MouseEvent<HTMLDivElement>): void {
    if (event.target === event.currentTarget) onClose();
  }

  async function copyLogs(): Promise<void> {
    try {
      await navigator.clipboard.writeText(visibleEntries.map(formatDiagnosticEntry).join("\n"));
      setStatus(`Copied ${visibleEntries.length} log entries.`);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Could not copy diagnostics.");
    }
  }

  async function exportLogs(): Promise<void> {
    try {
      const destination = await service.export(includePaths);
      setStatus(destination ? `Exported ${destination}.` : "Export cancelled.");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Could not export diagnostics.");
    }
  }

  async function clearLogs(): Promise<void> {
    await service.clear();
    setEntries([]);
    setStatus("Diagnostics cleared.");
  }

  return (
    <div className="diagnostics-backdrop" onMouseDown={closeFromBackdrop}>
      <section aria-labelledby="diagnostics-title" aria-modal="true" className="diagnostics-dialog" role="dialog">
        <header className="diagnostics-header">
          <div>
            <span className="eyebrow">Watchcraft</span>
            <h2 id="diagnostics-title">Diagnostics</h2>
          </div>
          <button aria-label="Close diagnostics" className="diagnostics-close" onClick={onClose} type="button">×</button>
        </header>

        <div className="diagnostics-summary">
          <span className="diagnostics-recording"><i /> Recording</span>
          <span>{entries.length} events</span>
          <span>{errors} errors</span>
          <span>{warnings} warnings</span>
          <small>{service.persistenceLabel}</small>
        </div>

        <div className="diagnostics-toolbar">
          <label>
            Category
            <select onChange={(event) => setCategory(event.target.value)} value={category}>
              <option value="all">All</option>
              {categories.map((value) => <option key={value} value={value}>{value}</option>)}
            </select>
          </label>
          <div className="diagnostics-actions">
            <button onClick={() => void copyLogs()} type="button">Copy logs</button>
            <button className="primary-action" onClick={() => void exportLogs()} type="button">Export report…</button>
            <button onClick={() => void clearLogs()} type="button">Clear</button>
          </div>
        </div>

        {service.includePathsSupported ? (
          <label className="diagnostics-path-option">
            <input checked={includePaths} onChange={(event) => setIncludePaths(event.target.checked)} type="checkbox" />
            <span>Include full local paths in exported reports</span>
          </label>
        ) : (
          <p className="diagnostics-limitation">
            Web diagnostics include browser, collection, network, and playback events. Folder binding and native streaming are desktop-only.
          </p>
        )}

        <pre aria-label="Diagnostic log" className="diagnostics-log">
          {visibleEntries.length > 0
            ? visibleEntries.map(formatDiagnosticEntry).join("\n")
            : "No diagnostic events in this view."}
        </pre>
        {status ? <p className="diagnostics-status" role="status">{status}</p> : null}
      </section>
    </div>
  );
}
