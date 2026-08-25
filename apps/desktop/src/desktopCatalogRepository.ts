import { convertFileSrc, invoke } from "@tauri-apps/api/core";
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

export interface DesktopLibraryLocation {
  selectedRoot: string;
  catalogRoot: string;
  mediaRoot: string;
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

  constructor(location: DesktopLibraryLocation) {
    this.location = location;
  }

  get manifestLocation(): string {
    return joinLocalPath(this.location.catalogRoot, "collection.json");
  }

  async loadCollection(): Promise<CollectionManifest> {
    return fetchLocalJson<CollectionManifest>(this.manifestLocation);
  }

  loadAnalysis(item: CatalogItem): Promise<VideoAnalysis> {
    return fetchLocalJson<VideoAnalysis>(
      joinLocalPath(this.location.catalogRoot, item.analysis.path),
    );
  }

  mediaUrl(item: CatalogItem): string | null {
    const media = item.media[0];
    if (!media) return null;
    if (media.type === "url" && media.url) return media.url;
    return convertFileSrc(joinLocalPath(this.location.mediaRoot, media.relative_path), "stream");
  }

  async defaultPlayerName(item: CatalogItem): Promise<string | null> {
    const media = item.media.find((candidate) => candidate.type === "local-file");
    if (!media) return null;
    try {
      return await invoke<string | null>("default_video_player", {
        path: joinLocalPath(this.location.mediaRoot, media.relative_path),
      });
    } catch {
      return null;
    }
  }

  async openInDefaultPlayer(item: CatalogItem): Promise<boolean> {
    const media = item.media.find((candidate) => candidate.type === "local-file");
    if (!media) return false;
    try {
      return await invoke<boolean>("open_video", {
        path: joinLocalPath(this.location.mediaRoot, media.relative_path),
      });
    } catch {
      return false;
    }
  }
}
