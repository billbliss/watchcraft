import { useEffect, useId, useRef, useState } from "react";
import { useAction, useMutation, useQuery } from "convex/react";
import { ConvexError } from "convex/values";
import type { FunctionReturnType } from "convex/server";
import { api } from "../../../convex/_generated/api";
import type { RequestScope } from "../../../packages/catalog-core/src/youtubeRequest";
const preparationLabels: Record<string, string> = { discovering: "Checking videos", snapshot: "Saving the video list", estimating: "Estimating time and cost", linking: "Preparing approval", failed: "Planning needs attention" };
const scopeLabels: Record<string, string> = { video: "Single video", playlist: "Playlist", popular: "Popular videos", channel: "Entire channel" };
type Item = FunctionReturnType<typeof api.collectionRequests.queue>["requests"][number];
function RequestCard({ item }: { item: Item }) {
  const [scope, setScope] = useState(item.selectedScope as RequestScope); const [busy, setBusy] = useState(false); const [error, setError] = useState("");
  const [expanded, setExpanded] = useState(false);
  const detailsId = useId();
  const preview = useAction(api.collectionRequests.preview);
  const [previewData, setPreviewData] = useState<FunctionReturnType<typeof api.collectionRequests.preview> | null>(null);
  const [previewError, setPreviewError] = useState(false);
  const [previewLoading, setPreviewLoading] = useState(false);
  const previewInFlight = useRef(false);
  async function loadPreview() {
    if (previewData || previewInFlight.current) return;
    previewInFlight.current = true; setPreviewLoading(true); setPreviewError(false);
    try { setPreviewData(await preview({ source: item.sourceUrl })); }
    catch { setPreviewError(true); }
    finally { previewInFlight.current = false; setPreviewLoading(false); }
  }
  const review = useMutation(api.collectionRequests.reviewRequest);
  async function decide(decision: "plan" | "reject") {
    if (busy) return; setBusy(true); setError("");
    try { await review({ requestId: item.id, expectedRevision: item.revision, selectedScope: scope, decision }); }
    catch (e) { setError(e instanceof ConvexError && typeof e.data === "string" ? e.data : "Unable to update this request. Try again."); }
    finally { setBusy(false); }
  }
  const requesters = [...new Set(item.requesters.map(r => r.label))].join(", ") + (item.hasMoreRequesters ? ", …" : "");
  const status = item.preparation ? (item.preparation.stalled ? "Planning interrupted" : preparationLabels[item.preparation.stage] ?? "Preparing plan") : item.state === "planning" ? "Queued for planning" : null;
  return <article className="request-row">
    <div className="request-row-summary">
      <button className="request-expand" aria-expanded={expanded} aria-controls={detailsId} aria-label={`${expanded ? "Collapse" : "Expand"} ${item.title}`} onClick={() => { setExpanded(!expanded); if (!expanded) void loadPreview(); }}><span aria-hidden="true">{expanded ? "▾" : "▸"}</span></button>
      <h3 className="request-row-title"><a href={item.sourceUrl} target="_blank" rel="noreferrer" title={item.title}>{item.title} ↗</a></h3>
      <p className="request-row-meta" title={`Submitted ${new Date(item.submittedAt).toLocaleString()} · By ${requesters}`}><time dateTime={new Date(item.submittedAt).toISOString()}>{new Date(item.submittedAt).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}</time> · {requesters}{item.requesters.length > 1 ? ` · ${item.requesters.length}${item.hasMoreRequesters ? "+" : ""} requests` : ""}{status && <> · <span className="status">{status}</span></>}</p>
      <select className="request-row-scope" aria-label={`Collection scope for ${item.title}`} disabled={busy} value={scope} onChange={e => setScope(e.target.value as RequestScope)}>{item.options.map(option => <option key={option.scope} value={option.scope}>{scopeLabels[option.scope] ?? option.title}{option.count !== null && option.scope !== "video" ? ` · ${option.count}` : ""}</option>)}</select>
      <div className="request-row-actions"><button className="reject" disabled={busy} onClick={() => void decide("reject")}>Reject request</button><button className="accept" disabled={busy || (item.state === "planning" && scope === item.selectedScope && item.preparation?.stage !== "failed" && !item.preparation?.stalled)} onClick={() => void decide("plan")}>{busy ? "Saving…" : item.preparation?.stage === "failed" || item.preparation?.stalled ? "Retry planning" : item.state === "planning" ? "Update scope" : "Mark for planning"}</button></div>
    </div>
    {expanded && <div id={detailsId} className="request-row-details">
      {previewLoading && <p role="status">Loading preview…</p>}
      {previewError && <p>Preview unavailable. <button className="request-text" onClick={() => void loadPreview()}>Try again</button></p>}
      {previewData && <div className="inbox-preview">
        {previewData.thumbnail && <img src={previewData.thumbnail} alt="" referrerPolicy="no-referrer" className={previewData.source.kind === "channel" ? "channel-avatar" : undefined} />}
        <div><p>{previewData.source.kind === "channel" ? "YouTube channel" : previewData.source.kind === "playlist" ? "YouTube playlist" : "YouTube video"}{previewData.source.kind !== "channel" && previewData.channel ? ` · ${previewData.channel}` : ""}</p>
          <a href={item.sourceUrl} target="_blank" rel="noreferrer">View on YouTube ↗</a>
          {previewData.warning && <p>{previewData.warning}</p>}
        </div>
      </div>}
      <p>Time and cost will be estimated during planning.</p>
      {item.preparation?.stage === "failed" || item.preparation?.stalled ? <p>The plan couldn't be completed. Retry planning or choose a different scope.</p> : null}
    </div>}
    {error && <p className="feedback error" role="alert">{error}</p>}
  </article>;

}
export function RequestInbox() {
  const data = useQuery(api.collectionRequests.queue);
  const [now, setNow] = useState(Date.now);
  useEffect(() => { const timer = setInterval(() => setNow(Date.now()), 10_000); return () => clearInterval(timer); }, []);
  const plannerOnline = data?.plannerHeartbeatAt != null && now - data.plannerHeartbeatAt < 60_000;
  return <section aria-labelledby="requests-heading"><div className="section-heading"><h2 id="requests-heading">Collection requests <span className="count">{data?.requests.length ?? "…"}{data?.hasMore ? "+" : ""}</span></h2><a href="/submit/">Suggest a collection ↗</a></div>
    {data && <p className="planner-connection" role="status">{plannerOnline ? "Planner connected · marked requests are picked up automatically" : "Planner offline · marked requests will wait until it connects"}</p>}
    {!data ? <p role="status">Loading requests…</p> : data.requests.length === 0 ? <p className="notice">New video, playlist, and channel suggestions will appear here before they become processing plans.</p> : <div className="request-queue">{data.requests.map(item => <RequestCard key={`${item.id}:${item.revision}`} item={item} />)}</div>}
    {data?.hasMore && <p className="muted">Showing the oldest 50 requests awaiting review or planning.</p>}</section>;
}
