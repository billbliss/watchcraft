use http::{
    header::{ACCEPT_RANGES, CACHE_CONTROL, CONTENT_LENGTH, CONTENT_RANGE, CONTENT_TYPE},
    Method, Request, Response, StatusCode,
};
use http_range::HttpRange;
use percent_encoding::percent_decode_str;
use std::error::Error;
use std::io::{Read, Seek, SeekFrom};
use std::path::{Path, PathBuf};
use std::process::Command;
use tauri::{Manager, Runtime};

const VIDEO_EXTENSIONS: &[&str] = &["mp4", "m4v", "mov", "webm", "mkv"];
const MAX_STREAM_CHUNK: u64 = 2 * 1024 * 1024;

fn is_video_path(path: &Path) -> bool {
    path.extension()
        .and_then(|extension| extension.to_str())
        .map(|extension| VIDEO_EXTENSIONS.contains(&extension.to_ascii_lowercase().as_str()))
        .unwrap_or(false)
}

fn video_content_type(path: &Path) -> &'static str {
    match path
        .extension()
        .and_then(|extension| extension.to_str())
        .map(str::to_ascii_lowercase)
        .as_deref()
    {
        Some("mov") => "video/quicktime",
        Some("webm") => "video/webm",
        Some("mkv") => "video/x-matroska",
        _ => "video/mp4",
    }
}

fn validated_video_path<R: Runtime>(
    app: &tauri::AppHandle<R>,
    requested_path: &str,
) -> Result<PathBuf, String> {
    let path = PathBuf::from(requested_path);
    if !path.is_file() || !is_video_path(&path) {
        return Err("The requested path is not a supported video file.".into());
    }
    if !app.asset_protocol_scope().is_allowed(&path) {
        return Err("The requested video is outside the selected library.".into());
    }
    Ok(path)
}

fn ensure_library_scope_inner<R: Runtime>(
    app: &tauri::AppHandle<R>,
    requested_root: &str,
) -> Result<bool, String> {
    let root = PathBuf::from(requested_root);
    if !root.is_dir() {
        return Ok(false);
    }
    let scope = app.asset_protocol_scope();
    if !scope.is_allowed(&root) {
        return Ok(false);
    }
    scope
        .allow_directory(&root, true)
        .map_err(|error| format!("Could not restore library access: {error}"))?;
    Ok(true)
}

#[cfg(target_os = "macos")]
fn default_player_name(path: &Path) -> Option<String> {
    let content_type = match path
        .extension()
        .and_then(|extension| extension.to_str())
        .map(str::to_ascii_lowercase)
        .as_deref()
    {
        Some("mov") => "com.apple.quicktime-movie",
        Some("webm") => "org.webmproject.webm",
        Some("mkv") => "org.matroska.mkv",
        _ => "public.mpeg-4",
    };
    let output = Command::new("/usr/bin/defaults")
        .args([
            "read",
            "com.apple.LaunchServices/com.apple.launchservices.secure",
            "LSHandlers",
        ])
        .output()
        .ok()?;
    if !output.status.success() {
        return None;
    }
    let preferences = String::from_utf8(output.stdout).ok()?;
    let bundle_identifier = macos_handler_for_content_type(&preferences, content_type)?;
    Some(macos_application_name(bundle_identifier))
}

#[cfg(target_os = "macos")]
fn macos_handler_for_content_type<'a>(preferences: &'a str, content_type: &str) -> Option<&'a str> {
    let marker = format!("LSHandlerContentType = \"{content_type}\";");
    preferences.split("},").find_map(|entry| {
        if !entry.contains(&marker) {
            return None;
        }
        entry.lines().rev().find_map(|line| {
            let line = line.trim();
            line.strip_prefix("LSHandlerRoleAll = ")
                .or_else(|| line.strip_prefix("LSHandlerRoleViewer = "))
                .and_then(|value| value.strip_suffix(';'))
                .map(|value| value.trim_matches('"'))
        })
    })
}

#[cfg(target_os = "macos")]
fn macos_application_name(bundle_identifier: &str) -> String {
    match bundle_identifier.to_ascii_lowercase().as_str() {
        "com.colliderli.iina" => "IINA".into(),
        "org.videolan.vlc" => "VLC".into(),
        "com.apple.quicktimeplayerx" => "QuickTime Player".into(),
        _ => bundle_identifier
            .rsplit('.')
            .next()
            .unwrap_or(bundle_identifier)
            .replace(['-', '_'], " "),
    }
}

#[cfg(all(
    unix,
    not(any(target_os = "macos", target_os = "ios", target_os = "android"))
))]
fn default_player_name(path: &Path) -> Option<String> {
    let output = Command::new("xdg-mime")
        .args(["query", "default", video_content_type(path)])
        .output()
        .ok()?;
    if !output.status.success() {
        return None;
    }
    let desktop_id = String::from_utf8(output.stdout).ok()?;
    let desktop_id = desktop_id.trim().strip_suffix(".desktop")?;
    desktop_id
        .rsplit('.')
        .next()
        .filter(|name| !name.is_empty())
        .map(|name| name.replace(['-', '_'], " "))
}

#[cfg(target_os = "windows")]
fn default_player_name(path: &Path) -> Option<String> {
    use std::iter;
    use std::ptr::{null, null_mut};
    use windows_sys::Win32::UI::Shell::{AssocQueryStringW, ASSOCF_NONE, ASSOCSTR_FRIENDLYAPPNAME};

    let extension = format!(".{}", path.extension()?.to_str()?);
    let association: Vec<u16> = extension.encode_utf16().chain(iter::once(0)).collect();
    let mut length = 0;
    unsafe {
        AssocQueryStringW(
            ASSOCF_NONE,
            ASSOCSTR_FRIENDLYAPPNAME,
            association.as_ptr(),
            null(),
            null_mut(),
            &mut length,
        );
    }
    if length <= 1 {
        return None;
    }

    let mut buffer = vec![0_u16; length as usize];
    let result = unsafe {
        AssocQueryStringW(
            ASSOCF_NONE,
            ASSOCSTR_FRIENDLYAPPNAME,
            association.as_ptr(),
            null(),
            buffer.as_mut_ptr(),
            &mut length,
        )
    };
    if result < 0 || length <= 1 {
        return None;
    }
    String::from_utf16(&buffer[..length as usize - 1]).ok()
}

#[cfg(any(target_os = "ios", target_os = "android"))]
fn default_player_name(_path: &Path) -> Option<String> {
    None
}

fn video_stream_response<R: Runtime>(
    app: &tauri::AppHandle<R>,
    request: Request<Vec<u8>>,
) -> Result<Response<Vec<u8>>, Box<dyn Error>> {
    let decoded_path =
        percent_decode_str(request.uri().path().trim_start_matches('/')).decode_utf8()?;
    let path = PathBuf::from(decoded_path.as_ref());

    if !path.is_file() || !is_video_path(&path) {
        return Ok(Response::builder()
            .status(StatusCode::NOT_FOUND)
            .body(Vec::new())?);
    }
    if !app.asset_protocol_scope().is_allowed(&path) {
        return Ok(Response::builder()
            .status(StatusCode::FORBIDDEN)
            .body(Vec::new())?);
    }
    if request.method() != Method::GET && request.method() != Method::HEAD {
        return Ok(Response::builder()
            .status(StatusCode::METHOD_NOT_ALLOWED)
            .body(Vec::new())?);
    }

    let mut file = std::fs::File::open(&path)?;
    let length = file.metadata()?.len();
    let response = Response::builder()
        .header(CONTENT_TYPE, video_content_type(&path))
        .header(ACCEPT_RANGES, "bytes")
        .header(CACHE_CONTROL, "no-store");

    if request.method() == Method::HEAD {
        return Ok(response
            .status(StatusCode::OK)
            .header(CONTENT_LENGTH, length)
            .body(Vec::new())?);
    }

    if let Some(range_header) = request.headers().get("range") {
        let not_satisfiable = || {
            Response::builder()
                .status(StatusCode::RANGE_NOT_SATISFIABLE)
                .header(CONTENT_RANGE, format!("bytes */{length}"))
                .body(Vec::new())
        };
        let ranges = match range_header
            .to_str()
            .ok()
            .and_then(|value| HttpRange::parse(value, length).ok())
        {
            Some(ranges) if ranges.len() == 1 => ranges,
            _ => return Ok(not_satisfiable()?),
        };
        let range = &ranges[0];
        let start = range.start;
        if start >= length || range.length == 0 {
            return Ok(not_satisfiable()?);
        }
        let bytes_to_read = range.length.min(MAX_STREAM_CHUNK).min(length - start);
        let end = start + bytes_to_read - 1;
        let mut body = Vec::with_capacity(bytes_to_read as usize);
        file.seek(SeekFrom::Start(start))?;
        file.take(bytes_to_read).read_to_end(&mut body)?;

        return Ok(response
            .status(StatusCode::PARTIAL_CONTENT)
            .header(CONTENT_RANGE, format!("bytes {start}-{end}/{length}"))
            .header(CONTENT_LENGTH, body.len())
            .body(body)?);
    }

    let mut body = Vec::with_capacity(length as usize);
    file.read_to_end(&mut body)?;
    Ok(response
        .status(StatusCode::OK)
        .header(CONTENT_LENGTH, body.len())
        .body(body)?)
}

#[tauri::command]
fn open_video(app: tauri::AppHandle, path: String) -> Result<bool, String> {
    let path = validated_video_path(&app, &path)?;

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

#[tauri::command]
fn default_video_player(app: tauri::AppHandle, path: String) -> Result<Option<String>, String> {
    let path = validated_video_path(&app, &path)?;
    Ok(default_player_name(&path))
}

#[tauri::command]
fn ensure_library_scope(app: tauri::AppHandle, path: String) -> Result<bool, String> {
    ensure_library_scope_inner(&app, &path)
}

#[tauri::command]
fn playback_smoke_library_root(app: tauri::AppHandle) -> Result<Option<String>, String> {
    let root = match std::env::var("WATCHCRAFT_PLAYBACK_SMOKE_LIBRARY") {
        Ok(root) => PathBuf::from(root),
        Err(_) => return Ok(None),
    };
    let root_string = root
        .to_str()
        .ok_or("Playback smoke library has no valid root directory")?;
    if !ensure_library_scope_inner(&app, root_string)? {
        return Err("Playback smoke library access was not restored.".into());
    }
    Ok(Some(root_string.to_owned()))
}

#[tauri::command]
fn finish_playback_smoke(
    app: tauri::AppHandle,
    passed: bool,
    detail: String,
) -> Result<(), String> {
    if std::env::var_os("WATCHCRAFT_PLAYBACK_SMOKE_LIBRARY").is_none() {
        return Err("Playback smoke mode is not enabled.".into());
    }
    if passed {
        println!("WATCHCRAFT_PLAYBACK_SMOKE_PASS: {detail}");
        app.exit(0);
    } else {
        eprintln!("WATCHCRAFT_PLAYBACK_SMOKE_FAIL: {detail}");
        app.exit(1);
    }
    Ok(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_persisted_scope::init())
        .plugin(tauri_plugin_dialog::init())
        .setup(|app| {
            if std::env::var("WATCHCRAFT_PLAYBACK_SMOKE_PRIME").as_deref() == Ok("1") {
                let root = std::env::var("WATCHCRAFT_PLAYBACK_SMOKE_LIBRARY")
                    .map_err(|_| "Playback smoke library is missing")?;
                app.asset_protocol_scope().allow_directory(root, true)?;
            }
            Ok(())
        })
        .register_asynchronous_uri_scheme_protocol("stream", |context, request, responder| {
            let response =
                video_stream_response(context.app_handle(), request).unwrap_or_else(|_| {
                    Response::builder()
                        .status(StatusCode::INTERNAL_SERVER_ERROR)
                        .body(Vec::new())
                        .expect("valid video error response")
                });
            responder.respond(response);
        })
        .invoke_handler(tauri::generate_handler![
            open_video,
            default_video_player,
            ensure_library_scope,
            playback_smoke_library_root,
            finish_playback_smoke
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

#[cfg(test)]
mod tests {
    use super::{is_video_path, video_content_type};
    use std::path::Path;

    #[cfg(target_os = "macos")]
    use super::{macos_application_name, macos_handler_for_content_type};

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

    #[test]
    fn reports_video_content_types() {
        assert_eq!(video_content_type(Path::new("lesson.mp4")), "video/mp4");
        assert_eq!(
            video_content_type(Path::new("lesson.mov")),
            "video/quicktime"
        );
        assert_eq!(video_content_type(Path::new("lesson.webm")), "video/webm");
    }

    #[cfg(target_os = "macos")]
    #[test]
    fn reads_the_default_player_from_macos_preferences() {
        let preferences = r#"(
            {
                LSHandlerContentType = "public.mpeg-4";
                LSHandlerPreferredVersions = {
                    LSHandlerRoleAll = "-";
                };
                LSHandlerRoleAll = "com.colliderli.iina";
            },
        )"#;
        let handler = macos_handler_for_content_type(preferences, "public.mpeg-4");
        assert_eq!(handler, Some("com.colliderli.iina"));
        assert_eq!(macos_application_name(handler.unwrap()), "IINA");
    }
}
