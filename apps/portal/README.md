# Watchcraft portal

The portal is a separate React/Vite workspace at `/portal/` on the existing
GitHub Pages website. It uses Clerk sessions and Convex authorization. Its main
screen is a submission review queue, followed by approved work waiting to start,
in-flight jobs, and collapsed completed project history.

## Reviewing work

Pending submissions show their creation time, submitter, selected items, and the
time/model-cost estimates bound to the approval. Full-plan estimates are labeled
when a submission selects fewer items; unknown estimates are not treated as zero.
New CLI submissions record the local username, or an explicit `--submitted-by`
name/email. This is operator-supplied attribution, not a verified Clerk identity.
Older submissions display “Not recorded.”

Accept and Reject are owner-authorized mutations. Accept approves the exact
revision and plan digest, rechecking the current project and successful plan.
Reject cancels a still-pending execution. Both decisions record the authenticated
actor and support idempotent retry. Accept atomically queues a workflow for the
connected `run-portal-worker` consumer.

In-flight jobs include ready, dispatch-pending, dispatched, claimed, and running
states. Terminal jobs do not appear there. Lists filter by indexed state before
applying limits, so completed records cannot hide pending submissions.

Completed video processing advances into collection assembly. These stages stay
visible in-flight until a verified preview is ready. The completed row then
enables Load in Watchcraft, Open in browser, and an explicit Submit pull request
action. Internal compilation artifact URLs are never used as loadable manifests.

The homepage and gallery load the portal's `navigation.js` entry. The link starts
hidden and appears only after Convex confirms the current user is authorized.
Signing out hides it again. Direct access to `/portal/` shows Clerk sign-in.
The HTML and JavaScript are public; project data remains behind Convex checks.

## Clerk setup

Use the existing Watchcraft Clerk application, `app_3JISNDjlY7GTxU9QeoDIWEuQCQj`.
Clerk CLI authorization is optional. Manual configuration needs only the public
publishable key and issuer domain; no Clerk secret key belongs in this app.

1. Enable the desired sign-in method in Clerk (email verification codes for the
   initial setup).
2. Activate the Convex integration/JWT template in the appropriate Clerk instance.
   Its audience must be `convex`.
3. Configure `CLERK_JWT_ISSUER_DOMAIN` on the matching Convex deployment.
4. Create/sign in as the intended owner in this Clerk application, then configure
   that user's ID as `CLERK_PORTAL_USER_ID` on the same Convex deployment.
   The Clerk dashboard account is distinct from an application user.
5. Deploy the Convex functions and auth configuration.

Every portal data query checks both the trusted issuer and this user ID. No
first-user auto-enrollment, email-only check, or client-side permission flag is
used. Missing settings deny access. Convex requires the issuer environment
variable to be defined when deploying the auth config; set it to an empty string
on deployments where browser authentication is intentionally disabled.

The existing operator, worker, and registry administrator credentials and HTTP
routes remain independent. Owner-only portal mutations enforce the same owner
check before performing any work. Public request intake has separate, narrowly
scoped endpoints and cannot approve processing.

## Local development

Copy `.env.example` to `.env.local` in this workspace and supply:

- `VITE_CLERK_PUBLISHABLE_KEY`: this application's development publishable key.
- `VITE_CONVEX_URL`: the matching development Convex deployment URL.

From the repository root, `npm run portal:dev` opens the portal development
server. Use `npm run site:build` followed by `npm run site:preview` to test the
homepage, gallery, portal, and shared session at a single origin. Hash-based
Clerk routing supports refresh and sign-in callbacks on static hosting.

## Production

Use Clerk's production instance with primary domain `watchcraft.stream` and
complete its DNS verification. Development and production user IDs differ;
configure the production owner's ID explicitly in production Convex.

Set GitHub repository variables `VITE_CLERK_PUBLISHABLE_KEY` (a `pk_live_` key)
and `VITE_CONVEX_URL` (the production Convex URL). Deploy the Convex auth and
portal functions before publishing the website through the existing Pages
workflow. The workflow refuses to publish with missing portal configuration or
a development Clerk key.

Neither production deployment nor user authorization is implied by a successful
local build. Verify a signed-out visit, owner sign-in, homepage link, sign-out,
and rejection of another application user before considering setup complete.

## Public collection suggestions

The same build serves `/submit/`, with anonymous submission by default and Clerk
loaded only when the visitor chooses account mode. Account history is optional;
email notifications are deferred. The page hands canonical content and scope to
Convex actions, while private status links carry random receipt tokens in their
fragments. Only token hashes are persisted. No requester identity is attached to
anonymous receipts.

The portal's new Collection requests section precedes the existing approval queue.
The authoring operator lists work with `queue request-inbox`, then runs
`queue prepare-request REQUEST_ID --expected-revision REVISION`. This resolves
membership and runs the existing metadata-only iterator and planner, returning
an exact approval-bound execution to the portal. Preparation progress and retry
states appear on each request. Run `queue run-request-planner` to keep a foreground consumer connected. It
polls every 10 seconds, prepares one request at a time, and maintains a heartbeat
shown in the portal. `--once` handles at most one queued request for verification.
Failed or interrupted requests require an explicit Retry in the portal. The
runner never approves project execution.

The runner uses the existing hosted operator/worker connection. The local
preview build now targets that same hosted backend through the ignored
`apps/portal/.env.production.local` override. Its Clerk development instance is
owner-authorized on that backend for this preview. Local-development submissions
remain in the separate local database; they are not copied automatically.
Marking a request while the runner is offline leaves it queued. The foreground
runner must remain running on the operator's machine; GitHub hosts the individual
metadata/plan jobs. No startup service or production website deployment is implied. Neither preparation nor
marking a request approves processing. The manual `queue link-request` handoff
remains available. See [the submission design](../../docs/architecture/collection-submission-flow.md)
for data practices, scope semantics, and operational limits.

## Approved processing and publication

Run `./authoring/watchcraft-author queue run-portal-worker --operator-token-source keychain --r2-credentials-source keychain --r2-staging-credentials-source keychain` alongside the planner. Accept atomically queues processing. The worker advances through video processing, terminology, topic normalization, compilation, and preview publication using two-minute renewable claims. Failed stages require Retry; restarts resume expired claims. `--once` handles one stage, not a whole execution.

Previews are published to isolated `codex/portal-*` branches in `billbliss/watchcraft-collections`, with load URLs pinned to verified commits. The source checkout and main branch are not modified. Submit pull request queues a separate owner-authorized operation; retries reuse the existing PR. Changed preview branches fail closed. Completed historical runs without a workflow retain disabled publication controls. Assembly requires the plan to contain exactly the approved videos.

The foreground worker must remain running; this is not a startup service. No email notifications are sent.

### Local acquisition diagnostics

New YouTube acquisition failures write a bounded JSON log to
`authoring/diagnostics/<diagnostic-id>.log` and include that ID in the recorded
error. The log contains the canonical video URL, available execution/run/job
identifiers, yt-dlp version, exit status, timing, validation error, and sanitized
stdout/stderr excerpts. Each file is owner-readable only, ignored by Git, and
contains no downloaded media. Credential-bearing lines, URLs in tool output,
and common local paths are removed. Files older than 30 days are pruned when a
new failure is logged. Failure to save diagnostics preserves the original error
classification. Historical failures cannot be reconstructed; already-running
Python workers load this change only when restarted.
