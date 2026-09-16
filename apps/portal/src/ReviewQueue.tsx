import { useRef, useState } from "react";
import { useMutation, useQuery } from "convex/react";
import { ConvexError } from "convex/values";
import type { FunctionReturnType } from "convex/server";
import { api } from "../../../convex/_generated/api";
import { RequestInbox } from "./RequestInbox";

type OverviewData = FunctionReturnType<typeof api.portal.overview>;
type Submission = OverviewData["pending"][number];
const timestamp = (value: number) => new Date(value).toLocaleString(undefined, {
  month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit", timeZoneName: "short",
});
export function duration(value: number | null): string {
  if (value === null) return "Not estimated";
  if (value === 0) return "0 min";
  if (value < 60) return "Less than 1 min";
  const minutes = Math.ceil(value / 60);
  return minutes < 60 ? `${minutes} min` : `${Math.floor(minutes / 60)} hr${minutes % 60 ? ` ${minutes % 60} min` : ""}`;
}
export function cost(value: number | null): string {
  if (value === null) return "Not estimated";
  if (value > 0 && value < .01) return "Less than $0.01";
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(value);
}
function Submitted({ submission }: { submission: Submission }) {
  return <p className="submission-meta">Submitted <time dateTime={new Date(submission.submittedAt).toISOString()}>{timestamp(submission.submittedAt)}</time>
    <span>By <strong>{submission.submittedBy ?? "Not recorded"}</strong>{submission.submitterIsCli && " · CLI"}</span></p>;
}

function FailureDetails({ item }: { item: Submission }) {
  const [expanded, setExpanded] = useState(false);
  const details = useQuery(api.portal.failureDetails, { executionId: item.id });
  if (!details) return <p className="muted">Loading failure details…</p>;
  return <div className="failure-details">
    <p>{details.completed === details.total ? `Video processing finished for all ${details.total} videos. Collection preparation is not finished.` : `${details.completed} / ${details.total} videos processed · ${details.failures.length} failed.`} Completed video work is kept when you retry.</p>
    {details.stageFailure && <div>
      <p><strong>{details.stageFailure.affectedVideo ?? "Collection stage failed"}</strong></p>
      <p>{details.stageFailure.message}</p>
      <p className="muted">{timestamp(details.stageFailure.occurredAt)}{details.stageFailure.attempts !== null ? ` · ${details.stageFailure.attempts} worker attempt(s)` : ""}</p>
      <p>{details.stageFailure.guidance}</p>
      <details><summary>Diagnostics</summary>
        <p>Execution: <code>{item.id}</code></p>
        {details.stageFailure.jobId && <><p>Job: <code>{details.stageFailure.jobId}</code></p><p>Inspect with the CLI:</p><code>./authoring/watchcraft-author queue status --operator-token-source keychain {details.stageFailure.jobId}</code></>}
        {details.stageFailure.logUrl && <p><a href={details.stageFailure.logUrl} target="_blank" rel="noreferrer">Open worker log ↗</a></p>}
      </details>
    </div>}
    {details.failures.length === 0 ? !details.stageFailure && <p className="muted">No video-level error was recorded. The workflow stopped during {workflowLabels[item.workflow?.phase ?? ""]?.toLowerCase() ?? "collection preparation"}.</p> :
      <div>
        <button type="button" className="failure-toggle" aria-expanded={expanded} onClick={() => setExpanded(value => !value)}>
          {expanded ? "▾ Hide failures and attempt history" : "▸ Show failures and attempt history"}
        </button>
        {expanded && <div>
        {details.historyLimited && <p className="muted">History is limited; counts below are recorded minimums.</p>}
        {details.failures.map(failure => <article key={failure.id}>
          <strong>{failure.title}</strong>
          <p className="muted">{failure.attempts ? `${failure.attempts} recorded attempt${failure.attempts === 1 ? "" : "s"} · ` : "Attempt count unavailable · "}{failure.failureCount} recorded failure{failure.failureCount === 1 ? "" : "s"}</p>
          {failure.errors.map((error, index) => <p key={index}><time>{timestamp(error.occurred_at)}</time> — {error.message}</p>)}
        </article>)}
        </div>}
      </div>}
  </div>;
}

const workflowLabels: Record<string, string> = { processing: "Processing videos", terminology: "Resolving terminology", normalization: "Organizing topics", compilation: "Building collection", preview: "Publishing preview", ready: "Ready", pull_request: "Opening pull request" };
function WorkflowActions({ item }: { item: Submission }) {
  const retry = useMutation(api.portalWorkflows.retry);
  const requestPr = useMutation(api.portalWorkflows.requestPullRequest);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const work = item.workflow;
  async function act(kind: "retry" | "pr") {
    if (busy) return;
    setBusy(true); setError("");
    try { await (kind === "retry" ? retry : requestPr)({ executionId: item.id }); }
    catch { setError("Unable to save this action. Please try again."); }
    finally { setBusy(false); }
  }
  return <>
    <div className="completion-actions">
      {work?.preview_url ? <><a href={`watchcraft://install?url=${encodeURIComponent(work.preview_url)}`}>Load in Watchcraft</a><a href={`/app/?catalog=${encodeURIComponent(work.preview_url)}`} target="_blank" rel="noreferrer">Open in browser ↗</a></> : <button disabled>Load in Watchcraft</button>}
      {work?.pull_request_url ? <a href={work.pull_request_url} target="_blank" rel="noreferrer">View pull request ↗</a> : <button disabled={busy || !work?.preview_url || work.phase === "pull_request"} onClick={() => void act("pr")}>{work?.phase === "pull_request" ? work.state === "queued" ? "Pull request queued" : work.state === "failed" ? "Pull request failed" : "Creating pull request…" : "Submit pull request"}</button>}
      {work?.state === "failed" && <button disabled={busy} onClick={() => void act("retry")}>Retry {workflowLabels[work.phase]?.toLowerCase() ?? "workflow"}</button>}
    </div>
    <small>{work ? `${work.state === "failed" ? "Needs attention · " : ""}${work.pull_request_url ? "Pull request submitted" : work.phase === "pull_request" && work.state === "queued" ? "Waiting for the local worker to create the pull request" : work.phase === "ready" && work.preview_url ? "Preview ready · awaiting pull request" : workflowLabels[work.phase] ?? work.phase}` : "No preview is attached to this earlier run."}</small>
    {work?.state === "failed" && <FailureDetails item={item} />}
    {error && <p className="feedback error" role="alert">{error}</p>}
  </>;
}

export function ReviewQueue() {
  const data = useQuery(api.portal.overview);
  const review = useMutation(api.portal.review);
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const requests = useRef(new Map<string, string>());
  const pendingRequest = useRef(false);
  async function decide(submission: Submission, decision: "accept" | "reject") {
    if (pendingRequest.current) return;
    pendingRequest.current = true;
    setBusy(submission.id); setError(""); setNotice("");
    const key = `${submission.id}:${submission.revision}:${decision}`;
    let commandId = requests.current.get(key);
    if (!commandId) { commandId = crypto.randomUUID(); requests.current.set(key, commandId); }
    try {
      await review({ executionId: submission.id, decision, commandId, expectedRevision: submission.revision, approvalSha256: submission.approvalSha256 });
      setNotice(decision === "accept" ? `${submission.title} accepted. Queued for automatic processing.` : `${submission.title} rejected. Processing will not start for this submission.`);
    } catch (cause) {
      setError(cause instanceof ConvexError && typeof cause.data === "string" ? cause.data : "Unable to save the decision. Check your connection and try again.");
    } finally { setBusy(null); pendingRequest.current = false; }
  }
  if (!data) return <p className="notice" role="status">Loading submissions…</p>;
  const unfinished = [...data.accepted, ...data.running, ...(data.failed ?? []), ...data.completed.filter(item => item.workflow && !item.workflow.preview_url)];
  const inFlight = unfinished.filter(item => item.workflow ? ["queued", "running"].includes(item.workflow.state) : ["approved", "running"].includes(item.state));
  const attention = unfinished.filter(item => item.workflow?.state === "failed" || (!item.workflow && item.state === "failed"));
  const readyToPublish = data.completed.filter(item => item.workflow?.preview_url && !item.workflow.pull_request_url);
  const submittedPrs = data.completed.filter(item => item.workflow?.pull_request_url);
  const completed = data.completed.filter(item => !item.workflow);
  return <>
    <RequestInbox />
    {notice && <p className="feedback" role="status">{notice}</p>}
    {error && <p className="feedback error" role="alert">{error}</p>}
    <section aria-labelledby="review-heading">
      <div className="section-heading"><h2 id="review-heading">Awaiting review <span className="count">{data.pending.length}{data.hasMorePending ? "+" : ""}</span></h2><span>Oldest submissions first</span></div>
      {data.pending.length === 0 ? <div className="notice empty"><h3>Nothing awaiting review</h3><p>Submitted project plans will appear here with their estimates, ready to accept or reject.</p></div>
        : <div className="review-list">{data.pending.map((submission) => <article className="review-card approval-card" key={submission.id}>
          <div className="review-title"><div><h3>{submission.title}</h3><Submitted submission={submission} /></div></div>
          <dl className="review-facts">
            <div><dt>Videos</dt><dd>{submission.total}</dd></div>
            <div><dt>Estimated time</dt><dd>{duration(submission.estimate.expectedSeconds)}</dd>{submission.estimate.highSeconds !== null && <small>{duration(submission.estimate.highSeconds)} conservative</small>}</div>
            <div><dt>Estimated model cost</dt><dd>{cost(submission.estimate.expectedCostUsd)}</dd>{submission.estimate.highCostUsd !== null && <small>{cost(submission.estimate.highCostUsd)} conservative</small>}</div>
          </dl>
          <details className="estimate-details approval-details"><summary>Plan details</summary>
            <ol className="selected-videos">{submission.selectedItems.map((item, index) => <li key={item.id}>{item.url ? <a href={item.url} target="_blank" rel="noreferrer">{item.title ?? `Video ${index + 1} · ${item.id.slice(8)}`} ↗</a> : item.id}</li>)}</ol>
            <p>Revision {submission.projectRevision}{submission.estimate.confidence ? ` · ${submission.estimate.confidence} confidence` : ""}{submission.estimate.concurrency !== null ? ` · Estimated with ${submission.estimate.concurrency} concurrent videos` : ""}{` · Approved concurrency: ${submission.concurrency}`}</p>
          </details>
          {submission.estimate.fullPlanItems !== null && submission.estimate.fullPlanItems !== submission.total && <p className="estimate-scope">Estimates cover all {submission.estimate.fullPlanItems} planned items, not just the {submission.total} selected here.</p>}
          <div className="review-actions"><div>
            <button className="reject" disabled={busy !== null} onClick={() => void decide(submission, "reject")} aria-label={`Reject ${submission.title}`}>Reject</button>
            <button className="accept" disabled={busy !== null} onClick={() => void decide(submission, "accept")} aria-label={`Accept ${submission.title}`}>{busy === submission.id ? "Saving…" : "Accept"}</button>
          </div></div>
        </article>)}</div>}
      {data.hasMorePending && <p className="muted">Showing the oldest 50 submissions. More appear as these are reviewed.</p>}
    </section>
    <section aria-labelledby="processing-heading">
      <div className="section-heading"><h2 id="processing-heading">In-flight processing</h2><span>{data.activeJobs.length}{data.hasMoreJobs ? "+" : ""} active jobs</span></div>
      {inFlight.length > 0 && <div className="running-projects">{inFlight.map(item => <div key={item.id}>
        <div><strong>{item.title}</strong><span>{item.completed === item.total ? `All ${item.total} videos processed` : `${item.completed} / ${item.total} videos processed`}</span></div>
        <p className="muted">{item.workflow?.state === "queued"
          ? `Queued${item.queuePosition ? ` · #${item.queuePosition} waiting` : ""} · ${workflowLabels[item.workflow.phase] ?? "Processing videos"}${item.waitingOn ? ` · Waiting for ${item.waitingOn} to finish its current stage` : " · Waiting for the worker"}`
          : `${workflowLabels[item.workflow?.phase ?? "processing"] ?? "Processing"} · In progress`}</p>
        {item.completed < item.total ? <progress aria-label={`${item.title} video processing progress`} value={item.completed} max={Math.max(1, item.total)} /> : <p className="muted">Collection preparation is still underway.</p>}
      </div>)}</div>}
      {data.hasMoreRunning && <p className="muted">Showing the 50 most recently updated active projects.</p>}
      {data.activeJobs.length === 0 ? <p className="notice">{inFlight.length ? "Collections are queued or being prepared. No video jobs are active at the moment." : "No jobs are currently queued or running."}</p>
        : <div className="table-scroll"><table><thead><tr><th>Video</th><th>Job</th><th>Status</th><th>Progress</th><th>Last update</th></tr></thead>
          <tbody>{data.activeJobs.map((job) => <tr key={job.id}>
            <td>{job.videoTitle ?? job.videoId ?? job.project}</td><td className="job-title">{job.title}</td>
            <td><span className="status">{{ ready: "Queued", dispatch_pending: "Dispatching", dispatched: "Waiting for worker", claimed: "Starting", running: "Running" }[job.state as string] ?? job.state}</span></td>
            <td>{job.progress ? <>{job.progress.phase}<small>{job.progress.completed}{job.progress.total !== null ? ` / ${job.progress.total}` : ""} {job.progress.unit}</small></> : "Waiting for update"}</td>
            <td><time dateTime={new Date(job.updatedAt).toISOString()}>{timestamp(job.updatedAt)}</time></td>
          </tr>)}</tbody></table></div>}
      {data.hasMoreJobs && <p className="muted">Showing the 100 most recently updated active jobs.</p>}
    </section>
    {attention.length > 0 && <section><h2>Needs attention</h2>{attention.map(item => <article className="notice" key={item.id}><h3>{item.title}</h3><WorkflowActions item={item} /></article>)}</section>}
    {[{ id: "publish", title: "Ready to publish", items: readyToPublish }, { id: "pull-requests", title: "Submitted pull requests", items: submittedPrs }].map(group => group.items.length > 0 &&
      <section key={group.id} aria-labelledby={`${group.id}-heading`}>
        <div className="section-heading"><h2 id={`${group.id}-heading`}>{group.title} <span className="count">{group.items.length}</span></h2></div>
        <div className="table-scroll"><table><thead><tr><th>Project</th><th>Videos</th><th>Next steps</th></tr></thead>
          <tbody>{group.items.map(item => <tr key={item.id}><td>{item.title}<small>Revision {item.projectRevision}</small></td><td>{item.total}</td><td><WorkflowActions item={item} /></td></tr>)}</tbody>
        </table></div>
      </section>)}
    <details className="history"><summary>Completed projects <span>{completed.length}{data.hasMoreCompleted ? "+" : ""}</span></summary>
      {completed.length === 0 ? <p className="muted">No completed project runs yet.</p> : <div className="table-scroll"><table>
        <thead><tr><th>Project</th><th>Items</th><th>Completed</th><th>Next steps</th></tr></thead>
        <tbody>{completed.map((item) => <tr key={item.id}>
          <td>{item.title}<small>Revision {item.projectRevision}</small></td><td>{item.completed} / {item.total}</td><td>{timestamp(item.updatedAt)}</td>
          <td><WorkflowActions item={item} /></td>
        </tr>)}</tbody>
      </table></div>}
      {data.hasMoreCompleted && <p className="muted">Showing the 20 most recently completed runs.</p>}
    </details>
  </>;
}
