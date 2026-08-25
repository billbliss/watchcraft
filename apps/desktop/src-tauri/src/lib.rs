use std::path::{Path, PathBuf};
use std::process::Command;
use tauri::Manager;

const VIDEO_EXTENSIONS: &[&str] = &["mp4", "m4v", "mov", "webm", "mkv"];

fn is_video_path(path: &Path) -> bool {
    path.extension()
        .and_then(|extension| extension.to_str())
        .map(|extension| VIDEO_EXTENSIONS.contains(&extension.to_ascii_lowercase().as_str()))
        .unwrap_or(false)
}

#[tauri::command]
fn open_video(app: tauri::AppHandle, path: String) -> Result<bool, String> {
    let path = PathBuf::from(path);
    if !path.is_file() || !is_video_path(&path) {
        return Err("The requested path is not a supported video file.".into());
    }
    if !app.asset_protocol_scope().is_allowed(&path) {
        return Err("The requested video is outside the selected library.".into());
    }

    #[cfg(target_os = "macos")]
    let mut command = Command::new("open");
    #[cfg(target_os = "windows")]
    let mut command = Command::new("explorer");
    #[cfg(all(
        unix,
        not(any(target_os = "macos", target_os = "ios", target_os = "android"))
    ))]
    let mut command = Command::new("xdg-open");
    #[cfg(any(target_os = "ios", target_os = "android"))]
    return Err("Opening a video in another app is not supported on this platform yet.".into());

    #[cfg(not(any(target_os = "ios", target_os = "android")))]
    {
        command
            .arg(&path)
            .spawn()
            .map(|_| true)
            .map_err(|error| format!("Could not open the video: {error}"))
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_persisted_scope::init())
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![open_video])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

#[cfg(test)]
mod tests {
    use super::is_video_path;
    use std::path::Path;

    #[test]
    fn accepts_supported_video_extensions_case_insensitively() {
        assert!(is_video_path(Path::new("lesson.MP4")));
        assert!(is_video_path(Path::new("lesson.mov")));
    }

    #[test]
    fn rejects_non_video_paths() {
        assert!(!is_video_path(Path::new("lesson.txt")));
        assert!(!is_video_path(Path::new("lesson")));
    }
}
