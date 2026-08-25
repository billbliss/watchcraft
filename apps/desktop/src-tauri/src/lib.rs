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
        .invoke_handler(tauri::generate_handler![open_video])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

#[cfg(test)]
mod tests {
    use super::{is_video_path, video_content_type};
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

    #[test]
    fn reports_video_content_types() {
        assert_eq!(video_content_type(Path::new("lesson.mp4")), "video/mp4");
        assert_eq!(
            video_content_type(Path::new("lesson.mov")),
            "video/quicktime"
        );
        assert_eq!(video_content_type(Path::new("lesson.webm")), "video/webm");
    }
}
