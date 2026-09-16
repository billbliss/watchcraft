import { lazy, Suspense, useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { ConvexProvider, ConvexReactClient, useAction, useQuery } from "convex/react";
import { ConvexError } from "convex/values";
import { api } from "../../../convex/_generated/api";
import type { ExistingCollection, Discovery } from "../../../convex/requestDiscovery";
import { parseYouTubeSource, type RequestScope } from "../../../packages/catalog-core/src/youtubeRequest";
import { ErrorBoundary } from "./ErrorBoundary";
const RequestAccount = lazy(() => import("./RequestAccount"));
const client = import.meta.env.VITE_CONVEX_URL ? new ConvexReactClient(import.meta.env.VITE_CONVEX_URL, { logger: false }) : null;
const labels: Record<string,string> = { video: "Just this video", playlist: "Playlist", popular: "Popular videos", channel: "Entire channel" };
export function requestState(state: string, processing: string | null) {
  if (processing) return ({ awaiting_approval: "Awaiting approval", approved: "Approved · waiting to start", running: "Processing", complete: "Processing complete · preparing collection", failed: "Processing needs attention", cancelled: "Not proceeding" } as Record<string,string>)[processing] ?? "In review";
  return ({ submitted: "Submitted · awaiting review", planning: "Preparing a plan and estimate", planned: "Plan ready for review", rejected: "Not proceeding" } as Record<string,string>)[state] ?? "Submitted";
}
function errorMessage(error: unknown) { return error instanceof ConvexError && typeof error.data === "string" ? error.data : "We couldn't complete that request. Please try again."; }
function initialFragment() { return new URLSearchParams(window.location.hash.slice(1)); }
function Status({ token }: { token: string }) {
  const status = useQuery(api.collectionRequests.status, /^[a-f0-9]{64}$/.test(token) ? { token } : "skip");
  const [copied, setCopied] = useState(false);
  if (!/^[a-f0-9]{64}$/.test(token)) return <p role="alert">This status link is invalid.</p>;
  if (status === undefined) return <p role="status">Loading your request…</p>;
  if (!status) return <p role="alert">This request wasn't found. Check the complete status link or return to your submission.</p>;
  return <section className="request-panel"><span className="status">{requestState(status.state, status.processingState)}</span><h2>{status.title}</h2>
    <p>{labels[status.selectedScope]}{status.selectedScope !== status.preferredScope ? ` · You requested ${labels[status.preferredScope].toLowerCase()}` : ""}</p>
    <p>Save this private link to check progress. Anyone with the link can view this request’s status.</p>
    <div className="request-inline"><button className="request-secondary" onClick={() => { void navigator.clipboard.writeText(window.location.href).then(() => setCopied(true)).catch(() => setCopied(false)); }}>{copied ? "Copied" : "Copy status link"}</button><a href={status.sourceUrl} target="_blank" rel="noreferrer">View on YouTube ↗</a></div>
    <p className="muted">Email notifications are not enabled yet.</p></section>;
}
function History() {
  const requests = useQuery(api.collectionRequests.mine);
  return <section><h2>Your requests</h2>{requests === undefined ? <p role="status">Loading…</p> : requests.length === 0 ? <p className="muted">Requests submitted while signed in will appear here.</p> : <ul className="request-history">{requests.map(r => <li key={r.id}><strong>{r.title}</strong><span>{requestState(r.state, r.processingState)}</span><small>{labels[r.selectedScope]}</small></li>)}</ul>}</section>;
}
interface Draft { source: string; data: (Discovery & { existing?: ExistingCollection[]; alreadyRequested?: boolean }) | null; scope: RequestScope; }
function Form({ draft, update, signedIn, onSubmitted }: { draft: Draft; update: (draft: Draft) => void; signedIn: boolean; onSubmitted: (token: string) => void }) {
  const preview = useAction(api.collectionRequests.preview); const submit = useAction(api.collectionRequests.submit);
  const [busy, setBusy] = useState(false); const [error, setError] = useState("");
  const inFlight = useRef(false); const commands = useRef(new Map<string,string>());
  const autoChecked = useRef<string | null>(null);
  const inspect = useCallback(async (event?: FormEvent) => {
    event?.preventDefault(); if (inFlight.current) return; inFlight.current = true; setBusy(true); setError("");
    try { const data = await preview({ source: draft.source }); update({ source: data.source.url, data, scope: data.source.playlistId ? "playlist" : data.source.kind === "channel" ? (data.options.some(o => o.scope === "popular") ? "popular" : "channel") : "video" }); }
    catch (e) { setError(errorMessage(e)); } finally { inFlight.current = false; setBusy(false); }
  }, [draft.source, preview, update]);
  useEffect(() => {
    const source = initialFragment().get("source");
    if (!source || source !== draft.source || draft.data || busy || autoChecked.current === source) return;
    autoChecked.current = source;
    void inspect();
  }, [draft.source, draft.data, busy, inspect]);
  async function send() {
    if (!draft.data || inFlight.current) return; inFlight.current = true; setBusy(true); setError("");
    const key = `${draft.data.source.key}:${draft.scope}:${signedIn}`;
    let token = commands.current.get(key);
    if (!token) { token = Array.from(crypto.getRandomValues(new Uint8Array(32)), n => n.toString(16).padStart(2,"0")).join(""); commands.current.set(key, token); }
    try { await submit({ source: draft.data.source.url, preferredScope: draft.scope, token, attachAccount: signedIn }); onSubmitted(token); }
    catch (e) { setError(errorMessage(e)); } finally { inFlight.current = false; setBusy(false); }
  }
  return <section className="request-panel">
    <form onSubmit={inspect}><label htmlFor="youtube-source">YouTube video, playlist, or channel</label><div className="request-source"><input id="youtube-source" autoComplete="off" autoCapitalize="none" spellCheck={false} placeholder="Paste a YouTube link or playlist ID" value={draft.source} disabled={busy} onChange={e => update({ ...draft, source: e.target.value, data: null })} required maxLength={2048} /><button className="request-primary" disabled={busy || !draft.source.trim()}>{busy ? "Checking…" : "Check link"}</button></div></form>
    {error && <p role="alert" className="feedback error">{error}</p>}
    {draft.data && <div className="request-result"><div className="request-preview">{draft.data.thumbnail && <img src={draft.data.thumbnail} alt="" referrerPolicy="no-referrer" className={draft.data.source.kind === "channel" ? "channel-avatar" : undefined} width={draft.data.source.kind === "channel" ? 96 : 160} height={draft.data.source.kind === "channel" ? 96 : 90} />}<div><h2>{draft.data.title}</h2>{draft.data.source.kind === "channel" ? <p>YouTube channel</p> : draft.data.channel && <p>{draft.data.channel}</p>}</div></div>
      {draft.data.warning && <p className="muted">{draft.data.warning}</p>}
      {draft.data.alreadyRequested && <p className="notice">A request for this link already exists. Submitting will give you a status link for that request without creating duplicate work.</p>}
      {Boolean(draft.data.existing?.length) && <section className="notice"><h3>Already available in Watchcraft</h3><p>{draft.data.source.videoId ? "The requested video appears in " : "The requested playlist appears in "}{draft.data.existing!.length === 1 ? "this collection" : "these collections"}.</p>{draft.data.existing!.map(collection => <p key={collection.manifestUrl}><strong>{collection.title}</strong><br /><a href={`watchcraft://install?url=${encodeURIComponent(collection.manifestUrl)}`}>Load in Watchcraft</a>{collection.supportsWeb && <>{" · "}<a href={`/app/?catalog=${encodeURIComponent(collection.manifestUrl)}`} target="_blank" rel="noreferrer">Open in browser</a></>}</p>)}<p className="muted">You can still suggest a different scope below.</p></section>}
      <fieldset disabled={busy}><legend>What would you like included?</legend>{draft.data.options.map(option => <label className={`scope-option ${draft.scope === option.scope ? "selected" : ""}`} key={option.scope}><input type="radio" name="scope" value={option.scope} checked={draft.scope === option.scope} onChange={() => update({ ...draft, scope: option.scope })} /><span><strong>{option.title}</strong><small>{option.count === null ? "Video count checked during planning" : `${option.count} ${option.count === 1 ? "video" : "videos"}`}{option.scope === "channel" ? " · Large channels can take substantial time to process." : option.scope === "popular" ? " · Up to 20 videos, checked again when the plan is prepared." : ""}</small></span></label>)}</fieldset>
      <p className="muted">We’ll review the scope, time, and cost before processing. Submitting doesn’t start a job.</p>
      <button className="request-primary" disabled={busy} onClick={() => void send()}>{busy ? "Submitting…" : signedIn ? "Submit request" : "Submit without signing in"}</button>
      <p className="muted">{signedIn ? "This request will be saved to your account history." : "No name or email required. You’ll receive a private status link to save."}</p>
    </div>}
  </section>;
}
export function SubmissionApp() {
  const [accountMode, setAccountMode] = useState(() => initialFragment().get("account") === "1");
  const [token, setToken] = useState(() => initialFragment().get("status") ?? "");
  const [draft, setDraft] = useState<Draft>(() => ({ source: initialFragment().get("source") ?? "", data: null, scope: "video" }));
  useEffect(() => { const changed = () => { const params = initialFragment(); setToken(params.get("status") ?? ""); if (params.has("source")) setDraft({ source: params.get("source")!, data: null, scope: "video" }); }; window.addEventListener("hashchange", changed); return () => window.removeEventListener("hashchange", changed); }, []);
  let accountSource = "";
  try { accountSource = parseYouTubeSource(draft.source).url; } catch { /* Do not forward arbitrary pasted text to sign-in. */ }
  const accountReturn = `/submit/#${new URLSearchParams({ account: "1", ...(accountSource ? { source: accountSource } : {}) }).toString()}`;
  function chooseAccount() {
    if (!token) window.history.replaceState(null, "", accountReturn);
    setAccountMode(true);
  }
  function chooseAnonymous() {
    const params = initialFragment(); params.delete("account");
    window.history.replaceState(null, "", `${window.location.pathname}${params.size ? `#${params}` : ""}`);
    setAccountMode(false);
  }
  const content = (signedIn: boolean) => <>{token ? <Status token={token} /> : <Form draft={draft} update={setDraft} signedIn={signedIn} onSubmitted={value => { window.location.hash = new URLSearchParams({ status: value }).toString(); setToken(value); }} />}{signedIn && <History />}</>;
  return <div className="shell request-shell"><header className="header"><a className="brand" href="/">Watchcraft</a><a href="/">Back to website ↗</a></header><main>
    <div className="page-heading"><p className="eyebrow">Watchcraft</p><h1>{token ? "Your request" : "Suggest a collection"}</h1><p>Bring a video, playlist, or channel into Watchcraft.</p></div>
    <ErrorBoundary>{!client ? <p className="notice">Submissions aren’t available yet. Please check back soon.</p> : accountMode ? <><Suspense fallback={<p role="status">Loading sign-in…</p>}><RequestAccount returnTo={accountReturn}>{content}</RequestAccount></Suspense><button className="request-text" onClick={chooseAnonymous}>Continue without signing in</button></> : <ConvexProvider client={client}>{content(false)}<p className="request-signin">Want to keep a request history? <button className="request-text" onClick={chooseAccount}>Sign in (optional)</button></p></ConvexProvider>}</ErrorBoundary>
    {token && <a className="request-text" href="#" onClick={() => { setToken(""); setDraft({ source: "", data: null, scope: "video" }); }}>Suggest another collection</a>}
  </main></div>;
}
