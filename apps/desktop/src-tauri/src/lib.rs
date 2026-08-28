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
use std::sync::RwLock;
use tauri::{Manager, Runtime};
use tauri_plugin_dialog::DialogExt;
use url::Url;

mod library;

use library::{LibraryLocation, RegisteredCollection};

const VIDEO_EXTENSIONS: &[&str] = &["mp4", "m4v", "mov", "webm", "mkv"];
const MAX_STREAM_CHUNK: u64 = 2 * 1024 * 1024;
#[cfg(target_os = "linux")]
const WATCHCRAFT_WEB_ORIGIN: &str = "https://watchcraft.stream/";

#[derive(Default)]
struct ApprovedLibraryRoots(RwLock<Vec<PathBuf>>);

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

fn is_within_approved_roots(roots: &[PathBuf], path: &Path) -> bool {
    roots.iter().any(|root| path.starts_with(root))
}

fn canonical_video_roots<'a>(
    roots: impl IntoIterator<Item = &'a Path>,
) -> Result<Vec<PathBuf>, String> {
    roots
        .into_iter()
        .map(|root| {
            root.canonicalize().map_err(|error| {
                format!(
                    "Could not resolve an approved video folder {}: {error}",
                    root.display()
                )
            })
        })
        .collect()
}

#[cfg(any(target_os = "linux", test))]
fn is_youtube_request_url(requested_url: &str) -> bool {
    Url::parse(requested_url)
        .ok()
        .filter(|url| url.scheme() == "https")
        .and_then(|url| url.host_str().map(str::to_ascii_lowercase))
        .is_some_and(|host| {
            host == "youtube.com"
                || host.ends_with(".youtube.com")
                || host == "youtube-nocookie.com"
                || host.ends_with(".youtube-nocookie.com")
        })
}

fn validated_external_url(requested_url: &str) -> Result<Url, String> {
    let url = Url::parse(requested_url)
        .map_err(|_| "The requested external URL is invalid.".to_string())?;
    if url.scheme() != "https" {
        return Err("Only secure external URLs can be opened.".into());
    }
    let host = url
        .host_str()
        .map(str::to_ascii_lowercase)
        .ok_or_else(|| "The requested external URL has no host.".to_string())?;
    if host != "youtube.com" && !host.ends_with(".youtube.com") && host != "youtu.be" {
        return Err("Only YouTube links can be opened externally.".into());
    }
    Ok(url)
}

fn validated_video_path<R: Runtime>(
    app: &tauri::AppHandle<R>,
    requested_path: &str,
) -> Result<PathBuf, String> {
    let path = PathBuf::from(requested_path);
    if !path.is_file() || !is_video_path(&path) {
        return Err("The requested path is not a supported video file.".into());
    }
    let canonical_path = path
        .canonicalize()
        .map_err(|error| format!("Could not resolve the requested video: {error}"))?;
    let approved_roots = app.state::<ApprovedLibraryRoots>();
    let approved_roots = approved_roots
        .0
        .read()
        .map_err(|_| "The selected library state is unavailable.")?;
    if approved_roots.is_empty() {
        return Err("No library folder has been approved for this session.".into());
    }
    if !is_within_approved_roots(&approved_roots, &canonical_path) {
        return Err("The requested video is outside the selected library.".into());
    }
    Ok(canonical_path)
}

fn app_data_root<R: Runtime>(app: &tauri::AppHandle<R>) -> Result<PathBuf, String> {
    app.path()
        .app_data_dir()
        .map_err(|error| format!("Could not locate Watchcraft's private data folder: {error}"))
}

fn approve_library_location<R: Runtime>(
    app: &tauri::AppHandle<R>,
    location: LibraryLocation,
) -> Result<LibraryLocation, String> {
    app.asset_protocol_scope()
        .allow_directory(&location.metadata_root, true)
        .map_err(|error| format!("Could not allow collection access: {error}"))?;
    if let Some(media_root) = &location.media_root {
        app.asset_protocol_scope()
            .allow_directory(media_root, true)
            .map_err(|error| format!("Could not allow media access: {error}"))?;
    }
    if let Some(managed_media_root) = &location.managed_media_root {
        app.asset_protocol_scope()
            .allow_directory(managed_media_root, true)
            .map_err(|error| format!("Could not allow managed media access: {error}"))?;
    }
    let roots = canonical_video_roots(
        [
            location.media_root.as_deref(),
            location.managed_media_root.as_deref(),
        ]
        .into_iter()
        .flatten(),
    )?;
    let approved_roots = app.state::<ApprovedLibraryRoots>();
    *approved_roots
        .0
        .write()
        .map_err(|_| "The selected library state is unavailable.")? = roots;
    Ok(location)
}

fn install_selected_library<R: Runtime>(
    app: &tauri::AppHandle<R>,
    selected_root: &Path,
) -> Result<LibraryLocation, String> {
    let location = install_selected_library_with_activation(app, selected_root, true)?;
    approve_library_location(app, location)
}

fn install_selected_library_with_activation<R: Runtime>(
    app: &tauri::AppHandle<R>,
    selected_root: &Path,
    activate: bool,
) -> Result<LibraryLocation, String> {
    if !selected_root.is_dir() {
        return Err("The selected library folder is unavailable.".into());
    }
    library::install_from_folder_with_activation(&app_data_root(app)?, selected_root, activate)
}

fn load_current_library<R: Runtime>(
    app: &tauri::AppHandle<R>,
) -> Result<Option<LibraryLocation>, String> {
    library::load_current(&app_data_root(app)?)?
        .map(|location| approve_library_location(app, location))
        .transpose()
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
    let path = match validated_video_path(app, decoded_path.as_ref()) {
        Ok(path) => path,
        Err(error) => {
            eprintln!(
                "Watchcraft stream rejected {}: {error}",
                decoded_path.as_ref()
            );
            return Ok(Response::builder()
                .status(StatusCode::FORBIDDEN)
                .body(Vec::new())?);
        }
    };
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
fn open_external_url(url: String) -> Result<bool, String> {
    let url = validated_external_url(&url)?;

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
    return Err("Opening a browser is not supported on this platform yet.".into());

    #[cfg(not(any(target_os = "ios", target_os = "android")))]
    {
        command
            .arg(url.as_str())
            .spawn()
            .map(|_| true)
            .map_err(|error| format!("Could not open the browser: {error}"))
    }
}

#[tauri::command]
fn default_video_player(app: tauri::AppHandle, path: String) -> Result<Option<String>, String> {
    let path = validated_video_path(&app, &path)?;
    Ok(default_player_name(&path))
}

#[tauri::command]
fn load_current_collection(app: tauri::AppHandle) -> Result<Option<LibraryLocation>, String> {
    load_current_library(&app)
}

#[tauri::command]
fn list_registered_collections(app: tauri::AppHandle) -> Result<Vec<RegisteredCollection>, String> {
    library::list_collections(&app_data_root(&app)?)
}

#[tauri::command]
async fn choose_collection_folder(
    app: tauri::AppHandle,
    default_path: Option<String>,
    open_after: bool,
) -> Result<Option<LibraryLocation>, String> {
    let mut picker = app
        .dialog()
        .file()
        .set_title("Choose a Watchcraft collection folder or its parent");
    if let Some(default_path) = default_path {
        let path = PathBuf::from(default_path);
        if path.is_dir() {
            picker = picker.set_directory(path);
        }
    }
    let Some(selected) = picker.blocking_pick_folder() else {
        return Ok(None);
    };
    let selected = selected
        .into_path()
        .map_err(|error| format!("Could not read the selected folder: {error}"))?;
    install_selected_library_with_activation(&app, &selected, open_after)?;
    load_current_library(&app)
}

#[tauri::command]
async fn install_collection_url(
    app: tauri::AppHandle,
    url: String,
    open_after: bool,
) -> Result<Option<LibraryLocation>, String> {
    let data_root = app_data_root(&app)?;
    tauri::async_runtime::spawn_blocking(move || {
        library::install_from_url(&data_root, &url, open_after)
    })
    .await
    .map_err(|error| format!("The collection download could not finish: {error}"))??;
    load_current_library(&app)
}

#[tauri::command]
fn activate_registered_collection(
    app: tauri::AppHandle,
    collection_id: String,
) -> Result<LibraryLocation, String> {
    let location = library::activate_collection(&app_data_root(&app)?, &collection_id)?;
    approve_library_location(&app, location)
}

#[tauri::command]
fn remove_registered_collection(
    app: tauri::AppHandle,
    collection_id: String,
) -> Result<LibraryLocation, String> {
    let location = library::remove_collection(&app_data_root(&app)?, &collection_id)?;
    approve_library_location(&app, location)
}

#[tauri::command]
fn playback_smoke_library_root(app: tauri::AppHandle) -> Result<Option<String>, String> {
    let root = match std::env::var("WATCHCRAFT_PLAYBACK_SMOKE_LIBRARY") {
        Ok(root) => PathBuf::from(root),
        Err(_) => return Ok(None),
    };
    let location = if std::env::var("WATCHCRAFT_PLAYBACK_SMOKE_PRIME").as_deref() == Ok("1") {
        install_selected_library(&app, &root)?
    } else if let Some(location) = load_current_library(&app)? {
        location
    } else {
        return Err("Playback smoke collection was not restored from the registry.".into());
    };
    Ok(location
        .selected_root
        .map(|path| path.to_string_lossy().into_owned()))
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
        .manage(ApprovedLibraryRoots::default())
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_persisted_scope::init())
        .plugin(tauri_plugin_dialog::init())
        .register_asynchronous_uri_scheme_protocol("stream", |context, request, responder| {
            let response =
                video_stream_response(context.app_handle(), request).unwrap_or_else(|error| {
                    eprintln!("Watchcraft stream failed: {error}");
                    Response::builder()
                        .status(StatusCode::INTERNAL_SERVER_ERROR)
                        .body(Vec::new())
                        .expect("valid video error response")
                });
            responder.respond(response);
        })
        .setup(|_app| {
            #[cfg(target_os = "linux")]
            if let Some(main_window) = _app.get_webview_window("main") {
                main_window.with_webview(|platform_webview| {
                    use webkit2gtk::{URIRequestExt, WebViewExt};

                    platform_webview
                        .inner()
                        .connect_resource_load_started(|_, _, request| {
                            let Some(uri) = request.uri() else {
                                return;
                            };
                            if !is_youtube_request_url(uri.as_str()) {
                                return;
                            }
                            if let Some(headers) = request.http_headers() {
                                headers.replace("Referer", WATCHCRAFT_WEB_ORIGIN);
                            }
                        });
                })?;
            }
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            open_video,
            open_external_url,
            default_video_player,
            load_current_collection,
            list_registered_collections,
            choose_collection_folder,
            install_collection_url,
            activate_registered_collection,
            remove_registered_collection,
            playback_smoke_library_root,
            finish_playback_smoke
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

#[cfg(test)]
mod tests {
    use super::{
        canonical_video_roots, is_video_path, is_within_approved_roots, is_youtube_request_url,
        validated_external_url, video_content_type,
    };
    use std::fs;
    use std::path::Path;
    use std::time::{SystemTime, UNIX_EPOCH};

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
    fn identifies_only_secure_youtube_webview_requests() {
        assert!(is_youtube_request_url(
            "https://www.youtube-nocookie.com/embed/PjObX9XQvgI"
        ));
        assert!(is_youtube_request_url("https://www.youtube.com/player.js"));
        assert!(!is_youtube_request_url(
            "http://www.youtube.com/embed/video"
        ));
        assert!(!is_youtube_request_url(
            "https://youtube.example/embed/video"
        ));
    }

    #[test]
    fn allows_only_secure_youtube_external_links() {
        assert!(validated_external_url("https://www.youtube.com/watch?v=PjObX9XQvgI").is_ok());
        assert!(validated_external_url("https://youtu.be/PjObX9XQvgI").is_ok());
        assert!(validated_external_url("http://www.youtube.com/watch?v=PjObX9XQvgI").is_err());
        assert!(validated_external_url("https://example.com/watch?v=PjObX9XQvgI").is_err());
    }

    #[test]
    fn confines_video_paths_to_the_approved_library() {
        let root = Path::new("/library/courses");
        let roots = vec![root.to_path_buf()];
        assert!(is_within_approved_roots(
            &roots,
            Path::new("/library/courses/lesson/video.mp4")
        ));
        assert!(!is_within_approved_roots(
            &roots,
            Path::new("/library/courses-private/video.mp4")
        ));
        assert!(!is_within_approved_roots(
            &roots,
            Path::new("/library/other/video.mp4")
        ));
    }

    #[test]
    fn canonicalizes_approved_roots_before_comparing_video_paths() {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("system clock")
            .as_nanos();
        let root = std::env::temp_dir().join(format!(
            "watchcraft-approved-root-{}-{nonce}",
            std::process::id()
        ));
        let video = root.join("lesson.mp4");
        fs::create_dir_all(&root).expect("create temporary approved root");
        fs::write(&video, b"fixture").expect("create temporary video");

        let roots = canonical_video_roots([root.as_path()]).expect("canonical approved root");
        let canonical_video = video.canonicalize().expect("canonical video path");
        assert!(is_within_approved_roots(&roots, &canonical_video));

        #[cfg(target_os = "windows")]
        assert!(roots[0].to_string_lossy().starts_with(r"\\?\"));

        fs::remove_dir_all(root).expect("remove temporary approved root");
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
