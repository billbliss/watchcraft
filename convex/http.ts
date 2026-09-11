import {
  httpRouter,
} from "convex/server";

import { sha256Hex } from "../packages/authoring-pipeline/src/contracts.ts";
import { internal } from "./_generated/api";
import { httpAction } from "./_generated/server";

const http = httpRouter();

function authorized(request: Request, verifierName: string): boolean {
  const authorization = request.headers.get("authorization");
  const token = authorization?.startsWith("Bearer ") ? authorization.slice(7) : "";
  const expected = process.env[verifierName];
  if (!token || !expected || !/^[a-f0-9]{64}$/.test(expected)) return false;
  const actual = sha256Hex(token);
  if (actual.length !== expected.length) return false;
  let difference = 0;
  for (let index = 0; index < actual.length; index += 1) {
    difference |= actual.charCodeAt(index) ^ expected.charCodeAt(index);
  }
  return difference === 0;
}

function jsonResponse(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function mutationRoute(functionReference: any, verifierName: string) {
  return httpAction(async (ctx, request) => {
    if (!authorized(request, verifierName)) return jsonResponse({ error: "Unauthorized." }, 401);
    try {
      const args = await request.json();
      const result = await ctx.runMutation(functionReference, args);
      return jsonResponse(result);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Authoring request failed.";
      return jsonResponse({ error: message.slice(0, 500) }, 409);
    }
  });
}

function queryRoute(functionReference: any, verifierName: string) {
  return httpAction(async (ctx, request) => {
    if (!authorized(request, verifierName)) return jsonResponse({ error: "Unauthorized." }, 401);
    try {
      const args = await request.json();
      const result = await ctx.runQuery(functionReference, args);
      return jsonResponse(result);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Authoring request failed.";
      return jsonResponse({ error: message.slice(0, 500) }, 409);
    }
  });
}

const workerVerifier = "AUTHORING_WORKER_TOKEN_SHA256";
const operatorVerifier = "AUTHORING_OPERATOR_TOKEN_SHA256";
const registryAdminVerifier = "AUTHORING_REGISTRY_ADMIN_TOKEN_SHA256";

http.route({ path: "/authoring/smoke/prepare", method: "POST", handler: mutationRoute(internal.authoringInternal.prepareSmokeJob, workerVerifier) });
http.route({ path: "/authoring/jobs/dispatch/record", method: "POST", handler: mutationRoute(internal.authoringInternal.recordDispatch, workerVerifier) });
http.route({ path: "/authoring/jobs/get", method: "POST", handler: queryRoute(internal.authoringInternal.getSubmission, workerVerifier) });
http.route({ path: "/authoring/jobs/claim", method: "POST", handler: mutationRoute(internal.authoringInternal.claimJob, workerVerifier) });
http.route({ path: "/authoring/jobs/start", method: "POST", handler: mutationRoute(internal.authoringInternal.startJob, workerVerifier) });
http.route({ path: "/authoring/jobs/heartbeat", method: "POST", handler: mutationRoute(internal.authoringInternal.heartbeatJob, workerVerifier) });
http.route({ path: "/authoring/jobs/succeed", method: "POST", handler: mutationRoute(internal.authoringInternal.succeedJob, workerVerifier) });
http.route({ path: "/authoring/jobs/fail", method: "POST", handler: mutationRoute(internal.authoringInternal.failJob, workerVerifier) });

http.route({ path: "/authoring/operator/submissions/get", method: "POST", handler: queryRoute(internal.authoringInternal.getSubmission, operatorVerifier) });
http.route({ path: "/authoring/operator/submissions/submit", method: "POST", handler: mutationRoute(internal.authoringInternal.submitJob, operatorVerifier) });
http.route({ path: "/authoring/operator/pipelines/submit", method: "POST", handler: mutationRoute(internal.authoringInternal.submitPipeline, operatorVerifier) });
http.route({ path: "/authoring/operator/pipelines/approve", method: "POST", handler: mutationRoute(internal.authoringInternal.approvePipeline, operatorVerifier) });
http.route({ path: "/authoring/operator/pipelines/get", method: "POST", handler: queryRoute(internal.authoringInternal.getPipeline, operatorVerifier) });
http.route({ path: "/authoring/operator/submissions/approve", method: "POST", handler: mutationRoute(internal.authoringInternal.approveSubmission, operatorVerifier) });
http.route({ path: "/authoring/operator/submissions/request-dispatch", method: "POST", handler: mutationRoute(internal.authoringInternal.requestDispatch, operatorVerifier) });
http.route({ path: "/authoring/operator/submissions/cancel", method: "POST", handler: mutationRoute(internal.authoringInternal.cancelJob, operatorVerifier) });
http.route({ path: "/authoring/operator/submissions/retry", method: "POST", handler: mutationRoute(internal.authoringInternal.retryJob, operatorVerifier) });
http.route({ path: "/authoring/operator/registry/get-active", method: "POST", handler: queryRoute(internal.authoringRegistry.getActiveRegistry, operatorVerifier) });
http.route({ path: "/authoring/operator/projects/get", method: "POST", handler: queryRoute(internal.authoringInternal.getCatalogProject, operatorVerifier) });
http.route({ path: "/authoring/operator/projects/history", method: "POST", handler: queryRoute(internal.authoringInternal.getCatalogProjectHistory, operatorVerifier) });
http.route({ path: "/authoring/operator/projects/import", method: "POST", handler: mutationRoute(internal.authoringInternal.importCatalogProject, operatorVerifier) });
http.route({ path: "/authoring/operator/projects/accept-snapshot", method: "POST", handler: mutationRoute(internal.authoringInternal.acceptCatalogProjectSnapshot, operatorVerifier) });
http.route({ path: "/authoring/operator/project-executions/get", method: "POST", handler: queryRoute(internal.authoringInternal.getProjectExecution, operatorVerifier) });
http.route({ path: "/authoring/operator/project-executions/list", method: "POST", handler: queryRoute(internal.authoringInternal.listProjectExecutions, operatorVerifier) });
http.route({ path: "/authoring/operator/project-executions/create", method: "POST", handler: mutationRoute(internal.authoringInternal.createProjectExecutionRecord, operatorVerifier) });
http.route({ path: "/authoring/operator/project-executions/approve", method: "POST", handler: mutationRoute(internal.authoringInternal.approveProjectExecution, operatorVerifier) });
http.route({ path: "/authoring/operator/project-executions/items/claim", method: "POST", handler: mutationRoute(internal.authoringInternal.claimProjectExecutionItem, operatorVerifier) });
http.route({ path: "/authoring/operator/project-executions/items/complete", method: "POST", handler: mutationRoute(internal.authoringInternal.completeProjectExecutionItem, operatorVerifier) });
http.route({ path: "/authoring/operator/project-executions/items/fail", method: "POST", handler: mutationRoute(internal.authoringInternal.failProjectExecutionItem, operatorVerifier) });
http.route({ path: "/authoring/operator/project-executions/cancel", method: "POST", handler: mutationRoute(internal.authoringInternal.cancelProjectExecution, operatorVerifier) });

http.route({ path: "/authoring/admin/registry/get-active", method: "POST", handler: queryRoute(internal.authoringRegistry.getActiveRegistry, registryAdminVerifier) });
http.route({ path: "/authoring/admin/registry/publish", method: "POST", handler: mutationRoute(internal.authoringRegistry.publishRegistry, registryAdminVerifier) });
http.route({ path: "/authoring/admin/registry/activate", method: "POST", handler: mutationRoute(internal.authoringRegistry.activateRegistry, registryAdminVerifier) });
http.route({ path: "/authoring/admin/cleanup/list", method: "POST", handler: queryRoute(internal.authoringCleanup.listRuns, registryAdminVerifier) });
http.route({ path: "/authoring/admin/cleanup/purge-run", method: "POST", handler: mutationRoute(internal.authoringCleanup.purgeRun, registryAdminVerifier) });
http.route({ path: "/authoring/admin/cleanup/purge-orphan-job", method: "POST", handler: mutationRoute(internal.authoringCleanup.purgeOrphanJob, registryAdminVerifier) });

export default http;
