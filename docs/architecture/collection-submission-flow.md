# Collection requests and processing proposals

Status: request intake and operator preparation bridge implemented locally.

A person can suggest a YouTube video, saved playlist URL/ID, or channel. They
choose a preferred scope, and the owner chooses what to plan before approving
any processing expense. A single video is a valid collection. Video URLs with
playlist context offer that playlist explicitly. Channel alternatives are up to
20 provider-ranked popular videos (only offered for a submitted video if it is
observed in that list) and the whole channel. The complete current video set is
resolved for the processing plan, not silently extended after approval.

## Visitor flow

`/submit/` provides link recognition, source metadata, scope choices, optional
sign-in, and a private status link. Public collection manifests are checked for
existing content; an existing collection can be opened directly. Repeated
requests for the same normalized source share one request, with separate status
receipts and scope preferences. No processing starts on submission.

“Add to Watchcraft” is available in the reader. YouTube links pasted into the
existing Settings import field are handed into the submission page. The existing
Watchcraft manifest import path continues to install collections directly.

Anonymous requests record canonical content identifiers, scope, metadata, and
workflow timestamps. They do not record a visitor name, email, IP address,
user-agent, analytics identifier, or browser fingerprint. Link normalization
removes tracking parameters. A receipt contains a hash of a random 256-bit status
token; the link carries the token in its fragment, not its HTTP path/query. Anyone
with that link can see the content and processing status, but not the submitter's
identity, other requests, operator details, or private artifact references.

Choosing account mode explicitly loads Clerk. Signed-in submissions additionally
record the verified account identifier and an available name/email claim for
history and operator attribution. Choosing anonymous submission does not attach
an existing account. Looking up a link does not create a request record.

Email notifications are deferred by user choice. The UI promises status tracking
and account history, not email delivery. Provider-side retention is separate from
these application practices; a public privacy policy must reflect verified Clerk,
Convex, hosting, and YouTube practices rather than claim that providers log nothing.
No final public privacy policy has been asserted by this implementation.

## Owner and operator flow

The portal distinguishes new requests from immutable processing proposals.
“Mark for planning” selects a scope and places the request in the operator inbox;
it does not approve a processing job or automatically launch a planner.

The existing authoring operator can:

1. Run `watchcraft-author queue request-inbox` to retrieve requests marked for
   planning, including selected scope and revision.
2. Run `watchcraft-author queue prepare-request REQUEST_ID --expected-revision
   REVISION` to resolve the selected scope, discover video metadata, import a
   frozen explicit-membership project, run the existing iterator and planner,
   and atomically create/link a pending execution. Operator and R2 reader
   credentials plus the existing GitHub authoring workers must be available.
3. The portal shows discovery, snapshot, estimate, and approval preparation
   progress. Failed/interrupted preparation offers Retry planning, which starts
   a new request revision. The manual `link-request` command remains available
   for plans prepared through the existing individual operator commands.
4. Review the exact selected video list, time/cost estimate, and source request
   attribution in the portal, then Accept or Reject the processing proposal.

Linking refuses stale requests and executions that are not pending approval. A
video-origin request must include the requested video; a single-video scope must
select exactly that video. Playlist/channel membership and complete coverage must
be established by the operator's normal snapshot/plan validation. The public
submission endpoints cannot approve work or supply trusted plans or estimates.

Request status follows the linked execution. Accept atomically queues a portal workflow. A separate `queue run-portal-worker`
consumer processes only accepted executions, then resolves terminology, normalizes
topics, compiles the collection, and publishes a verified, commit-pinned preview
to an isolated branch in watchcraft-collections. No pull request is opened until
the owner clicks Submit pull request. Failed stages require an explicit retry.
The worker requires operator, R2 reader/staging, and GitHub credentials; it must
remain running on the operator machine. Hosted workers execute individual jobs.
Partial selections require a matching reduced plan before collection assembly. `queue run-request-planner` consumes marked requests automatically while running.
The portal reports its connection from a 60-second heartbeat. Only one live
consumer can own a deployment's queue. Failed/interrupted requests require an
owner retry; a missing preparation stage is indexed so failed rows cannot hide
new work. The runner must target the same deployment as the portal. The preview build is now configured to use the hosted backend alongside the
existing hosted workers; the separate local database is not migrated. The command dispatches only metadata
iteration and planning jobs, never project execution or model processing.

Preparation stops if an anchor video no longer belongs to the chosen scope,
metadata cannot be retrieved, or membership exceeds the default 500-video limit
(configurable up to 5,000). It never silently truncates an entire-channel or
playlist request. Popular is the explicitly selected provider list, up to 20;
entire-channel membership uses the channel uploads playlist. Private/unavailable
videos can prevent preparation and require a scope decision. An operator lease
prevents simultaneous preparation; stale revisions cannot publish an approval
card. Estimates use the existing versioned pipeline estimation policy.

## Operational limits

Source discovery mirrors the existing anonymous YouTube discovery approach; it
uses public page metadata and explicit provider Popular controls, never labels a
Latest list as Popular when sort parameters are ignored. Metadata failures allow
basic video/playlist requests with a warning; unverified Popular scopes are not
offered. Current public matching scans at most 50 listed collection manifests on
approved collection hosts. A larger public directory should gain a content index.

Public intake has a global limit of 30 receipts per minute without recording
visitor identifiers. Status links are bearer capabilities; they should not be
included in support logs, analytics, or public pages. Keep email delivery,
retention/deletion policy, and production privacy text as explicit follow-up work.
