// Only read duration messages from a player whose source and origin the caller verified.
export function youtubeDuration(data: unknown): number | null {
  if (typeof data === "string") {
    try { data = JSON.parse(data); } catch { return null; }
  }
  if (!data || typeof data !== "object") return null;
  const message = data as { event?: string; info?: { duration?: unknown } };
  if (message.event !== "infoDelivery" && message.event !== "initialDelivery") return null;
  const duration = message.info?.duration;
  return typeof duration === "number" && Number.isFinite(duration) && duration > 0 ? duration : null;
}
