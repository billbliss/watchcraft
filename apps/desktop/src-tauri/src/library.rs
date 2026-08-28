use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::io::Read;
use std::path::{Component, Path, PathBuf};
use std::time::Duration;
use url::Url;

const COLLECTION_KIND: &str = "watchcraft.collection";
const COLLECTION_SCHEMA_VERSION: u64 = 4;
const LIBRARY_SCHEMA_VERSION: u64 = 1;
const MANIFEST_SCAN_LIMIT: u64 = 64 * 1024 * 1024;
const REMOTE_FILE_LIMIT: usize = 64 * 1024 * 1024;
const REMOTE_TOTAL_LIMIT: usize = 256 * 1024 * 1024;
const VIDEO_EXTENSIONS: &[&str] = &["mp4", "m4v", "mov", "webm", "mkv"];

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct LibraryLocation {
    pub(crate) selected_root: Option<PathBuf>,
    pub(crate) collection_id: String,
    pub(crate) manifest_path: PathBuf,
    pub(crate) metadata_root: PathBuf,
    pub(crate) media_root: Option<PathBuf>,
    pub(crate) managed_media_root: Option<PathBuf>,
    pub(crate) media_expected: usize,
    pub(crate) media_found: usize,
    pub(crate) media_extra: usize,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct RegisteredCollection {
    pub(crate) collection_id: String,
    pub(crate) title: String,
    pub(crate) revision: u64,
    pub(crate) source_type: String,
    pub(crate) source_label: String,
    pub(crate) active: bool,
    pub(crate) archived: bool,
    pub(crate) media_expected: usize,
    pub(crate) media_found: usize,
    pub(crate) media_extra: usize,
    pub(crate) media_modes: Vec<String>,
}

#[allow(dead_code)]
#[derive(Debug, Deserialize)]
struct CollectionManifest {
    kind: String,
    schema_version: u64,
    collection_id: String,
    title: String,
    revision: u64,
    topic_scope: String,
    root: serde_json::Value,
    topics: serde_json::Value,
    topic_families: serde_json::Value,
    stats: serde_json::Value,
    content_hash: String,
    #[serde(default)]
    media_root_hint: Option<PathBuf>,
    items: BTreeMap<String, CollectionItem>,
}

#[allow(dead_code)]
#[derive(Debug, Deserialize)]
struct CollectionItem {
    item_id: String,
    title: String,
    #[serde(default)]
    media: Vec<MediaReference>,
    #[serde(default)]
    transcript: TranscriptReference,
    analysis: AnalysisReference,
    summary: String,
    locations: Vec<serde_json::Value>,
    topic_ids: Vec<String>,
    family_ids: Vec<String>,
    topic_sections: BTreeMap<String, Vec<usize>>,
    chapter_count: usize,
}

#[allow(dead_code)]
#[derive(Debug, Deserialize)]
#[serde(tag = "type")]
enum MediaReference {
    #[serde(rename = "local-file")]
    LocalFile {
        #[serde(default)]
        delivery: Option<MediaDelivery>,
        relative_path: PathBuf,
    },
    #[serde(rename = "youtube")]
    YouTube {
        #[serde(default)]
        delivery: Option<MediaDelivery>,
        video_id: String,
        #[serde(default)]
        url: Option<String>,
    },
    #[serde(rename = "http-video")]
    HttpVideo {
        #[serde(default)]
        delivery: Option<MediaDelivery>,
        url: String,
    },
}

#[derive(Clone, Copy, Debug, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "kebab-case")]
enum MediaDelivery {
    ManagedLocal,
    ReferencedLocal,
    Remote,
}

#[derive(Debug, Default)]
struct MediaInventory {
    managed_local: Vec<PathBuf>,
    referenced_local: Vec<PathBuf>,
    remote_count: usize,
}

#[derive(Debug, Default, Deserialize)]
struct TranscriptReference {
    subtitles: Option<PathBuf>,
    text: Option<PathBuf>,
    segments: Option<PathBuf>,
}

#[derive(Debug, Deserialize)]
struct AnalysisReference {
    path: PathBuf,
}

#[derive(Debug, Serialize, Deserialize)]
struct LibraryRegistry {
    schema_version: u64,
    current_collection_id: Option<String>,
    collections: BTreeMap<String, InstalledCollection>,
}

impl Default for LibraryRegistry {
    fn default() -> Self {
        Self {
            schema_version: LIBRARY_SCHEMA_VERSION,
            current_collection_id: None,
            collections: BTreeMap::new(),
        }
    }
}

#[derive(Debug, Serialize, Deserialize)]
struct InstalledCollection {
    collection_id: String,
    title: String,
    revision: u64,
    manifest_path: PathBuf,
    metadata_root: PathBuf,
    source: CollectionSource,
    media_binding: Option<DirectoryBinding>,
    media_expected: usize,
    media_found: usize,
    media_extra: usize,
    enabled: bool,
}

#[derive(Debug, Serialize, Deserialize)]
#[serde(tag = "type")]
enum CollectionSource {
    #[serde(rename = "local-manifest")]
    LocalManifest {
        manifest_path: PathBuf,
        selected_root: PathBuf,
    },
    #[serde(rename = "remote-manifest")]
    RemoteManifest { url: String },
}

#[derive(Debug, Serialize, Deserialize)]
struct DirectoryBinding {
    #[serde(rename = "type")]
    binding_type: String,
    path: PathBuf,
}

pub(crate) fn install_from_folder_with_activation(
    app_data_root: &Path,
    selected_root: &Path,
    activate: bool,
) -> Result<LibraryLocation, String> {
    let selected_root = selected_root
        .canonicalize()
        .map_err(|error| format!("Could not resolve the selected folder: {error}"))?;
    let manifest_path = discover_manifest(&selected_root)?;
    let manifest = read_manifest(&manifest_path)?;
    let metadata_source_root = manifest_path
        .parent()
        .ok_or("The collection manifest has no parent folder.")?
        .canonicalize()
        .map_err(|error| format!("Could not resolve the collection folder: {error}"))?;
    let media = media_inventory(&manifest)?;
    let media_root = resolve_media_root(
        &selected_root,
        &metadata_source_root,
        manifest.media_root_hint.as_deref(),
        &media.referenced_local,
    )?;

    let safe_id = safe_component(&manifest.collection_id)?;
    let revision_root = app_data_root
        .join("collections")
        .join(safe_id)
        .join("revisions")
        .join(manifest.revision.to_string());
    let private_manifest_path = revision_root.join("manifest.json");
    if !installed_revision_is_complete(&revision_root, &manifest, &media) {
        install_metadata_revision(
            &metadata_source_root,
            &manifest_path,
            &manifest,
            &revision_root,
        )?;
    }
    let managed_media_root = revision_root.join("managed-media");
    let managed_found = media
        .managed_local
        .iter()
        .filter(|relative| managed_media_root.join(relative).is_file())
        .count();
    let (_, referenced_found, media_extra) =
        media_stats(media_root.as_deref(), &media.referenced_local);
    let media_expected = media.managed_local.len() + media.referenced_local.len();
    let media_found = managed_found + referenced_found;

    let mut registry = read_registry(app_data_root)?;
    let relative_revision = revision_root
        .strip_prefix(app_data_root)
        .map_err(|_| "Private collection storage is outside the Watchcraft data folder.")?
        .to_path_buf();
    let relative_manifest = private_manifest_path
        .strip_prefix(app_data_root)
        .map_err(|_| "Private manifest storage is outside the Watchcraft data folder.")?
        .to_path_buf();
    let installed = InstalledCollection {
        collection_id: manifest.collection_id.clone(),
        title: manifest.title,
        revision: manifest.revision,
        manifest_path: relative_manifest,
        metadata_root: relative_revision,
        source: CollectionSource::LocalManifest {
            manifest_path,
            selected_root: selected_root.clone(),
        },
        media_binding: media_root.clone().map(|path| DirectoryBinding {
            binding_type: "directory".into(),
            path,
        }),
        media_expected,
        media_found,
        media_extra,
        enabled: true,
    };
    let collection_id = manifest.collection_id.clone();
    if activate || registry.current_collection_id.is_none() {
        registry.current_collection_id = Some(collection_id.clone());
    }
    registry
        .collections
        .insert(collection_id.clone(), installed);
    write_registry(app_data_root, &registry)?;
    location_for_id(app_data_root, &registry, &collection_id)
        .ok_or_else(|| "The installed collection could not be reopened.".into())
}

pub(crate) fn install_from_url(
    app_data_root: &Path,
    manifest_url: &str,
    activate: bool,
) -> Result<LibraryLocation, String> {
    let requested_url = parse_remote_url(manifest_url)?;
    let client = reqwest::blocking::Client::builder()
        .connect_timeout(Duration::from_secs(20))
        .timeout(Duration::from_secs(90))
        .user_agent("Watchcraft/0.1")
        .build()
        .map_err(|error| format!("Could not prepare the collection download: {error}"))?;
    let (manifest_bytes, resolved_url) = download_remote_file(
        &client,
        requested_url,
        MANIFEST_SCAN_LIMIT as usize,
        "collection manifest",
    )?;
    let manifest = parse_manifest(&manifest_bytes, resolved_url.as_str())?;
    let media = media_inventory(&manifest)?;

    let safe_id = safe_component(&manifest.collection_id)?;
    let revision_root = app_data_root
        .join("collections")
        .join(safe_id)
        .join("revisions")
        .join(manifest.revision.to_string());
    let private_manifest_path = revision_root.join("manifest.json");
    if !installed_revision_is_complete(&revision_root, &manifest, &media) {
        install_remote_metadata_revision(
            &client,
            &resolved_url,
            &manifest_bytes,
            &manifest,
            &revision_root,
        )?;
    }

    let mut registry = read_registry(app_data_root)?;
    let relative_revision = revision_root
        .strip_prefix(app_data_root)
        .map_err(|_| "Private collection storage is outside the Watchcraft data folder.")?
        .to_path_buf();
    let relative_manifest = private_manifest_path
        .strip_prefix(app_data_root)
        .map_err(|_| "Private manifest storage is outside the Watchcraft data folder.")?
        .to_path_buf();
    let collection_id = manifest.collection_id.clone();
    let managed_media_root = revision_root.join("managed-media");
    let managed_found = media
        .managed_local
        .iter()
        .filter(|relative| managed_media_root.join(relative).is_file())
        .count();
    let media_expected = media.managed_local.len() + media.referenced_local.len();
    let installed = InstalledCollection {
        collection_id: collection_id.clone(),
        title: manifest.title,
        revision: manifest.revision,
        manifest_path: relative_manifest,
        metadata_root: relative_revision,
        source: CollectionSource::RemoteManifest {
            url: resolved_url.to_string(),
        },
        media_binding: None,
        media_expected,
        media_found: managed_found,
        media_extra: 0,
        enabled: true,
    };
    if activate || registry.current_collection_id.is_none() {
        registry.current_collection_id = Some(collection_id.clone());
    }
    registry
        .collections
        .insert(collection_id.clone(), installed);
    write_registry(app_data_root, &registry)?;
    location_for_id(app_data_root, &registry, &collection_id)
        .ok_or_else(|| "The installed collection could not be reopened.".into())
}

pub(crate) fn load_current(app_data_root: &Path) -> Result<Option<LibraryLocation>, String> {
    let registry = read_registry(app_data_root)?;
    Ok(current_location(app_data_root, &registry))
}

pub(crate) fn list_collections(app_data_root: &Path) -> Result<Vec<RegisteredCollection>, String> {
    let registry = read_registry(app_data_root)?;
    let current = registry.current_collection_id.as_deref();
    let mut collections = registry
        .collections
        .values()
        .map(|installed| {
            let (source_type, source_label) = match &installed.source {
                CollectionSource::LocalManifest { selected_root, .. } => (
                    "folder".to_string(),
                    selected_root.to_string_lossy().into_owned(),
                ),
                CollectionSource::RemoteManifest { url } => ("url".to_string(), url.clone()),
            };
            let manifest_path = app_data_root.join(&installed.manifest_path);
            let media_modes = read_manifest(&manifest_path)
                .and_then(|manifest| media_inventory(&manifest))
                .map(|media| media.mode_names())
                .unwrap_or_default();
            RegisteredCollection {
                collection_id: installed.collection_id.clone(),
                title: installed.title.clone(),
                revision: installed.revision,
                source_type,
                source_label,
                active: current == Some(installed.collection_id.as_str()),
                archived: !installed.enabled,
                media_expected: installed.media_expected,
                media_found: installed.media_found,
                media_extra: installed.media_extra,
                media_modes,
            }
        })
        .collect::<Vec<_>>();
    collections.sort_by(|left, right| {
        right
            .active
            .cmp(&left.active)
            .then_with(|| left.archived.cmp(&right.archived))
            .then_with(|| left.title.to_lowercase().cmp(&right.title.to_lowercase()))
    });
    Ok(collections)
}

pub(crate) fn set_collection_archived(
    app_data_root: &Path,
    collection_id: &str,
    archived: bool,
) -> Result<LibraryLocation, String> {
    let mut registry = read_registry(app_data_root)?;
    let installed = registry
        .collections
        .get(collection_id)
        .ok_or("That collection is not registered with Watchcraft.")?;
    if installed.enabled == !archived {
        return current_location(app_data_root, &registry)
            .ok_or_else(|| "The open collection is unavailable.".into());
    }
    if archived {
        if registry.current_collection_id.as_deref() == Some(collection_id) {
            return Err("Open another collection before archiving this one.".into());
        }
        if registry
            .collections
            .values()
            .filter(|collection| collection.enabled)
            .count()
            <= 1
        {
            return Err("The final available collection cannot be archived.".into());
        }
    }
    registry
        .collections
        .get_mut(collection_id)
        .expect("registered collection checked above")
        .enabled = !archived;
    write_registry(app_data_root, &registry)?;
    current_location(app_data_root, &registry)
        .ok_or_else(|| "The open collection is unavailable.".into())
}

pub(crate) fn activate_collection(
    app_data_root: &Path,
    collection_id: &str,
) -> Result<LibraryLocation, String> {
    let mut registry = read_registry(app_data_root)?;
    if !registry
        .collections
        .get(collection_id)
        .is_some_and(|installed| installed.enabled)
    {
        return Err("That collection is not registered with Watchcraft.".into());
    }
    registry.current_collection_id = Some(collection_id.to_string());
    write_registry(app_data_root, &registry)?;
    location_for_id(app_data_root, &registry, collection_id)
        .ok_or_else(|| "The selected collection's private metadata is unavailable.".into())
}

pub(crate) fn remove_collection(
    app_data_root: &Path,
    collection_id: &str,
) -> Result<LibraryLocation, String> {
    let mut registry = read_registry(app_data_root)?;
    if !registry.collections.contains_key(collection_id) {
        return Err("That collection is not registered with Watchcraft.".into());
    }
    if registry.collections.len() <= 1 {
        return Err("The final collection cannot be removed. Add another collection first.".into());
    }
    if registry.current_collection_id.as_deref() == Some(collection_id) {
        registry.current_collection_id = registry
            .collections
            .values()
            .find(|collection| collection.collection_id != collection_id && collection.enabled)
            .map(|collection| collection.collection_id.clone());
        if registry.current_collection_id.is_none() {
            return Err("The final available collection cannot be removed.".into());
        }
    }
    registry.collections.remove(collection_id);
    write_registry(app_data_root, &registry)?;

    if let Ok(safe_id) = safe_component(collection_id) {
        let private_root = app_data_root.join("collections").join(safe_id);
        if private_root.is_dir() {
            let _ = fs::remove_dir_all(private_root);
        }
    }
    current_location(app_data_root, &registry)
        .ok_or_else(|| "The remaining collection could not be opened.".into())
}

fn current_location(app_data_root: &Path, registry: &LibraryRegistry) -> Option<LibraryLocation> {
    let id = registry.current_collection_id.as_ref()?;
    location_for_id(app_data_root, registry, id)
}

fn location_for_id(
    app_data_root: &Path,
    registry: &LibraryRegistry,
    id: &str,
) -> Option<LibraryLocation> {
    let installed = registry.collections.get(id)?;
    if !installed.enabled {
        return None;
    }
    let manifest_path = app_data_root.join(&installed.manifest_path);
    let metadata_root = app_data_root.join(&installed.metadata_root);
    if !manifest_path.is_file() || !metadata_root.is_dir() {
        return None;
    }
    let managed_media_root = {
        let path = metadata_root.join("managed-media");
        path.is_dir().then_some(path)
    };
    Some(LibraryLocation {
        selected_root: match &installed.source {
            CollectionSource::LocalManifest { selected_root, .. } => Some(selected_root.clone()),
            CollectionSource::RemoteManifest { .. } => None,
        },
        collection_id: installed.collection_id.clone(),
        manifest_path,
        metadata_root,
        media_root: installed
            .media_binding
            .as_ref()
            .map(|binding| binding.path.clone())
            .filter(|path| path.is_dir()),
        managed_media_root,
        media_expected: installed.media_expected,
        media_found: installed.media_found,
        media_extra: installed.media_extra,
    })
}

fn discover_manifest(selected_root: &Path) -> Result<PathBuf, String> {
    let mut files = candidate_files(selected_root)?;
    for child in sorted_children(selected_root)? {
        if child.is_dir() {
            files.extend(candidate_files(&child)?);
        }
    }
    files.sort();
    files.dedup();
    let mut manifests = files
        .into_iter()
        .filter(|path| read_manifest(path).is_ok())
        .collect::<Vec<_>>();
    match manifests.len() {
        0 => Err("No Watchcraft collection manifest was found in the selected folder or an immediate child folder.".into()),
        1 => Ok(manifests.remove(0)),
        count => Err(format!(
            "The selected folder contains {count} Watchcraft collections. Choose the specific collection folder you want to install."
        )),
    }
}

fn candidate_files(folder: &Path) -> Result<Vec<PathBuf>, String> {
    Ok(sorted_children(folder)?
        .into_iter()
        .filter(|path| path.is_file() && is_manifest_candidate(path))
        .collect())
}

fn sorted_children(folder: &Path) -> Result<Vec<PathBuf>, String> {
    let mut paths = fs::read_dir(folder)
        .map_err(|error| format!("Could not inspect {}: {error}", folder.display()))?
        .filter_map(Result::ok)
        .map(|entry| entry.path())
        .collect::<Vec<_>>();
    paths.sort();
    Ok(paths)
}

fn is_manifest_candidate(path: &Path) -> bool {
    let within_limit = path
        .metadata()
        .map(|metadata| metadata.len() <= MANIFEST_SCAN_LIMIT)
        .unwrap_or(false);
    let supported_extension = path
        .extension()
        .and_then(|extension| extension.to_str())
        .map(|extension| {
            matches!(
                extension.to_ascii_lowercase().as_str(),
                "json" | "watchcraft" | "manifest"
            )
        })
        .unwrap_or(true);
    within_limit && supported_extension
}

fn read_manifest(path: &Path) -> Result<CollectionManifest, String> {
    let bytes =
        fs::read(path).map_err(|error| format!("Could not open {}: {error}", path.display()))?;
    parse_manifest(&bytes, &path.display().to_string())
}

fn parse_manifest(bytes: &[u8], source: &str) -> Result<CollectionManifest, String> {
    let manifest: CollectionManifest = serde_json::from_slice(bytes)
        .map_err(|error| format!("Could not read {source}: {error}"))?;
    if manifest.kind != COLLECTION_KIND {
        return Err(format!("{source} is not a Watchcraft collection."));
    }
    if manifest.schema_version != COLLECTION_SCHEMA_VERSION {
        return Err(format!(
            "{source} uses schema version {}; Watchcraft requires version {COLLECTION_SCHEMA_VERSION}.",
            manifest.schema_version
        ));
    }
    if manifest.collection_id.trim().is_empty() {
        return Err("The collection_id cannot be empty.".into());
    }
    if manifest.title.trim().is_empty() || manifest.topic_scope != "collection" {
        return Err("The collection title and collection topic scope are required.".into());
    }
    if !manifest.root.is_object()
        || !manifest.topics.is_object()
        || !manifest.topic_families.is_object()
        || !manifest.stats.is_object()
    {
        return Err(
            "The collection hierarchy, topic registries, and stats must be objects.".into(),
        );
    }
    if manifest.revision == 0
        || manifest.content_hash.len() != 64
        || !manifest
            .content_hash
            .chars()
            .all(|character| character.is_ascii_hexdigit())
    {
        return Err("The collection revision or content_hash is invalid.".into());
    }
    Ok(manifest)
}

fn parse_remote_url(value: &str) -> Result<Url, String> {
    let url = Url::parse(value.trim())
        .map_err(|error| format!("The collection URL is invalid: {error}"))?;
    if !matches!(url.scheme(), "https" | "http") {
        return Err("A collection URL must use HTTP or HTTPS.".into());
    }
    if url.host_str().is_none() {
        return Err("The collection URL must include a host.".into());
    }
    Ok(url)
}

fn download_remote_file(
    client: &reqwest::blocking::Client,
    url: Url,
    limit: usize,
    label: &str,
) -> Result<(Vec<u8>, Url), String> {
    let response = client
        .get(url.clone())
        .send()
        .map_err(|error| format!("Could not download {label} from {url}: {error}"))?
        .error_for_status()
        .map_err(|error| format!("Could not download {label} from {url}: {error}"))?;
    if response
        .content_length()
        .is_some_and(|length| length > limit as u64)
    {
        return Err(format!(
            "The downloaded {label} is larger than Watchcraft permits."
        ));
    }
    let resolved_url = response.url().clone();
    let mut bytes = Vec::new();
    response
        .take((limit + 1) as u64)
        .read_to_end(&mut bytes)
        .map_err(|error| format!("Could not read the downloaded {label}: {error}"))?;
    if bytes.len() > limit {
        return Err(format!(
            "The downloaded {label} is larger than Watchcraft permits."
        ));
    }
    Ok((bytes, resolved_url))
}

impl MediaInventory {
    fn mode_names(&self) -> Vec<String> {
        let mut modes = Vec::new();
        if !self.managed_local.is_empty() {
            modes.push("managed-local".into());
        }
        if !self.referenced_local.is_empty() {
            modes.push("referenced-local".into());
        }
        if self.remote_count > 0 {
            modes.push("remote".into());
        }
        modes
    }
}

fn media_inventory(manifest: &CollectionManifest) -> Result<MediaInventory, String> {
    let mut managed_local = BTreeSet::new();
    let mut referenced_local = BTreeSet::new();
    let mut remote_count = 0;
    for (item_id, item) in &manifest.items {
        if item.item_id != *item_id || item.title.trim().is_empty() || item.media.is_empty() {
            return Err(
                "Each collection item requires a matching item_id, a title, and media.".into(),
            );
        }
        for media in &item.media {
            match media {
                MediaReference::LocalFile {
                    delivery,
                    relative_path,
                } => {
                    validate_relative_path(relative_path, "local media")?;
                    match delivery.unwrap_or(MediaDelivery::ReferencedLocal) {
                        MediaDelivery::ManagedLocal => {
                            managed_local.insert(relative_path.clone());
                        }
                        MediaDelivery::ReferencedLocal => {
                            referenced_local.insert(relative_path.clone());
                        }
                        MediaDelivery::Remote => {
                            return Err(
                                "A local-file media reference cannot use remote delivery.".into()
                            );
                        }
                    }
                }
                MediaReference::YouTube {
                    delivery,
                    video_id,
                    url,
                } => {
                    if video_id.trim().is_empty()
                        || delivery.is_some_and(|value| value != MediaDelivery::Remote)
                        || url
                            .as_ref()
                            .is_some_and(|value| !value.starts_with("https://"))
                    {
                        return Err("A YouTube media reference is invalid.".into());
                    }
                    remote_count += 1;
                }
                MediaReference::HttpVideo { delivery, url } => {
                    if delivery.is_some_and(|value| value != MediaDelivery::Remote)
                        || (!url.starts_with("https://") && !url.starts_with("http://"))
                    {
                        return Err("An HTTP video reference must use an HTTP(S) URL.".into());
                    }
                    remote_count += 1;
                }
            }
        }
    }
    Ok(MediaInventory {
        managed_local: managed_local.into_iter().collect(),
        referenced_local: referenced_local.into_iter().collect(),
        remote_count,
    })
}

fn installed_revision_is_complete(
    revision_root: &Path,
    manifest: &CollectionManifest,
    media: &MediaInventory,
) -> bool {
    revision_root.join("manifest.json").is_file()
        && referenced_metadata_paths(manifest)
            .iter()
            .all(|relative| revision_root.join(relative).is_file())
        && media
            .managed_local
            .iter()
            .all(|relative| revision_root.join("managed-media").join(relative).is_file())
}

fn resolve_media_root(
    selected_root: &Path,
    metadata_root: &Path,
    hint: Option<&Path>,
    local_paths: &[PathBuf],
) -> Result<Option<PathBuf>, String> {
    if local_paths.is_empty() {
        return Ok(None);
    }
    let candidate = if let Some(hint) = hint {
        validate_media_root_hint(hint)?;
        metadata_root.join(hint)
    } else {
        selected_root.to_path_buf()
    };
    let candidate = candidate
        .canonicalize()
        .map_err(|error| format!("Could not resolve the suggested local media folder: {error}"))?;
    if !candidate.is_dir() {
        return Err("The suggested local media location is not a folder.".into());
    }
    let within_selection = candidate.starts_with(selected_root);
    let selected_is_manifest_folder = selected_root == metadata_root;
    let is_direct_parent = selected_is_manifest_folder
        && metadata_root
            .parent()
            .map(|parent| parent == candidate)
            .unwrap_or(false);
    if !within_selection && !is_direct_parent {
        return Err("media_root_hint points outside the selected library boundary.".into());
    }
    Ok(Some(candidate))
}

fn validate_media_root_hint(path: &Path) -> Result<(), String> {
    if path.as_os_str().is_empty() || path.is_absolute() {
        return Err("The media_root_hint must be a non-empty relative path.".into());
    }
    if path
        .components()
        .any(|component| matches!(component, Component::RootDir | Component::Prefix(_)))
    {
        return Err("The media_root_hint must be relative to the collection folder.".into());
    }
    Ok(())
}

fn media_stats(media_root: Option<&Path>, local_paths: &[PathBuf]) -> (usize, usize, usize) {
    let expected = local_paths.len();
    let Some(media_root) = media_root else {
        return (expected, 0, 0);
    };
    let found = local_paths
        .iter()
        .filter(|relative| media_root.join(relative).is_file())
        .count();
    let total_video_files = count_video_files(media_root);
    (expected, found, total_video_files.saturating_sub(found))
}

fn count_video_files(folder: &Path) -> usize {
    let Ok(entries) = fs::read_dir(folder) else {
        return 0;
    };
    entries
        .filter_map(Result::ok)
        .map(|entry| entry.path())
        .map(|path| {
            if path.is_dir() && !path.is_symlink() {
                count_video_files(&path)
            } else if is_video_path(&path) {
                1
            } else {
                0
            }
        })
        .sum()
}

fn is_video_path(path: &Path) -> bool {
    path.extension()
        .and_then(|extension| extension.to_str())
        .map(|extension| VIDEO_EXTENSIONS.contains(&extension.to_ascii_lowercase().as_str()))
        .unwrap_or(false)
}

fn install_metadata_revision(
    source_root: &Path,
    source_manifest: &Path,
    manifest: &CollectionManifest,
    target_root: &Path,
) -> Result<(), String> {
    let parent = target_root
        .parent()
        .ok_or("Private revision storage has no parent folder.")?;
    fs::create_dir_all(parent)
        .map_err(|error| format!("Could not create private collection storage: {error}"))?;
    let staging = parent.join(format!(".{}-{}.tmp", manifest.revision, std::process::id()));
    if staging.exists() {
        fs::remove_dir_all(&staging)
            .map_err(|error| format!("Could not clear private install staging: {error}"))?;
    }
    fs::create_dir_all(&staging)
        .map_err(|error| format!("Could not create private install staging: {error}"))?;
    copy_file(source_manifest, &staging.join("manifest.json"))?;

    for relative in referenced_metadata_paths(manifest) {
        validate_relative_path(&relative, "metadata")?;
        let source = source_root.join(&relative);
        let canonical_source = source.canonicalize().map_err(|error| {
            format!(
                "Could not resolve referenced metadata {}: {error}",
                source.display()
            )
        })?;
        if !canonical_source.starts_with(source_root) || !canonical_source.is_file() {
            return Err(format!(
                "Referenced metadata is outside the collection folder: {}",
                relative.display()
            ));
        }
        copy_file(&canonical_source, &staging.join(&relative))?;
    }

    for relative in media_inventory(manifest)?.managed_local {
        let source = source_root.join(&relative);
        let canonical_source = source.canonicalize().map_err(|error| {
            format!(
                "Could not resolve managed media {}: {error}",
                source.display()
            )
        })?;
        if !canonical_source.starts_with(source_root) || !canonical_source.is_file() {
            return Err(format!(
                "Managed media is outside the collection folder: {}",
                relative.display()
            ));
        }
        copy_file(
            &canonical_source,
            &staging.join("managed-media").join(&relative),
        )?;
    }

    finalize_staged_revision(&staging, target_root)
}

fn install_remote_metadata_revision(
    client: &reqwest::blocking::Client,
    manifest_url: &Url,
    manifest_bytes: &[u8],
    manifest: &CollectionManifest,
    target_root: &Path,
) -> Result<(), String> {
    let parent = target_root
        .parent()
        .ok_or("Private revision storage has no parent folder.")?;
    fs::create_dir_all(parent)
        .map_err(|error| format!("Could not create private collection storage: {error}"))?;
    let staging = parent.join(format!(".{}-{}.tmp", manifest.revision, std::process::id()));
    if staging.exists() {
        fs::remove_dir_all(&staging)
            .map_err(|error| format!("Could not clear private install staging: {error}"))?;
    }
    fs::create_dir_all(&staging)
        .map_err(|error| format!("Could not create private install staging: {error}"))?;
    fs::write(staging.join("manifest.json"), manifest_bytes)
        .map_err(|error| format!("Could not store the downloaded collection manifest: {error}"))?;

    let mut downloaded = manifest_bytes.len();
    for relative in referenced_metadata_paths(manifest) {
        validate_relative_path(&relative, "metadata")?;
        let relative_url = relative
            .to_str()
            .ok_or("A remote metadata path contains unsupported characters.")?
            .replace('\\', "/");
        let url = manifest_url.join(&relative_url).map_err(|error| {
            format!("Could not resolve remote metadata {relative_url}: {error}")
        })?;
        let (bytes, _) =
            download_remote_file(client, url, REMOTE_FILE_LIMIT, "collection metadata")?;
        downloaded = downloaded.saturating_add(bytes.len());
        if downloaded > REMOTE_TOTAL_LIMIT {
            let _ = fs::remove_dir_all(&staging);
            return Err(
                "The collection metadata download is larger than Watchcraft permits.".into(),
            );
        }
        let target = staging.join(&relative);
        if let Some(parent) = target.parent() {
            fs::create_dir_all(parent)
                .map_err(|error| format!("Could not create private metadata folder: {error}"))?;
        }
        fs::write(&target, bytes).map_err(|error| {
            format!("Could not store downloaded metadata {relative_url}: {error}")
        })?;
    }

    for relative in media_inventory(manifest)?.managed_local {
        let relative_url = relative
            .to_str()
            .ok_or("A managed media path contains unsupported characters.")?
            .replace('\\', "/");
        let url = manifest_url
            .join(&relative_url)
            .map_err(|error| format!("Could not resolve managed media {relative_url}: {error}"))?;
        let (bytes, _) = download_remote_file(client, url, REMOTE_FILE_LIMIT, "managed media")?;
        downloaded = downloaded.saturating_add(bytes.len());
        if downloaded > REMOTE_TOTAL_LIMIT {
            let _ = fs::remove_dir_all(&staging);
            return Err("The collection download is larger than Watchcraft permits.".into());
        }
        let target = staging.join("managed-media").join(&relative);
        if let Some(parent) = target.parent() {
            fs::create_dir_all(parent)
                .map_err(|error| format!("Could not create managed media folder: {error}"))?;
        }
        fs::write(&target, bytes).map_err(|error| {
            format!("Could not store downloaded managed media {relative_url}: {error}")
        })?;
    }

    finalize_staged_revision(&staging, target_root)
}

fn finalize_staged_revision(staging: &Path, target_root: &Path) -> Result<(), String> {
    if !target_root.exists() {
        return fs::rename(staging, target_root)
            .map_err(|error| format!("Could not finalize private collection metadata: {error}"));
    }

    let parent = target_root
        .parent()
        .ok_or("Private revision storage has no parent folder.")?;
    let revision_name = target_root
        .file_name()
        .and_then(|name| name.to_str())
        .ok_or("Private revision storage has an invalid name.")?;
    let backup = parent.join(format!(".{revision_name}-{}-backup", std::process::id()));
    if backup.exists() {
        fs::remove_dir_all(&backup)
            .map_err(|error| format!("Could not clear private install backup: {error}"))?;
    }
    fs::rename(target_root, &backup)
        .map_err(|error| format!("Could not prepare the collection repair: {error}"))?;
    if let Err(error) = fs::rename(staging, target_root) {
        let _ = fs::rename(&backup, target_root);
        let _ = fs::remove_dir_all(staging);
        return Err(format!(
            "Could not finalize repaired collection metadata: {error}"
        ));
    }
    fs::remove_dir_all(&backup)
        .map_err(|error| format!("Could not clear the replaced collection revision: {error}"))?;
    Ok(())
}

fn referenced_metadata_paths(manifest: &CollectionManifest) -> BTreeSet<PathBuf> {
    let mut paths = BTreeSet::new();
    for item in manifest.items.values() {
        paths.insert(item.analysis.path.clone());
        paths.extend(item.transcript.subtitles.iter().cloned());
        paths.extend(item.transcript.text.iter().cloned());
        paths.extend(item.transcript.segments.iter().cloned());
    }
    paths
}

fn copy_file(source: &Path, target: &Path) -> Result<(), String> {
    if let Some(parent) = target.parent() {
        fs::create_dir_all(parent)
            .map_err(|error| format!("Could not create private metadata folder: {error}"))?;
    }
    fs::copy(source, target).map_err(|error| {
        format!(
            "Could not copy {} into private collection storage: {error}",
            source.display()
        )
    })?;
    Ok(())
}

fn validate_relative_path(path: &Path, label: &str) -> Result<(), String> {
    if path.as_os_str().is_empty() || path.is_absolute() {
        return Err(format!(
            "The {label} path must be a non-empty relative path."
        ));
    }
    if path.components().any(|component| {
        matches!(
            component,
            Component::ParentDir | Component::RootDir | Component::Prefix(_)
        )
    }) {
        return Err(format!(
            "The {label} path cannot leave its collection folder."
        ));
    }
    Ok(())
}

fn safe_component(value: &str) -> Result<String, String> {
    let value = value.trim();
    if value.is_empty() {
        return Err("The collection_id cannot be empty.".into());
    }
    let readable: String = value
        .chars()
        .map(|character| {
            if character.is_ascii_alphanumeric() || matches!(character, '-' | '_' | '.') {
                character
            } else {
                '_'
            }
        })
        .collect();
    let hash = value
        .as_bytes()
        .iter()
        .fold(0xcbf29ce484222325_u64, |hash, byte| {
            (hash ^ u64::from(*byte)).wrapping_mul(0x100000001b3)
        });
    Ok(format!("{readable}-{hash:016x}"))
}

fn registry_path(app_data_root: &Path) -> PathBuf {
    app_data_root.join("library.json")
}

fn read_registry(app_data_root: &Path) -> Result<LibraryRegistry, String> {
    let path = registry_path(app_data_root);
    if !path.is_file() {
        return Ok(LibraryRegistry::default());
    }
    let registry: LibraryRegistry = serde_json::from_reader(
        fs::File::open(&path)
            .map_err(|error| format!("Could not open the private library registry: {error}"))?,
    )
    .map_err(|error| format!("Could not read the private library registry: {error}"))?;
    if registry.schema_version != LIBRARY_SCHEMA_VERSION {
        return Err(format!(
            "The private library registry uses unsupported schema version {}.",
            registry.schema_version
        ));
    }
    Ok(registry)
}

fn write_registry(app_data_root: &Path, registry: &LibraryRegistry) -> Result<(), String> {
    fs::create_dir_all(app_data_root)
        .map_err(|error| format!("Could not create the Watchcraft data folder: {error}"))?;
    let destination = registry_path(app_data_root);
    let temporary = app_data_root.join("library.json.tmp");
    let bytes = serde_json::to_vec_pretty(registry)
        .map_err(|error| format!("Could not serialize the private library registry: {error}"))?;
    fs::write(&temporary, bytes)
        .map_err(|error| format!("Could not stage the private library registry: {error}"))?;
    replace_file(&temporary, &destination)
}

#[cfg(not(target_os = "windows"))]
fn replace_file(source: &Path, destination: &Path) -> Result<(), String> {
    fs::rename(source, destination)
        .map_err(|error| format!("Could not save the private library registry: {error}"))
}

#[cfg(target_os = "windows")]
fn replace_file(source: &Path, destination: &Path) -> Result<(), String> {
    let backup = destination.with_extension("json.backup");
    if destination.exists() {
        fs::rename(destination, &backup)
            .map_err(|error| format!("Could not prepare the private library registry: {error}"))?;
    }
    if let Err(error) = fs::rename(source, destination) {
        let _ = fs::rename(&backup, destination);
        return Err(format!(
            "Could not save the private library registry: {error}"
        ));
    }
    if backup.exists() {
        let _ = fs::remove_file(backup);
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::{
        activate_collection, discover_manifest, install_from_folder_with_activation,
        install_from_url, list_collections, load_current, remove_collection,
        set_collection_archived,
    };
    use std::fs;
    use std::io::{Read, Write};
    use std::net::TcpListener;
    use std::path::PathBuf;
    use std::thread;

    #[test]
    fn discovers_an_arbitrarily_named_manifest_from_collection_or_parent() {
        let root = temporary_root("discovery");
        let collection = root.join("Course Metadata");
        fs::create_dir_all(&collection).unwrap();
        write_fixture(&collection.join("course.watchcraft"), "demo", 1, "..");
        assert_eq!(
            discover_manifest(&root).unwrap(),
            collection.join("course.watchcraft")
        );
        assert_eq!(
            discover_manifest(&collection).unwrap(),
            collection.join("course.watchcraft")
        );
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn asks_for_a_specific_collection_when_a_parent_contains_multiple() {
        let root = temporary_root("multiple");
        for (name, id) in [("Course One", "one"), ("Course Two", "two")] {
            let collection = root.join(name);
            fs::create_dir_all(&collection).unwrap();
            write_fixture(&collection.join("manifest.json"), id, 1, ".");
        }
        let error = discover_manifest(&root).unwrap_err();
        assert!(error.contains("2 Watchcraft collections"));
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn rejects_a_media_hint_beyond_the_selected_boundary() {
        let root = temporary_root("unsafe-hint");
        let collection = root.join("Course Metadata");
        fs::create_dir_all(collection.join("analysis")).unwrap();
        fs::write(collection.join("analysis/lesson.json"), "{}").unwrap();
        write_fixture(&collection.join("manifest.json"), "unsafe", 1, "../..");
        let error = install_from_folder_with_activation(&root.join("private"), &collection, true)
            .unwrap_err();
        assert!(error.contains("outside the selected library boundary"));
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn installs_metadata_and_restores_private_media_binding() {
        let root = temporary_root("install");
        let app_data = root.join("private");
        let collection = root.join("Course Metadata");
        fs::create_dir_all(collection.join("analysis")).unwrap();
        fs::create_dir_all(root.join("media")).unwrap();
        fs::write(collection.join("analysis/lesson.json"), "{}").unwrap();
        fs::write(root.join("media/lesson.mp4"), "video").unwrap();
        write_fixture(&collection.join("anything.json"), "demo", 2, "..");

        let installed = install_from_folder_with_activation(&app_data, &root, true).unwrap();
        assert_eq!(installed.collection_id, "demo");
        assert_eq!(installed.media_expected, 1);
        assert_eq!(installed.media_found, 1);
        assert_eq!(installed.media_extra, 0);
        assert!(installed.manifest_path.starts_with(&app_data));
        assert!(installed
            .metadata_root
            .join("analysis/lesson.json")
            .is_file());
        assert!(app_data.join("library.json").is_file());
        assert_eq!(load_current(&app_data).unwrap(), Some(installed));
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn copies_managed_local_media_into_private_storage() {
        let root = temporary_root("managed-folder");
        let app_data = root.join("private");
        let collection = root.join("Managed Course");
        fs::create_dir_all(collection.join("analysis")).unwrap();
        fs::create_dir_all(collection.join("media")).unwrap();
        fs::write(collection.join("analysis/lesson.json"), "{}").unwrap();
        fs::write(collection.join("media/lesson.mp4"), "managed video").unwrap();
        write_managed_fixture(&collection.join("collection.json"), "managed-folder", 1);

        let installed = install_from_folder_with_activation(&app_data, &collection, true).unwrap();
        let managed_root = installed.managed_media_root.unwrap();
        assert_eq!(
            fs::read_to_string(managed_root.join("media/lesson.mp4")).unwrap(),
            "managed video"
        );
        assert_eq!((installed.media_expected, installed.media_found), (1, 1));
        assert_eq!(installed.media_root, None);
        assert_eq!(
            list_collections(&app_data).unwrap()[0].media_modes,
            ["managed-local"]
        );

        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn allows_partial_local_collections_and_ignores_extra_videos() {
        let root = temporary_root("partial");
        let app_data = root.join("private");
        let collection = root.join("Course Metadata");
        fs::create_dir_all(collection.join("analysis")).unwrap();
        fs::create_dir_all(root.join("media")).unwrap();
        fs::write(collection.join("analysis/lesson.json"), "{}").unwrap();
        fs::write(root.join("media/extra.mp4"), "video").unwrap();
        write_fixture(&collection.join("catalog-data"), "partial", 1, "..");
        let installed = install_from_folder_with_activation(&app_data, &root, true).unwrap();
        assert_eq!(
            (
                installed.media_expected,
                installed.media_found,
                installed.media_extra
            ),
            (1, 0, 1)
        );
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn installs_a_hosted_collection_without_a_local_media_binding() {
        let root = temporary_root("hosted");
        let app_data = root.join("private");
        fs::create_dir_all(root.join("analysis")).unwrap();
        fs::write(root.join("analysis/lesson.json"), "{}").unwrap();
        fs::write(
            root.join("remote.json"),
            r#"{
              "kind":"watchcraft.collection",
              "schema_version":4,
              "collection_id":"hosted/demo",
              "title":"Hosted Demo",
              "revision":1,
              "topic_scope":"collection",
              "root":{"type":"group","group_id":"root","title":"Hosted Demo","children":[]},
              "topics":{},
              "topic_families":{},
              "items":{
                "lesson":{
                  "item_id":"lesson",
                  "title":"Lesson",
                  "media":[{"type":"youtube","video_id":"abc123"}],
                  "transcript":{},
                  "analysis":{"path":"analysis/lesson.json"},
                  "summary":"Lesson",
                  "locations":[],
                  "topic_ids":[],
                  "family_ids":[],
                  "topic_sections":{},
                  "chapter_count":1
                }
              },
              "stats":{"video_count":1,"topic_count":0,"topic_family_count":0},
              "content_hash":"0000000000000000000000000000000000000000000000000000000000000000"
            }"#,
        )
        .unwrap();
        let installed = install_from_folder_with_activation(&app_data, &root, true).unwrap();
        assert_eq!(installed.collection_id, "hosted/demo");
        assert_eq!(installed.media_root, None);
        assert_eq!(installed.media_expected, 0);
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn registers_switches_and_safely_removes_multiple_collections() {
        let root = temporary_root("registry");
        let app_data = root.join("private");
        let first = root.join("First Course");
        let second = root.join("Second Course");
        for (folder, id) in [(&first, "first"), (&second, "second")] {
            fs::create_dir_all(folder.join("analysis")).unwrap();
            fs::create_dir_all(folder.join("media")).unwrap();
            fs::write(folder.join("analysis/lesson.json"), "{}").unwrap();
            fs::write(folder.join("media/lesson.mp4"), "video").unwrap();
            write_fixture(&folder.join("course.watchcraft"), id, 1, ".");
        }

        install_from_folder_with_activation(&app_data, &first, true).unwrap();
        install_from_folder_with_activation(&app_data, &second, false).unwrap();
        let registered = list_collections(&app_data).unwrap();
        assert_eq!(registered.len(), 2);
        assert!(registered
            .iter()
            .any(|collection| collection.collection_id == "first" && collection.active));

        let activated = activate_collection(&app_data, "second").unwrap();
        assert_eq!(activated.collection_id, "second");
        let remaining = remove_collection(&app_data, "second").unwrap();
        assert_eq!(remaining.collection_id, "first");
        assert_eq!(list_collections(&app_data).unwrap().len(), 1);
        assert!(second.join("course.watchcraft").is_file());
        assert!(remove_collection(&app_data, "first")
            .unwrap_err()
            .contains("final collection"));
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn archives_and_restores_non_active_collections() {
        let root = temporary_root("archive-registry");
        let app_data = root.join("private");
        let first = root.join("First Course");
        let second = root.join("Second Course");
        for (folder, id) in [(&first, "first"), (&second, "second")] {
            fs::create_dir_all(folder.join("analysis")).unwrap();
            fs::create_dir_all(folder.join("media")).unwrap();
            fs::write(folder.join("analysis/lesson.json"), "{}").unwrap();
            fs::write(folder.join("media/lesson.mp4"), "video").unwrap();
            write_fixture(&folder.join("course.watchcraft"), id, 1, ".");
        }

        install_from_folder_with_activation(&app_data, &first, true).unwrap();
        install_from_folder_with_activation(&app_data, &second, false).unwrap();

        set_collection_archived(&app_data, "second", true).unwrap();
        let registered = list_collections(&app_data).unwrap();
        assert_eq!(registered.len(), 2);
        assert!(registered
            .iter()
            .any(|collection| collection.collection_id == "second" && collection.archived));
        assert!(activate_collection(&app_data, "second")
            .unwrap_err()
            .contains("not registered"));
        assert!(set_collection_archived(&app_data, "first", true)
            .unwrap_err()
            .contains("Open another collection"));

        set_collection_archived(&app_data, "second", false).unwrap();
        activate_collection(&app_data, "second").unwrap();
        set_collection_archived(&app_data, "first", true).unwrap();
        assert!(remove_collection(&app_data, "second")
            .unwrap_err()
            .contains("final available"));

        set_collection_archived(&app_data, "first", false).unwrap();
        let remaining = remove_collection(&app_data, "second").unwrap();
        assert_eq!(remaining.collection_id, "first");
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn installs_a_remote_manifest_and_its_referenced_metadata() {
        let manifest = r#"{
          "kind":"watchcraft.collection",
          "schema_version":4,
          "collection_id":"remote-demo",
          "title":"Remote Demo",
          "revision":1,
          "topic_scope":"collection",
          "root":{"type":"group","group_id":"root","title":"Remote Demo","children":[]},
          "topics":{},
          "topic_families":{},
          "items":{"lesson":{"item_id":"lesson","title":"Lesson","media":[{"type":"youtube","video_id":"abc123"}],"transcript":{},"analysis":{"path":"analysis/lesson.json"},"summary":"Lesson","locations":[],"topic_ids":[],"family_ids":[],"topic_sections":{},"chapter_count":1}},
          "stats":{"video_count":1,"topic_count":0,"topic_family_count":0},
          "content_hash":"0000000000000000000000000000000000000000000000000000000000000000"
        }"#;
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let server = thread::spawn(move || {
            for _ in 0..2 {
                let (mut stream, _) = listener.accept().unwrap();
                let mut request = [0_u8; 2048];
                let length = stream.read(&mut request).unwrap();
                let request = String::from_utf8_lossy(&request[..length]);
                let body = if request.starts_with("GET /course.watchcraft ") {
                    manifest
                } else {
                    "{}"
                };
                write!(
                    stream,
                    "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
                    body.len(),
                    body
                )
                .unwrap();
            }
        });

        let root = temporary_root("remote");
        let installed =
            install_from_url(&root, &format!("http://{address}/course.watchcraft"), true).unwrap();
        assert_eq!(installed.collection_id, "remote-demo");
        assert_eq!(installed.selected_root, None);
        assert!(installed
            .metadata_root
            .join("analysis/lesson.json")
            .is_file());
        assert_eq!(list_collections(&root).unwrap()[0].source_type, "url");
        server.join().unwrap();
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn downloads_managed_local_media_from_a_remote_collection() {
        let manifest = r#"{
          "kind":"watchcraft.collection",
          "schema_version":4,
          "collection_id":"remote-managed",
          "title":"Remote Managed",
          "revision":1,
          "topic_scope":"collection",
          "root":{"type":"group","group_id":"root","title":"Remote Managed","children":[]},
          "topics":{},
          "topic_families":{},
          "items":{"lesson":{"item_id":"lesson","title":"Lesson","media":[{"type":"local-file","delivery":"managed-local","relative_path":"media/lesson.mp4"}],"transcript":{},"analysis":{"path":"analysis/lesson.json"},"summary":"Lesson","locations":[],"topic_ids":[],"family_ids":[],"topic_sections":{},"chapter_count":1}},
          "stats":{"video_count":1,"topic_count":0,"topic_family_count":0},
          "content_hash":"0000000000000000000000000000000000000000000000000000000000000000"
        }"#;
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let server = thread::spawn(move || {
            for _ in 0..6 {
                let (mut stream, _) = listener.accept().unwrap();
                let mut request = [0_u8; 2048];
                let length = stream.read(&mut request).unwrap();
                let request = String::from_utf8_lossy(&request[..length]);
                let (content_type, body): (&str, &[u8]) =
                    if request.starts_with("GET /collection.json ") {
                        ("application/json", manifest.as_bytes())
                    } else if request.starts_with("GET /media/lesson.mp4 ") {
                        ("video/mp4", b"downloaded video")
                    } else {
                        ("application/json", b"{}")
                    };
                write!(
                    stream,
                    "HTTP/1.1 200 OK\r\nContent-Type: {content_type}\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
                    body.len()
                )
                .unwrap();
                stream.write_all(body).unwrap();
            }
        });

        let root = temporary_root("remote-managed");
        let installed =
            install_from_url(&root, &format!("http://{address}/collection.json"), true).unwrap();
        let managed_root = installed.managed_media_root.unwrap();
        assert_eq!(
            fs::read(managed_root.join("media/lesson.mp4")).unwrap(),
            b"downloaded video"
        );
        assert_eq!((installed.media_expected, installed.media_found), (1, 1));
        assert_eq!(installed.media_root, None);

        fs::remove_file(managed_root.join("media/lesson.mp4")).unwrap();
        let repaired =
            install_from_url(&root, &format!("http://{address}/collection.json"), true).unwrap();
        let repaired_root = repaired.managed_media_root.unwrap();
        assert_eq!(
            fs::read(repaired_root.join("media/lesson.mp4")).unwrap(),
            b"downloaded video"
        );
        assert_eq!((repaired.media_expected, repaired.media_found), (1, 1));
        server.join().unwrap();
        fs::remove_dir_all(root).unwrap();
    }

    fn write_fixture(path: &std::path::Path, id: &str, revision: u64, hint: &str) {
        let json = format!(
            r#"{{
              "kind":"watchcraft.collection",
              "schema_version":4,
              "collection_id":"{id}",
              "title":"Demo",
              "revision":{revision},
              "media_root_hint":"{hint}",
              "topic_scope":"collection",
              "root":{{"type":"group","group_id":"root","title":"Demo","children":[]}},
              "topics":{{}},
              "topic_families":{{}},
              "items":{{
                "lesson":{{
                  "item_id":"lesson",
                  "title":"Lesson",
                  "media":[{{"type":"local-file","relative_path":"media/lesson.mp4"}}],
                  "transcript":{{}},
                  "analysis":{{"path":"analysis/lesson.json"}},
                  "summary":"Lesson",
                  "locations":[],
                  "topic_ids":[],
                  "family_ids":[],
                  "topic_sections":{{}},
                  "chapter_count":1
                }}
              }},
              "stats":{{"video_count":1,"topic_count":0,"topic_family_count":0}},
              "content_hash":"0000000000000000000000000000000000000000000000000000000000000000"
            }}"#
        );
        fs::write(path, json).unwrap();
    }

    fn write_managed_fixture(path: &std::path::Path, id: &str, revision: u64) {
        let json = format!(
            r#"{{
              "kind":"watchcraft.collection",
              "schema_version":4,
              "collection_id":"{id}",
              "title":"Managed Demo",
              "revision":{revision},
              "topic_scope":"collection",
              "root":{{"type":"group","group_id":"root","title":"Managed Demo","children":[]}},
              "topics":{{}},
              "topic_families":{{}},
              "items":{{"lesson":{{"item_id":"lesson","title":"Lesson","media":[{{"type":"local-file","delivery":"managed-local","relative_path":"media/lesson.mp4"}}],"transcript":{{}},"analysis":{{"path":"analysis/lesson.json"}},"summary":"Lesson","locations":[],"topic_ids":[],"family_ids":[],"topic_sections":{{}},"chapter_count":1}}}},
              "stats":{{"video_count":1,"topic_count":0,"topic_family_count":0}},
              "content_hash":"0000000000000000000000000000000000000000000000000000000000000000"
            }}"#
        );
        fs::write(path, json).unwrap();
    }

    fn temporary_root(suffix: &str) -> PathBuf {
        let root = std::env::temp_dir().join(format!(
            "watchcraft-library-test-{}-{suffix}",
            std::process::id()
        ));
        let _ = fs::remove_dir_all(&root);
        fs::create_dir_all(&root).unwrap();
        root
    }
}
