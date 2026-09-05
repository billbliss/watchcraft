import { invoke } from "@tauri-apps/api/core";
import type {
  DiagnosticEvent,
  DiagnosticSnapshot,
  DiagnosticsService,
} from "../../web/src/diagnostics";

export class DesktopDiagnosticsService implements DiagnosticsService {
  readonly includePathsSupported = true;
  readonly persistenceLabel = "Stored in Watchcraft's private application data";

  record(event: DiagnosticEvent): void {
    void invoke("record_frontend_diagnostic", {
      level: event.level,
      category: event.category,
      event: event.event,
      message: event.message,
      fields: event.fields ?? {},
    }).catch(() => undefined);
  }

  snapshot(): Promise<DiagnosticSnapshot> {
    return invoke<DiagnosticSnapshot>("diagnostics_snapshot");
  }

  clear(): Promise<void> {
    return invoke("clear_diagnostics");
  }

  export(includePaths: boolean): Promise<string | null> {
    return invoke<string | null>("export_diagnostics", { includePaths });
  }
}
