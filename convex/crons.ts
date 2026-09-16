import { cronJobs } from "convex/server";

import { internal } from "./_generated/api";

const crons = cronJobs();

crons.interval(
  "recover expired authoring leases",
  { minutes: 1 },
  internal.authoringInternal.reconcileExpiredLeases,
  {},
);

crons.interval("refresh collection pull requests", { minutes: 5 }, internal.portalWorkflows.syncPullRequests, {});

export default crons;
