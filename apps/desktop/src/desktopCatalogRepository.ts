import { convertFileSrc, invoke } from "@tauri-apps/api/core";
import {
  DEFAULT_YOUTUBE_BRIDGE_URL,
  youtubeBridgeUrl,
  youtubeWatchUrl,
} from "@watchcraft/catalog-core";
import type {
  CatalogItem,
  CatalogRepository,
  CollectionManifest,
  VideoAnalysis,
} from "@watchcraft/catalog-core";

function separatorFor(path: string): "/" | "\\" {
  return path.includes("\\") ? "\\" : "/";
}

export function joinLocalPath(root: string, relativePath: string): string {
  const separator = separatorFor(root);
  const cleanRoot = root.replace(/[\\/]+$/, "");
  const cleanRelative = relativePath
    .replace(/^[\\/]+/, "")
    .replace(/[\\/]+/g, separator);
  return `${cleanRoot}${separator}${cleanRelative}`;
}

function portableComponents(path: string): string[] {
  return path.split(/[\\/]+/).filter(Boolean);
}

export function boundMediaRelativePath(relativePath: string, pathPrefix: string): string {
  const relative = portableComponents(relativePath);
  const prefix = portableComponents(pathPrefix);
  const matches = prefix.every((component, index) => relative[index] === component);
  return (matches ? relative.slice(prefix.length) : relative).join("/");
}

export interface DesktopLibraryLocation {
  selectedRoot: string | null;
  collectionId: string;
  manifestPath: string;
  metadataRoot: string;
  mediaRoot: string | null;
  mediaPathPrefix: string;
  managedMediaRoot: string | null;
  mediaExpected: number;
  mediaFound: number;
  mediaExtra: number;
}

export function localMediaRoot(
  location: DesktopLibraryLocation,
  delivery?: "managed-local" | "referenced-local",
): string | null {
  return delivery === "managed-local" ? location.managedMediaRoot : location.mediaRoot;
}

async function fetchLocalJson<T>(path: string): Promise<T> {
  const response = await fetch(convertFileSrc(path), { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Could not load ${path} (${response.status})`);
  }
  return response.json() as Promise<T>;
}

export class DesktopCatalogRepository implements CatalogRepository {
  readonly canOpenInDefaultPlayer = true;
  readonly location: DesktopLibraryLocation;
  readonly youtubeBridgeBaseUrl: string;

  constructor(location: DesktopLibraryLocation, youtubeBridgeBaseUrl?: string) {
    this.location = location;
    this.youtubeBridgeBaseUrl = youtubeBridgeBaseUrl ?? DEFAULT_YOUTUBE_BRIDGE_URL;
  }

  get manifestLocation(): string {
    return this.location.manifestPath;
  }

  async loadCollection(): Promise<CollectionManifest> {
    return fetchLocalJson<CollectionManifest>(this.manifestLocation);
  }

  loadAnalysis(item: CatalogItem): Promise<VideoAnalysis> {
    return fetchLocalJson<VideoAnalysis>(
      joinLocalPath(this.location.metadataRoot, item.analysis.path),
    );
  }

  mediaUrl(item: CatalogItem): string | null {
    const media = item.media[0];
    if (!media) return null;
    if (media.type === "http-video") return media.url;
    if (media.type === "youtube") {
      return youtubeBridgeUrl(media.video_id, this.youtubeBridgeBaseUrl);
    }
    const root = localMediaRoot(this.location, media.delivery);
    if (!root) return null;
    const relativePath = media.delivery === "managed-local"
      ? media.relative_path
      : boundMediaRelativePath(media.relative_path, this.location.mediaPathPrefix);
    return convertFileSrc(joinLocalPath(root, relativePath), "stream");
  }

  async defaultPlayerName(item: CatalogItem): Promise<string | null> {
    const media = item.media.find((candidate) => candidate.type === "local-file");
    const root = media && localMediaRoot(this.location, media.delivery);
    if (!media || !root) return null;
    const relativePath = media.delivery === "managed-local"
      ? media.relative_path
      : boundMediaRelativePath(media.relative_path, this.location.mediaPathPrefix);
    try {
      return await invoke<string | null>("default_video_player", {
        path: joinLocalPath(root, relativePath),
      });
    } catch {
      return null;
    }
  }

  async openInDefaultPlayer(item: CatalogItem): Promise<boolean> {
    const media = item.media.find((candidate) => candidate.type === "local-file");
    const root = media && localMediaRoot(this.location, media.delivery);
    if (!media || !root) return false;
    const relativePath = media.delivery === "managed-local"
      ? media.relative_path
      : boundMediaRelativePath(media.relative_path, this.location.mediaPathPrefix);
    try {
      return await invoke<boolean>("open_video", {
        path: joinLocalPath(root, relativePath),
      });
    } catch {
      return false;
    }
  }

  async openExternalMedia(item: CatalogItem): Promise<boolean> {
    const media = item.media.find((candidate) => candidate.type === "youtube");
    if (!media) return false;
    try {
      return await invoke<boolean>("open_external_url", {
        url: youtubeWatchUrl(media.video_id),
      });
    } catch {
      return false;
    }
  }
}
