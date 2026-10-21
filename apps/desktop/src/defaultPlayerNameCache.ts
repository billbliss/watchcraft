// Default-player associations depend on file type, not on the selected video.
// Cache in-flight work too, so rapid navigation doesn't spawn duplicate queries.
export class DefaultPlayerNameCache {
  private readonly entries = new Map<string, { expires: number; result: Promise<string | null> }>();

  constructor(private readonly now: () => number = Date.now) {}

  get(extension: string, load: () => Promise<string | null>): Promise<string | null> {
    const key = extension.toLowerCase();
    const existing = this.entries.get(key);
    if (existing && existing.expires > this.now()) return existing.result;
    const result = Promise.resolve().then(load).catch((error: unknown) => {
      if (this.entries.get(key)?.result === result) this.entries.delete(key);
      throw error;
    });
    this.entries.set(key, { expires: this.now() + 30_000, result });
    return result;
  }
}
