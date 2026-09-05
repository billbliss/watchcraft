use http::{
    header::{ACCEPT_RANGES, CACHE_CONTROL, CONTENT_LENGTH, CONTENT_RANGE, CONTENT_TYPE},
    Method, Request, Response, StatusCode,
};
use http_range::HttpRange;
use percent_encoding::percent_decode_str;
use std::error::Error;
#[cfg(any(target_os = "linux", test))]
use std::io::Write;
use std::io::{Read, Seek, SeekFrom};
#[cfg(any(target_os = "linux", test))]
use std::net::{TcpListener, TcpStream};
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::RwLock;
#[cfg(any(target_os = "linux", test))]
use std::time::Duration;
use tauri::{Manager, Runtime};
use tauri_plugin_dialog::DialogExt;
use url::Url;

mod diagnostics;
mod library;

use diagnostics::{DiagnosticSnapshot, DiagnosticsState};
use library::{LibraryLocation, RegisteredCollection};

const VIDEO_EXTENSIONS: &[&str] = &["mp4", "m4v", "mov", "webm", "mkv"];
const MAX_STREAM_CHUNK: u64 = 2 * 1024 * 1024;
const HOSTED_YOUTUBE_BRIDGE_URL: &str = "https://watchcraft.stream/youtube-player/";

#[derive(Default)]
struct ApprovedLibraryRoots(RwLock<Vec<PathBuf>>);

struct YoutubeBridgeBaseUrl(String);

#[derive(Default)]
struct VideoStreamBaseUrl(RwLock<Option<String>>);

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

fn configured_youtube_bridge_base_url() -> String {
    HOSTED_YOUTUBE_BRIDGE_URL.to_string()
}

#[cfg(any(target_os = "linux", test))]
fn linux_deep_link_schemes_to_register(
    is_beta: bool,
    public_handler_is_usable: bool,
) -> Vec<&'static str> {
    if !is_beta {
        return vec!["watchcraft"];
    }

    let mut schemes = vec!["watchcraft-beta"];
    if !public_handler_is_usable {
        schemes.push("watchcraft");
    }
    schemes
}

#[cfg(target_os = "linux")]
fn linux_default_deep_link_handler(scheme: &str) -> Option<String> {
    let mime_type = format!("x-scheme-handler/{scheme}");
    let output = Command::new("xdg-mime")
        .args(["query", "default", mime_type.as_str()])
        .output()
        .ok()?;
    if !output.status.success() {
        return None;
    }

    let handler = String::from_utf8(output.stdout).ok()?;
    let handler = handler.trim();
    (!handler.is_empty()).then(|| handler.to_string())
}

#[cfg(target_os = "linux")]
fn linux_desktop_exec_command(contents: &str) -> Option<&str> {
    let value = contents
        .lines()
        .find_map(|line| line.strip_prefix("Exec="))?
        .trim();
    if let Some(quoted) = value.strip_prefix('"') {
        quoted
            .split('"')
            .next()
            .filter(|command| !command.is_empty())
    } else {
        value
            .split_ascii_whitespace()
            .next()
            .filter(|command| !command.is_empty())
    }
}

#[cfg(target_os = "linux")]
fn linux_command_exists(command: &str) -> bool {
    let command_path = Path::new(command);
    if command_path.is_absolute() || command.contains('/') {
        return command_path.is_file();
    }

    std::env::var_os("PATH")
        .map(|path| std::env::split_paths(&path).any(|directory| directory.join(command).is_file()))
        .unwrap_or(false)
}

#[cfg(target_os = "linux")]
fn linux_desktop_handler_is_usable<R: Runtime>(app: &tauri::AppHandle<R>, handler: &str) -> bool {
    let handler_path = Path::new(handler);
    if handler_path.file_name().and_then(|name| name.to_str()) != Some(handler) {
        return false;
    }

    let mut application_directories = Vec::new();
    if let Ok(data_dir) = app.path().data_dir() {
        application_directories.push(data_dir.join("applications"));
    }
    if let Some(data_dirs) = std::env::var_os("XDG_DATA_DIRS") {
        application_directories.extend(
            std::env::split_paths(&data_dirs).map(|directory| directory.join("applications")),
        );
    } else {
        application_directories.push(PathBuf::from("/usr/local/share/applications"));
        application_directories.push(PathBuf::from("/usr/share/applications"));
    }

    application_directories.into_iter().any(|directory| {
        std::fs::read_to_string(directory.join(handler))
            .ok()
            .and_then(|contents| linux_desktop_exec_command(&contents).map(str::to_string))
            .map(|command| linux_command_exists(&command))
            .unwrap_or(false)
    })
}

#[cfg(target_os = "linux")]
fn register_linux_deep_link_handlers<R: Runtime>(app: &tauri::AppHandle<R>) {
    use tauri_plugin_deep_link::DeepLinkExt;

    let is_beta = app.config().identifier == "app.watchcraft.reader.beta";
    let public_handler_is_usable = linux_default_deep_link_handler("watchcraft")
        .map(|handler| linux_desktop_handler_is_usable(app, &handler))
        .unwrap_or(false);

    for scheme in linux_deep_link_schemes_to_register(is_beta, public_handler_is_usable) {
        if let Err(error) = app.deep_link().register(scheme) {
            eprintln!("Watchcraft could not register {scheme} links: {error}");
        }
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

fn requested_byte_range(range_header: Option<&str>, length: u64) -> Result<Option<(u64, u64)>, ()> {
    let Some(range_header) = range_header else {
        return Ok(None);
    };
    let ranges = HttpRange::parse(range_header, length).map_err(|_| ())?;
    if ranges.len() != 1 {
        return Err(());
    }
    let range = &ranges[0];
    if range.start >= length || range.length == 0 {
        return Err(());
    }
    Ok(Some((
        range.start,
        range.length.min(MAX_STREAM_CHUNK).min(length - range.start),
    )))
}

#[cfg(any(target_os = "linux", test))]
fn linux_stream_token() -> Result<String, String> {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut random = [0_u8; 32];
    std::fs::File::open("/dev/urandom")
        .and_then(|mut source| source.read_exact(&mut random))
        .map_err(|error| format!("Could not create the private video stream token: {error}"))?;
    let mut token = String::with_capacity(random.len() * 2);
    for byte in random {
        token.push(HEX[(byte >> 4) as usize] as char);
        token.push(HEX[(byte & 0x0f) as usize] as char);
    }
    Ok(token)
}

#[cfg(any(target_os = "linux", test))]
struct LinuxHttpRequest {
    method: String,
    target: String,
    range: Option<String>,
}

#[cfg(any(target_os = "linux", test))]
fn read_linux_http_request(stream: &mut TcpStream) -> Result<LinuxHttpRequest, String> {
    const MAX_HEADER_BYTES: usize = 16 * 1024;
    let mut bytes = Vec::with_capacity(2048);
    let mut buffer = [0_u8; 2048];
    while !bytes.windows(4).any(|window| window == b"\r\n\r\n") {
        if bytes.len() >= MAX_HEADER_BYTES {
            return Err("The request headers are too large.".into());
        }
        let read = stream
            .read(&mut buffer)
            .map_err(|error| format!("Could not read the request: {error}"))?;
        if read == 0 {
            return Err("The request ended before its headers were complete.".into());
        }
        bytes.extend_from_slice(&buffer[..read]);
    }
    let headers = std::str::from_utf8(&bytes)
        .map_err(|_| "The request headers are not valid UTF-8.".to_string())?;
    let mut lines = headers.split("\r\n");
    let mut request_line = lines
        .next()
        .ok_or_else(|| "The request line is missing.".to_string())?
        .split_ascii_whitespace();
    let method = request_line
        .next()
        .ok_or_else(|| "The request method is missing.".to_string())?
        .to_string();
    let target = request_line
        .next()
        .ok_or_else(|| "The request target is missing.".to_string())?
        .to_string();
    let range = lines.find_map(|line| {
        let (name, value) = line.split_once(':')?;
        name.eq_ignore_ascii_case("range")
            .then(|| value.trim().to_string())
    });
    Ok(LinuxHttpRequest {
        method,
        target,
        range,
    })
}

#[cfg(any(target_os = "linux", test))]
fn write_linux_http_headers<W: Write>(
    stream: &mut W,
    status: &str,
    headers: &[(&str, String)],
) -> std::io::Result<()> {
    write!(stream, "HTTP/1.1 {status}\r\n")?;
    for (name, value) in headers {
        write!(stream, "{name}: {value}\r\n")?;
    }
    write!(stream, "Connection: close\r\n\r\n")?;
    Ok(())
}

#[cfg(any(target_os = "linux", test))]
fn write_linux_http_error<W: Write>(stream: &mut W, status: &str) -> std::io::Result<()> {
    write_linux_http_headers(
        stream,
        status,
        &[
            ("Content-Length", "0".into()),
            ("Cache-Control", "no-store".into()),
            ("Access-Control-Allow-Origin", "*".into()),
        ],
    )
}

#[cfg(any(target_os = "linux", test))]
fn write_linux_video_response<W: Write>(
    stream: &mut W,
    path: &Path,
    method: &str,
    range_header: Option<&str>,
) -> Result<(), String> {
    let mut file = std::fs::File::open(path)
        .map_err(|error| format!("Could not open the requested video: {error}"))?;
    let length = file
        .metadata()
        .map_err(|error| format!("Could not inspect the requested video: {error}"))?
        .len();
    let byte_range = match requested_byte_range(range_header, length) {
        Ok(range) => range,
        Err(()) => {
            write_linux_http_headers(
                stream,
                "416 Range Not Satisfiable",
                &[
                    ("Content-Length", "0".into()),
                    ("Content-Range", format!("bytes */{length}")),
                    ("Accept-Ranges", "bytes".into()),
                    ("Cache-Control", "no-store".into()),
                    ("Access-Control-Allow-Origin", "*".into()),
                ],
            )
            .map_err(|error| format!("Could not reject the video range: {error}"))?;
            return Ok(());
        }
    };
    let (status, start, response_length, content_range) = match byte_range {
        Some((start, response_length)) => (
            "206 Partial Content",
            start,
            response_length,
            Some(format!(
                "bytes {start}-{}/{length}",
                start + response_length - 1
            )),
        ),
        None => ("200 OK", 0, length, None),
    };
    let mut headers = vec![
        ("Content-Type", video_content_type(path).into()),
        ("Content-Length", response_length.to_string()),
        ("Accept-Ranges", "bytes".into()),
        ("Cache-Control", "no-store".into()),
        ("Access-Control-Allow-Origin", "*".into()),
        ("X-Content-Type-Options", "nosniff".into()),
    ];
    if let Some(content_range) = content_range {
        headers.push(("Content-Range", content_range));
    }
    write_linux_http_headers(stream, status, &headers)
        .map_err(|error| format!("Could not start the video response: {error}"))?;
    if method == "HEAD" || response_length == 0 {
        return Ok(());
    }
    file.seek(SeekFrom::Start(start))
        .map_err(|error| format!("Could not seek in the requested video: {error}"))?;
    std::io::copy(&mut file.take(response_length), stream)
        .map_err(|error| format!("Could not stream the requested video: {error}"))?;
    Ok(())
}

#[cfg(any(target_os = "linux", test))]
fn serve_linux_video_request(
    app: &tauri::AppHandle,
    token: &str,
    mut stream: TcpStream,
) -> Result<(), String> {
    stream
        .set_read_timeout(Some(Duration::from_secs(5)))
        .map_err(|error| format!("Could not configure the video request: {error}"))?;
    stream
        .set_write_timeout(Some(Duration::from_secs(30)))
        .map_err(|error| format!("Could not configure the video response: {error}"))?;
    let request = read_linux_http_request(&mut stream)?;
    if request.method != "GET" && request.method != "HEAD" {
        write_linux_http_error(&mut stream, "405 Method Not Allowed")
            .map_err(|error| format!("Could not reject the video request: {error}"))?;
        return Ok(());
    }

    let request_url = Url::parse(&format!("http://127.0.0.1{}", request.target))
        .map_err(|_| "The video request URL is invalid.".to_string())?;
    if request_url.path() != format!("/{token}") {
        write_linux_http_error(&mut stream, "404 Not Found")
            .map_err(|error| format!("Could not reject the video request: {error}"))?;
        return Ok(());
    }
    let Some(requested_path) = request_url
        .query_pairs()
        .find_map(|(name, value)| (name == "path").then(|| value.into_owned()))
    else {
        write_linux_http_error(&mut stream, "400 Bad Request")
            .map_err(|error| format!("Could not reject the video request: {error}"))?;
        return Ok(());
    };
    let path = match validated_video_path(app, &requested_path) {
        Ok(path) => path,
        Err(error) => {
            eprintln!("Watchcraft local video stream rejected a path: {error}");
            write_linux_http_error(&mut stream, "403 Forbidden").map_err(|write_error| {
                format!("Could not reject the video request: {write_error}")
            })?;
            return Ok(());
        }
    };

    write_linux_video_response(
        &mut stream,
        &path,
        &request.method,
        request.range.as_deref(),
    )
}

#[cfg(any(target_os = "linux", test))]
fn start_linux_video_stream_server(app: tauri::AppHandle) -> Result<String, String> {
    let listener = TcpListener::bind(("127.0.0.1", 0))
        .map_err(|error| format!("Could not start the private video stream: {error}"))?;
    let address = listener
        .local_addr()
        .map_err(|error| format!("Could not inspect the private video stream: {error}"))?;
    let token = linux_stream_token()?;
    let base_url = format!("http://127.0.0.1:{}/{}", address.port(), token);
    std::thread::Builder::new()
        .name("watchcraft-video-stream".into())
        .spawn(move || {
            for connection in listener.incoming() {
                match connection {
                    Ok(stream) => {
                        let app = app.clone();
                        let token = token.clone();
                        if let Err(error) = std::thread::Builder::new()
                            .name("watchcraft-video-request".into())
                            .spawn(move || {
                                if let Err(error) = serve_linux_video_request(&app, &token, stream)
                                {
                                    eprintln!("Watchcraft local video stream failed: {error}");
                                }
                            })
                        {
                            eprintln!("Watchcraft could not accept a video request: {error}");
                        }
                    }
                    Err(error) => {
                        eprintln!("Watchcraft local video stream stopped: {error}");
                        break;
                    }
                }
            }
        })
        .map_err(|error| format!("Could not run the private video stream: {error}"))?;
    Ok(base_url)
}

fn app_data_root<R: Runtime>(app: &tauri::AppHandle<R>) -> Result<PathBuf, String> {
    app.path()
        .app_data_dir()
        .map_err(|error| format!("Could not locate Watchcraft's private data folder: {error}"))
}

fn diagnostics_enabled_for_identifier(identifier: &str) -> bool {
    identifier.ends_with(".beta") || identifier.ends_with(".dev") || identifier.ends_with(".smoke")
}

fn record_diagnostic<R: Runtime>(
    app: &tauri::AppHandle<R>,
    level: &str,
    category: &str,
    event: &str,
    message: &str,
    fields: serde_json::Value,
) {
    app.state::<DiagnosticsState>()
        .record(level, category, event, message, fields);
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
    record_diagnostic(
        app,
        "info",
        "binding",
        "scope.approved",
        "Approved collection and media roots for this session",
        serde_json::json!({
            "collectionId": location.collection_id,
            "metadataRoot": location.metadata_root,
            "mediaRoot": location.media_root,
            "managedMediaRoot": location.managed_media_root,
        }),
    );
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
    let requested_range = request
        .headers()
        .get("range")
        .and_then(|value| value.to_str().ok())
        .map(str::to_string);
    record_diagnostic(
        app,
        "debug",
        "stream",
        "request.received",
        "Received a local video stream request",
        serde_json::json!({
            "method": request.method().as_str(),
            "requestedPath": decoded_path.as_ref(),
            "range": requested_range,
        }),
    );
    let path = match validated_video_path(app, decoded_path.as_ref()) {
        Ok(path) => path,
        Err(error) => {
            eprintln!(
                "Watchcraft stream rejected {}: {error}",
                decoded_path.as_ref()
            );
            record_diagnostic(
                app,
                "error",
                "stream",
                "request.rejected",
                "Rejected a local video stream path",
                serde_json::json!({ "requestedPath": decoded_path.as_ref(), "error": error }),
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
    record_diagnostic(
        app,
        "debug",
        "stream",
        "file.opened",
        "Opened the requested local video",
        serde_json::json!({
            "path": path,
            "length": length,
            "contentType": video_content_type(&path),
        }),
    );
    let response = Response::builder()
        .header(CONTENT_TYPE, video_content_type(&path))
        .header(ACCEPT_RANGES, "bytes")
        .header(CACHE_CONTROL, "no-store");

    if request.method() == Method::HEAD {
        record_diagnostic(
            app,
            "debug",
            "stream",
            "response.sent",
            "Returned local video metadata",
            serde_json::json!({ "status": 200, "length": length }),
        );
        return Ok(response
            .status(StatusCode::OK)
            .header(CONTENT_LENGTH, length)
            .body(Vec::new())?);
    }

    if request.headers().contains_key("range") {
        let not_satisfiable = || {
            Response::builder()
                .status(StatusCode::RANGE_NOT_SATISFIABLE)
                .header(CONTENT_RANGE, format!("bytes */{length}"))
                .body(Vec::new())
        };
        let range_header = request
            .headers()
            .get("range")
            .and_then(|value| value.to_str().ok());
        let (start, bytes_to_read) = match requested_byte_range(range_header, length) {
            Ok(Some(range)) => range,
            _ => {
                record_diagnostic(
                    app,
                    "warn",
                    "stream",
                    "range.rejected",
                    "Rejected an invalid local video byte range",
                    serde_json::json!({ "range": range_header, "length": length, "status": 416 }),
                );
                return Ok(not_satisfiable()?);
            }
        };
        let end = start + bytes_to_read - 1;
        let mut body = Vec::with_capacity(bytes_to_read as usize);
        file.seek(SeekFrom::Start(start))?;
        file.take(bytes_to_read).read_to_end(&mut body)?;

        record_diagnostic(
            app,
            "debug",
            "stream",
            "response.sent",
            "Returned a local video byte range",
            serde_json::json!({
                "status": 206,
                "start": start,
                "end": end,
                "fileLength": length,
                "responseBytes": body.len(),
            }),
        );

        return Ok(response
            .status(StatusCode::PARTIAL_CONTENT)
            .header(CONTENT_RANGE, format!("bytes {start}-{end}/{length}"))
            .header(CONTENT_LENGTH, body.len())
            .body(body)?);
    }

    let mut body = Vec::with_capacity(length as usize);
    file.read_to_end(&mut body)?;
    record_diagnostic(
        app,
        "debug",
        "stream",
        "response.sent",
        "Returned a complete local video",
        serde_json::json!({ "status": 200, "fileLength": length, "responseBytes": body.len() }),
    );
    Ok(response
        .status(StatusCode::OK)
        .header(CONTENT_LENGTH, body.len())
        .body(body)?)
}

#[tauri::command]
fn open_video(app: tauri::AppHandle, path: String) -> Result<bool, String> {
    record_diagnostic(
        &app,
        "info",
        "playback",
        "external.requested",
        "Requested playback in the operating system's default player",
        serde_json::json!({ "path": path }),
    );
    let path = match validated_video_path(&app, &path) {
        Ok(path) => path,
        Err(error) => {
            record_diagnostic(
                &app,
                "error",
                "playback",
                "external.rejected",
                "Rejected the external playback path",
                serde_json::json!({ "path": path, "error": error }),
            );
            return Err(error);
        }
    };

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
        match command.arg(&path).spawn() {
            Ok(_) => {
                record_diagnostic(
                    &app,
                    "info",
                    "playback",
                    "external.opened",
                    "Sent the video to the operating system's default player",
                    serde_json::json!({ "path": path }),
                );
                Ok(true)
            }
            Err(error) => {
                record_diagnostic(
                    &app,
                    "error",
                    "playback",
                    "external.failed",
                    "The operating system could not open the video",
                    serde_json::json!({ "path": path, "error": error.to_string() }),
                );
                Err(format!("Could not open the video: {error}"))
            }
        }
    }
}

#[tauri::command]
fn open_external_url(url: String) -> Result<bool, String> {
    let url = validated_external_url(&url)?;

    #[cfg(target_os = "windows")]
    {
        use std::iter;
        use std::ptr::{null, null_mut};
        use windows_sys::Win32::UI::Shell::ShellExecuteW;
        use windows_sys::Win32::UI::WindowsAndMessaging::SW_SHOWNORMAL;

        let operation: Vec<u16> = "open".encode_utf16().chain(iter::once(0)).collect();
        let target: Vec<u16> = url.as_str().encode_utf16().chain(iter::once(0)).collect();
        let result = unsafe {
            ShellExecuteW(
                null_mut(),
                operation.as_ptr(),
                target.as_ptr(),
                null(),
                null(),
                SW_SHOWNORMAL,
            )
        };
        return if result as isize > 32 {
            Ok(true)
        } else {
            Err(format!(
                "Windows could not open the browser (ShellExecuteW returned {}).",
                result as isize
            ))
        };
    }

    #[cfg(target_os = "macos")]
    let mut command = Command::new("open");
    #[cfg(all(
        unix,
        not(any(target_os = "macos", target_os = "ios", target_os = "android"))
    ))]
    let mut command = Command::new("xdg-open");
    #[cfg(any(target_os = "ios", target_os = "android"))]
    return Err("Opening a browser is not supported on this platform yet.".into());

    #[cfg(any(
        target_os = "macos",
        all(
            unix,
            not(any(target_os = "macos", target_os = "ios", target_os = "android"))
        )
    ))]
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
fn youtube_bridge_base_url(bridge: tauri::State<YoutubeBridgeBaseUrl>) -> String {
    bridge.0.clone()
}

#[tauri::command]
fn video_stream_base_url(
    stream: tauri::State<VideoStreamBaseUrl>,
) -> Result<Option<String>, String> {
    stream
        .0
        .read()
        .map(|base_url| base_url.clone())
        .map_err(|_| "The local video stream state is unavailable.".into())
}

#[tauri::command]
fn diagnostics_snapshot(diagnostics: tauri::State<DiagnosticsState>) -> DiagnosticSnapshot {
    diagnostics.snapshot()
}

#[tauri::command]
fn record_frontend_diagnostic(
    diagnostics: tauri::State<DiagnosticsState>,
    level: String,
    category: String,
    event: String,
    message: String,
    fields: serde_json::Value,
) {
    diagnostics.record(&level, &category, &event, &message, fields);
}

#[tauri::command]
fn clear_diagnostics(diagnostics: tauri::State<DiagnosticsState>) -> Result<(), String> {
    diagnostics.clear()
}

#[tauri::command]
async fn export_diagnostics(
    app: tauri::AppHandle,
    include_paths: bool,
) -> Result<Option<String>, String> {
    let Some(destination) = app
        .dialog()
        .file()
        .set_title("Export Watchcraft diagnostic report")
        .set_file_name("watchcraft-diagnostics.jsonl")
        .add_filter("JSON Lines", &["jsonl"])
        .blocking_save_file()
    else {
        return Ok(None);
    };
    let destination = destination
        .into_path()
        .map_err(|error| format!("Could not read the diagnostic report destination: {error}"))?;
    app.state::<DiagnosticsState>()
        .export(&destination, include_paths)?;
    record_diagnostic(
        &app,
        "info",
        "diagnostics",
        "report.exported",
        "Exported a diagnostic report",
        serde_json::json!({ "path": destination, "includedPaths": include_paths }),
    );
    Ok(Some(destination.to_string_lossy().into_owned()))
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
    let install_root = data_root.clone();
    let location = tauri::async_runtime::spawn_blocking(move || {
        library::install_from_url(&install_root, &url, open_after)
    })
    .await
    .map_err(|error| format!("The collection download could not finish: {error}"))??;
    let is_current = library::load_current(&data_root)?
        .is_some_and(|current| current.collection_id == location.collection_id);
    if is_current {
        approve_library_location(&app, location).map(Some)
    } else {
        Ok(Some(location))
    }
}

#[tauri::command]
async fn choose_collection_media_folder(
    app: tauri::AppHandle,
    collection_id: String,
    default_path: Option<String>,
) -> Result<Option<LibraryLocation>, String> {
    let data_root = app_data_root(&app)?;
    let existing_binding = library::collection_media_binding(&data_root, &collection_id)?;
    let mut picker = app
        .dialog()
        .file()
        .set_title("Choose the folder containing this collection's videos");
    let suggested_path = existing_binding.or_else(|| default_path.map(PathBuf::from));
    if let Some(path) = suggested_path.filter(|path| path.is_dir()) {
        picker = picker.set_directory(path);
    }
    let Some(selected) = picker.blocking_pick_folder() else {
        record_diagnostic(
            &app,
            "info",
            "binding",
            "folder.cancelled",
            "Media folder selection was cancelled",
            serde_json::json!({ "collectionId": collection_id }),
        );
        return Ok(None);
    };
    let selected = selected
        .into_path()
        .map_err(|error| format!("Could not read the selected folder: {error}"))?;
    record_diagnostic(
        &app,
        "info",
        "binding",
        "folder.selected",
        "Selected a folder for referenced local media",
        serde_json::json!({ "collectionId": collection_id, "selectedPath": selected }),
    );
    let bound = match library::bind_collection_media(&data_root, &collection_id, &selected) {
        Ok(bound) => bound,
        Err(error) => {
            record_diagnostic(
                &app,
                "error",
                "binding",
                "folder.rejected",
                "The selected media folder could not be bound",
                serde_json::json!({
                    "collectionId": collection_id,
                    "selectedPath": selected,
                    "error": error,
                }),
            );
            return Err(error);
        }
    };
    record_diagnostic(
        &app,
        "info",
        "binding",
        "folder.bound",
        "Bound the collection to its referenced local media",
        serde_json::json!({
            "collectionId": collection_id,
            "mediaRoot": bound.media_root,
            "mediaPathPrefix": bound.media_path_prefix,
            "mediaExpected": bound.media_expected,
            "mediaFound": bound.media_found,
            "mediaExtra": bound.media_extra,
        }),
    );
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
fn set_registered_collection_archived(
    app: tauri::AppHandle,
    collection_id: String,
    archived: bool,
) -> Result<LibraryLocation, String> {
    let location =
        library::set_collection_archived(&app_data_root(&app)?, &collection_id, archived)?;
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
    let configured_youtube_bridge_base_url = configured_youtube_bridge_base_url();

    let builder = tauri::Builder::default();
    #[cfg(desktop)]
    let builder = builder
        // The single-instance plugin must be registered first so Linux and Windows
        // can forward deep links to an app that is already open.
        .plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.unminimize();
                let _ = window.show();
                let _ = window.set_focus();
            }
        }))
        .plugin(tauri_plugin_deep_link::init());

    builder
        .manage(ApprovedLibraryRoots::default())
        .manage(YoutubeBridgeBaseUrl(configured_youtube_bridge_base_url))
        .manage(VideoStreamBaseUrl::default())
        .manage(DiagnosticsState::default())
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_persisted_scope::init())
        .plugin(tauri_plugin_dialog::init())
        .register_asynchronous_uri_scheme_protocol("stream", |context, request, responder| {
            let response =
                video_stream_response(context.app_handle(), request).unwrap_or_else(|error| {
                    eprintln!("Watchcraft stream failed: {error}");
                    record_diagnostic(
                        context.app_handle(),
                        "error",
                        "stream",
                        "response.failed",
                        "The local video stream failed",
                        serde_json::json!({ "error": error.to_string() }),
                    );
                    Response::builder()
                        .status(StatusCode::INTERNAL_SERVER_ERROR)
                        .body(Vec::new())
                        .expect("valid video error response")
                });
            responder.respond(response);
        })
        .setup(|_app| {
            let identifier = _app.config().identifier.clone();
            let diagnostics_enabled = diagnostics_enabled_for_identifier(&identifier);
            _app.state::<DiagnosticsState>()
                .initialize(
                    diagnostics_enabled,
                    &app_data_root(_app.handle()).map_err(std::io::Error::other)?,
                    &_app.package_info().version.to_string(),
                    &identifier,
                )
                .map_err(std::io::Error::other)?;
            #[cfg(any(target_os = "linux", test))]
            {
                let base_url = start_linux_video_stream_server(_app.handle().clone())
                    .map_err(std::io::Error::other)?;
                *_app.state::<VideoStreamBaseUrl>().0.write().map_err(|_| {
                    std::io::Error::other("The local video stream state is unavailable.")
                })? = Some(base_url);
            }
            #[cfg(target_os = "linux")]
            {
                // Debian desktop databases do not always refresh immediately after a
                // sideloaded package is installed. Registering at startup creates a
                // per-user handler and makes both cold- and warm-start links reliable.
                // Beta only claims the public scheme when no working handler exists,
                // so it remains a website-link fallback without stealing stable's links.
                register_linux_deep_link_handlers(_app.handle());
            }
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            open_video,
            open_external_url,
            default_video_player,
            youtube_bridge_base_url,
            video_stream_base_url,
            diagnostics_snapshot,
            record_frontend_diagnostic,
            clear_diagnostics,
            export_diagnostics,
            load_current_collection,
            list_registered_collections,
            choose_collection_folder,
            install_collection_url,
            choose_collection_media_folder,
            activate_registered_collection,
            set_registered_collection_archived,
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
        canonical_video_roots, configured_youtube_bridge_base_url,
        diagnostics_enabled_for_identifier, is_video_path, is_within_approved_roots,
        linux_deep_link_schemes_to_register, requested_byte_range, validated_external_url,
        video_content_type, write_linux_video_response, MAX_STREAM_CHUNK,
    };
    use std::fs;
    use std::path::Path;
    use std::time::{SystemTime, UNIX_EPOCH};

    #[test]
    fn diagnostics_follow_the_application_channel_identity() {
        assert!(diagnostics_enabled_for_identifier(
            "app.watchcraft.reader.beta"
        ));
        assert!(diagnostics_enabled_for_identifier(
            "app.watchcraft.reader.dev"
        ));
        assert!(diagnostics_enabled_for_identifier(
            "app.watchcraft.reader.smoke"
        ));
        assert!(!diagnostics_enabled_for_identifier("app.watchcraft.reader"));
    }

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
    fn allows_only_secure_youtube_external_links() {
        assert!(validated_external_url("https://www.youtube.com/watch?v=PjObX9XQvgI").is_ok());
        assert!(validated_external_url("https://youtu.be/PjObX9XQvgI").is_ok());
        assert!(validated_external_url("http://www.youtube.com/watch?v=PjObX9XQvgI").is_err());
        assert!(validated_external_url("https://example.com/watch?v=PjObX9XQvgI").is_err());
    }

    #[test]
    fn desktop_youtube_playback_uses_the_hosted_https_bridge() {
        assert_eq!(
            configured_youtube_bridge_base_url(),
            "https://watchcraft.stream/youtube-player/"
        );
    }

    #[test]
    fn stable_claims_the_public_linux_deep_link_scheme() {
        assert_eq!(
            linux_deep_link_schemes_to_register(false, false),
            vec!["watchcraft"]
        );
    }

    #[test]
    fn beta_preserves_a_working_public_linux_deep_link_handler() {
        assert_eq!(
            linux_deep_link_schemes_to_register(true, true),
            vec!["watchcraft-beta"]
        );
    }

    #[test]
    fn beta_falls_back_for_public_linux_deep_links_when_needed() {
        assert_eq!(
            linux_deep_link_schemes_to_register(true, false),
            vec!["watchcraft-beta", "watchcraft"]
        );
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

    #[test]
    fn bounds_open_ended_video_ranges_to_streaming_chunks() {
        assert_eq!(
            requested_byte_range(Some("bytes=100-"), 10 * 1024 * 1024),
            Ok(Some((100, MAX_STREAM_CHUNK)))
        );
    }

    #[test]
    fn rejects_multiple_or_unsatisfiable_video_ranges() {
        assert_eq!(requested_byte_range(Some("bytes=0-10,20-30"), 100), Err(()));
        assert_eq!(requested_byte_range(Some("bytes=100-"), 100), Err(()));
    }

    #[test]
    fn writes_seekable_linux_video_responses_without_buffering_the_whole_file() {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("system clock")
            .as_nanos();
        let path = std::env::temp_dir().join(format!(
            "watchcraft-video-response-{}-{nonce}.mp4",
            std::process::id()
        ));
        fs::write(&path, b"0123456789").expect("create temporary video");

        let mut response = Vec::new();
        write_linux_video_response(&mut response, &path, "GET", Some("bytes=2-5"))
            .expect("write partial response");
        let header_end = response
            .windows(4)
            .position(|window| window == b"\r\n\r\n")
            .expect("response header terminator")
            + 4;
        let headers = std::str::from_utf8(&response[..header_end]).expect("response headers");
        assert!(headers.starts_with("HTTP/1.1 206 Partial Content\r\n"));
        assert!(headers.contains("Content-Range: bytes 2-5/10\r\n"));
        assert!(headers.contains("Content-Length: 4\r\n"));
        assert_eq!(&response[header_end..], b"2345");

        fs::remove_file(path).expect("remove temporary video");
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
