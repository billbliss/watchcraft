use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use std::collections::VecDeque;
use std::fs::{self, File, OpenOptions};
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use std::time::{SystemTime, UNIX_EPOCH};

const MAX_ENTRIES: usize = 2_000;
const MAX_LOG_BYTES: u64 = 5 * 1024 * 1024;
const RETAINED_LOGS: usize = 2;

#[derive(Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct DiagnosticEntry {
    sequence: u64,
    session_id: String,
    timestamp_ms: u128,
    level: String,
    category: String,
    event: String,
    message: String,
    fields: Value,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct DiagnosticSnapshot {
    pub(crate) enabled: bool,
    pub(crate) session_id: String,
    pub(crate) entries: Vec<DiagnosticEntry>,
}

struct DiagnosticInner {
    enabled: bool,
    session_id: String,
    next_sequence: u64,
    entries: VecDeque<DiagnosticEntry>,
    log_path: Option<PathBuf>,
}

impl Default for DiagnosticInner {
    fn default() -> Self {
        Self {
            enabled: false,
            session_id: String::new(),
            next_sequence: 1,
            entries: VecDeque::new(),
            log_path: None,
        }
    }
}

#[derive(Default)]
pub(crate) struct DiagnosticsState(Mutex<DiagnosticInner>);

fn unix_millis() -> u128 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis()
}

fn rotate_logs(log_directory: &Path) -> Result<PathBuf, String> {
    fs::create_dir_all(log_directory)
        .map_err(|error| format!("Could not create the diagnostics folder: {error}"))?;
    for index in (1..=RETAINED_LOGS).rev() {
        let source = if index == 1 {
            log_directory.join("diagnostics.jsonl")
        } else {
            log_directory.join(format!("diagnostics-{}.jsonl", index - 1))
        };
        let destination = log_directory.join(format!("diagnostics-{index}.jsonl"));
        if source.exists() {
            let _ = fs::remove_file(&destination);
            fs::rename(&source, &destination)
                .map_err(|error| format!("Could not rotate a diagnostics file: {error}"))?;
        }
    }
    Ok(log_directory.join("diagnostics.jsonl"))
}

fn read_retained_entries(log_directory: &Path) -> VecDeque<DiagnosticEntry> {
    let mut entries = VecDeque::new();
    for index in (1..=RETAINED_LOGS).rev() {
        let path = log_directory.join(format!("diagnostics-{index}.jsonl"));
        let Ok(file) = File::open(path) else {
            continue;
        };
        for line in BufReader::new(file).lines().map_while(Result::ok) {
            if let Ok(entry) = serde_json::from_str::<DiagnosticEntry>(&line) {
                if entries.len() == MAX_ENTRIES {
                    entries.pop_front();
                }
                entries.push_back(entry);
            }
        }
    }
    entries
}

impl DiagnosticsState {
    pub(crate) fn initialize(
        &self,
        enabled: bool,
        app_data_root: &Path,
        version: &str,
        identifier: &str,
    ) -> Result<(), String> {
        let session_id = format!("{}-{}", unix_millis(), std::process::id());
        let log_directory = app_data_root.join("diagnostics");
        let log_path = if enabled {
            Some(rotate_logs(&log_directory)?)
        } else {
            None
        };
        let retained_entries = enabled
            .then(|| read_retained_entries(&log_directory))
            .unwrap_or_default();
        let next_sequence = retained_entries
            .iter()
            .map(|entry| entry.sequence)
            .max()
            .unwrap_or(0)
            + 1;
        {
            let mut inner = self
                .0
                .lock()
                .map_err(|_| "The diagnostics state is unavailable.".to_string())?;
            inner.enabled = enabled;
            inner.session_id = session_id;
            inner.next_sequence = next_sequence;
            inner.entries = retained_entries;
            inner.log_path = log_path;
        }
        self.record(
            "info",
            "system",
            "session.started",
            "Watchcraft diagnostics session started",
            serde_json::json!({
                "appVersion": version,
                "identifier": identifier,
                "os": std::env::consts::OS,
                "architecture": std::env::consts::ARCH,
            }),
        );
        Ok(())
    }

    pub(crate) fn record(
        &self,
        level: &str,
        category: &str,
        event: &str,
        message: &str,
        fields: Value,
    ) {
        let Ok(mut inner) = self.0.lock() else {
            return;
        };
        if !inner.enabled {
            return;
        }
        let entry = DiagnosticEntry {
            sequence: inner.next_sequence,
            session_id: inner.session_id.clone(),
            timestamp_ms: unix_millis(),
            level: level.into(),
            category: category.into(),
            event: event.into(),
            message: message.into(),
            fields,
        };
        inner.next_sequence += 1;
        if inner.entries.len() == MAX_ENTRIES {
            inner.entries.pop_front();
        }
        inner.entries.push_back(entry.clone());
        if let Some(log_path) = &inner.log_path {
            let should_write = fs::metadata(log_path)
                .map(|metadata| metadata.len() < MAX_LOG_BYTES)
                .unwrap_or(true);
            if should_write {
                if let Ok(mut file) = OpenOptions::new().create(true).append(true).open(log_path) {
                    if let Ok(line) = serde_json::to_string(&entry) {
                        let _ = writeln!(file, "{line}");
                    }
                }
            }
        }
    }

    pub(crate) fn snapshot(&self) -> DiagnosticSnapshot {
        self.0
            .lock()
            .map(|inner| DiagnosticSnapshot {
                enabled: inner.enabled,
                session_id: inner.session_id.clone(),
                entries: inner.entries.iter().cloned().collect(),
            })
            .unwrap_or_else(|_| DiagnosticSnapshot {
                enabled: false,
                session_id: String::new(),
                entries: Vec::new(),
            })
    }

    pub(crate) fn clear(&self) -> Result<(), String> {
        let mut inner = self
            .0
            .lock()
            .map_err(|_| "The diagnostics state is unavailable.".to_string())?;
        inner.entries.clear();
        if let Some(log_path) = &inner.log_path {
            File::create(log_path)
                .map_err(|error| format!("Could not clear the diagnostics file: {error}"))?;
        }
        Ok(())
    }

    pub(crate) fn export(&self, destination: &Path, include_paths: bool) -> Result<(), String> {
        let snapshot = self.snapshot();
        let mut file = File::create(destination)
            .map_err(|error| format!("Could not create the diagnostic report: {error}"))?;
        for mut entry in snapshot.entries {
            if !include_paths {
                redact_sensitive_fields(&mut entry.fields);
            }
            let line = serde_json::to_string(&entry)
                .map_err(|error| format!("Could not format the diagnostic report: {error}"))?;
            writeln!(file, "{line}")
                .map_err(|error| format!("Could not write the diagnostic report: {error}"))?;
        }
        Ok(())
    }
}

fn redact_sensitive_fields(value: &mut Value) {
    match value {
        Value::Object(fields) => redact_object(fields),
        Value::Array(values) => values.iter_mut().for_each(redact_sensitive_fields),
        _ => {}
    }
}

fn redact_object(fields: &mut Map<String, Value>) {
    for (key, value) in fields {
        let key = key.to_ascii_lowercase();
        if key.contains("path") || key.contains("root") || key.contains("url") {
            *value = Value::String("<redacted>".into());
        } else {
            redact_sensitive_fields(value);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::DiagnosticsState;
    use std::fs;
    use std::time::{SystemTime, UNIX_EPOCH};

    fn temporary_root(label: &str) -> std::path::PathBuf {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        std::env::temp_dir().join(format!("watchcraft-diagnostics-{label}-{nonce}"))
    }

    #[test]
    fn records_and_redacts_sensitive_export_fields() {
        let root = temporary_root("redaction");
        let state = DiagnosticsState::default();
        state
            .initialize(true, &root, "1.2.3-beta.1", "app.watchcraft.reader.beta")
            .unwrap();
        state.record(
            "error",
            "playback",
            "media.error",
            "Embedded playback failed",
            serde_json::json!({
                "mediaPath": r"D:\Videos\lesson.mp4",
                "mediaErrorCode": 4,
            }),
        );

        let destination = root.join("redacted.jsonl");
        state.export(&destination, false).unwrap();
        let report = fs::read_to_string(destination).unwrap();
        assert!(report.contains("<redacted>"));
        assert!(!report.contains(r"D:\\Videos"));
        assert!(report.contains("mediaErrorCode"));
        assert_eq!(state.snapshot().entries.len(), 2);

        let restored = DiagnosticsState::default();
        restored
            .initialize(true, &root, "1.2.3-beta.1", "app.watchcraft.reader.beta")
            .unwrap();
        let restored_snapshot = restored.snapshot();
        assert!(restored_snapshot
            .entries
            .iter()
            .any(|entry| entry.event == "media.error"));
        assert_ne!(
            restored_snapshot.entries.first().unwrap().session_id,
            restored_snapshot.entries.last().unwrap().session_id
        );

        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn disabled_diagnostics_do_not_collect_entries() {
        let root = temporary_root("disabled");
        let state = DiagnosticsState::default();
        state
            .initialize(false, &root, "1.2.3", "app.watchcraft.reader")
            .unwrap();
        state.record(
            "info",
            "system",
            "ignored",
            "Ignored",
            serde_json::json!({}),
        );
        assert!(!state.snapshot().enabled);
        assert!(state.snapshot().entries.is_empty());
    }
}
