import {
  httpRouter,
} from "convex/server";

import { sha256Hex } from "../packages/authoring-pipeline/src/contracts.ts";
import { internal } from "./_generated/api";
import { httpAction } from "./_generated/server";

const http = httpRouter();

function authorized(request: Request): boolean {
  const authorization = request.headers.get("authorization");
  const token = authorization?.startsWith("Bearer ") ? authorization.slice(7) : "";
  const expected = process.env.AUTHORING_WORKER_TOKEN_SHA256;
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

function mutationRoute(functionReference: any) {
  return httpAction(async (ctx, request) => {
    if (!authorized(request)) return jsonResponse({ error: "Unauthorized." }, 401);
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

http.route({ path: "/authoring/smoke/prepare", method: "POST", handler: mutationRoute(internal.authoringInternal.prepareSmokeJob) });
http.route({ path: "/authoring/jobs/claim", method: "POST", handler: mutationRoute(internal.authoringInternal.claimJob) });
http.route({ path: "/authoring/jobs/start", method: "POST", handler: mutationRoute(internal.authoringInternal.startJob) });
http.route({ path: "/authoring/jobs/heartbeat", method: "POST", handler: mutationRoute(internal.authoringInternal.heartbeatJob) });
http.route({ path: "/authoring/jobs/succeed", method: "POST", handler: mutationRoute(internal.authoringInternal.succeedJob) });
http.route({ path: "/authoring/jobs/fail", method: "POST", handler: mutationRoute(internal.authoringInternal.failJob) });

export default http;
