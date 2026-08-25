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

export function parentLocalPath(path: string): string {
  const separator = separatorFor(path);
  const cleanPath = path.replace(/[\\/]+$/, "");
  const boundary = cleanPath.lastIndexOf(separator);
  return boundary > 0 ? cleanPath.slice(0, boundary) : cleanPath;
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
  readonly libraryRoot: string;
  private catalogRoot: string | null = null;

  constructor(libraryRoot: string) {
    this.libraryRoot = libraryRoot;
  }

  get manifestLocation(): string {
    return this.catalogRoot
      ? joinLocalPath(this.catalogRoot, "collection.json")
      : this.libraryRoot;
  }

  async loadCollection(): Promise<CollectionManifest> {
    const candidates = [
      joinLocalPath(this.libraryRoot, "collection.json"),
      joinLocalPath(this.libraryRoot, "Video Catalog/collection.json"),
    ];
    const failures: string[] = [];

    for (const candidate of candidates) {
      try {
        const manifest = await fetchLocalJson<CollectionManifest>(candidate);
        this.catalogRoot = parentLocalPath(candidate);
        return manifest;
      } catch (error: unknown) {
        failures.push(error instanceof Error ? error.message : String(error));
      }
    }

    throw new Error(
      `No collection.json was found in the selected library. ${failures.join(" ")}`,
    );
  }

  loadAnalysis(item: CatalogItem): Promise<VideoAnalysis> {
    if (!this.catalogRoot) {
      return Promise.reject(new Error("The collection manifest has not loaded."));
    }
    return fetchLocalJson<VideoAnalysis>(joinLocalPath(this.catalogRoot, item.analysis.path));
  }

  mediaUrl(item: CatalogItem): string | null {
    const media = item.media[0];
    if (!media) return null;
    if (media.type === "url" && media.url) return media.url;
    return convertFileSrc(joinLocalPath(this.libraryRoot, media.relative_path));
  }

  async openInDefaultPlayer(item: CatalogItem): Promise<boolean> {
    const media = item.media.find((candidate) => candidate.type === "local-file");
    if (!media) return false;
    try {
      return await invoke<boolean>("open_video", {
        path: joinLocalPath(this.libraryRoot, media.relative_path),
      });
    } catch {
      return false;
    }
  }
}
