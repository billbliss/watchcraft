import type {
  CatalogItem,
  CatalogRepository,
  CollectionManifest,
  VideoAnalysis,
} from "@watchcraft/catalog-core";

export interface HttpCatalogOptions {
  manifestUrl: string;
}

async function fetchJson<T>(url: URL): Promise<T> {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Could not load ${url.pathname} (${response.status})`);
  }
  return response.json() as Promise<T>;
}

export class HttpCatalogRepository implements CatalogRepository {
  readonly manifestUrl: URL;
  private mediaRootUrl: URL | null = null;

  constructor(options: HttpCatalogOptions) {
    this.manifestUrl = new URL(options.manifestUrl, window.location.href);
  }

  get manifestLocation(): string {
    return this.manifestUrl.href;
  }

  async loadCollection(): Promise<CollectionManifest> {
    const manifest = await fetchJson<CollectionManifest>(this.manifestUrl);
    const directory = manifest.media_root.replace(/[\\/]+$/, "") || ".";
    this.mediaRootUrl = new URL(`${directory}/`, this.manifestUrl);
    return manifest;
  }

  loadAnalysis(item: CatalogItem): Promise<VideoAnalysis> {
    return fetchJson<VideoAnalysis>(new URL(item.analysis.path, this.manifestUrl));
  }

  mediaUrl(item: CatalogItem): string | null {
    const media = item.media[0];
    if (!media) return null;
    if (media.type === "url" && media.url) {
      return new URL(media.url, this.manifestUrl).href;
    }
    if (!this.mediaRootUrl) return null;
    return new URL(media.relative_path, this.mediaRootUrl).href;
  }

  async openInDefaultPlayer(item: CatalogItem): Promise<boolean> {
    const media = item.media.find((candidate) => candidate.type === "local-file");
    if (!media) return false;
    try {
      const response = await fetch(new URL("/api/open-video", this.manifestUrl), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ video: media.relative_path }),
      });
      return response.ok;
    } catch {
      return false;
    }
  }
}

export function repositoryFromLocation(location: Location): HttpCatalogRepository {
  const params = new URLSearchParams(location.search);
  return new HttpCatalogRepository({
    manifestUrl: params.get("catalog") ?? "/demo/collection.json",
  });
}
