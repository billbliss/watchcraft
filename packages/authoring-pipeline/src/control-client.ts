import type { ArtifactReference, AuthoringJob } from "./contracts.ts";

export interface SmokeJobPreparation {
  job_id: string;
  spec_sha256: string;
  dispatch_generation: number;
  revision: number;
}

export interface ClaimRequest {
  job_id: string;
  command_id: string;
  expected_revision: number;
  attempt_id: string;
  owner: string;
  spec_sha256: string;
  dispatch_generation: number;
  lease_duration_ms: number;
  github_run_id?: string;
}

export interface FailureReport {
  classification: string;
  message: string;
  retryable: boolean;
}

export interface AuthoringControlPlane {
  prepareSmokeJob(input: {
    job_id: string;
    run_id: string;
    command_prefix: string;
    github_run_id: string;
    github_run_url: string;
  }): Promise<SmokeJobPreparation>;
  claimJob(input: ClaimRequest): Promise<AuthoringJob>;
  startJob(input: {
    job_id: string;
    command_id: string;
    expected_revision: number;
    attempt_id: string;
  }): Promise<AuthoringJob>;
  heartbeatJob(input: {
    job_id: string;
    command_id: string;
    expected_revision: number;
    attempt_id: string;
    lease_duration_ms: number;
  }): Promise<AuthoringJob>;
  succeedJob(input: {
    job_id: string;
    command_id: string;
    expected_revision: number;
    attempt_id: string;
    artifact: ArtifactReference;
  }): Promise<AuthoringJob>;
  failJob(input: {
    job_id: string;
    command_id: string;
    expected_revision: number;
    attempt_id: string;
    failure: FailureReport;
  }): Promise<AuthoringJob>;
}

export function convexHttpUrl(deploymentUrl: string): string {
  const parsed = new URL(deploymentUrl);
  if (parsed.protocol !== "https:" || !parsed.hostname.endsWith(".convex.cloud")) {
    throw new TypeError("WATCHCRAFT_CONVEX_URL must be an https://*.convex.cloud deployment URL.");
  }
  parsed.hostname = parsed.hostname.replace(/\.convex\.cloud$/, ".convex.site");
  parsed.pathname = "";
  return parsed.toString().replace(/\/$/, "");
}

export class ConvexAuthoringControlClient implements AuthoringControlPlane {
  readonly httpUrl: string;
  readonly workerToken: string;
  readonly fetchImplementation: typeof fetch;

  constructor(
    deploymentUrl: string,
    workerToken: string,
    fetchImplementation: typeof fetch = fetch,
  ) {
    if (!workerToken) throw new TypeError("Authoring worker token is required.");
    this.httpUrl = convexHttpUrl(deploymentUrl);
    this.workerToken = workerToken;
    this.fetchImplementation = fetchImplementation;
  }

  private async post<T>(path: string, value: unknown): Promise<T> {
    const response = await this.fetchImplementation(`${this.httpUrl}${path}`, {
      method: "POST",
      headers: {
        authorization: `Bearer ${this.workerToken}`,
        "content-type": "application/json",
      },
      body: JSON.stringify(value),
    });
    const payload = await response.json().catch(() => null) as { error?: unknown } | null;
    if (!response.ok) {
      const message = payload && typeof payload.error === "string"
        ? payload.error
        : `Authoring control request failed with HTTP ${response.status}.`;
      throw new Error(message);
    }
    return payload as T;
  }

  prepareSmokeJob(input: Parameters<AuthoringControlPlane["prepareSmokeJob"]>[0]) {
    return this.post<SmokeJobPreparation>("/authoring/smoke/prepare", input);
  }

  claimJob(input: ClaimRequest) {
    return this.post<AuthoringJob>("/authoring/jobs/claim", input);
  }

  startJob(input: Parameters<AuthoringControlPlane["startJob"]>[0]) {
    return this.post<AuthoringJob>("/authoring/jobs/start", input);
  }

  heartbeatJob(input: Parameters<AuthoringControlPlane["heartbeatJob"]>[0]) {
    return this.post<AuthoringJob>("/authoring/jobs/heartbeat", input);
  }

  succeedJob(input: Parameters<AuthoringControlPlane["succeedJob"]>[0]) {
    return this.post<AuthoringJob>("/authoring/jobs/succeed", input);
  }

  failJob(input: Parameters<AuthoringControlPlane["failJob"]>[0]) {
    return this.post<AuthoringJob>("/authoring/jobs/fail", input);
  }
}

export function controlClientFromEnvironment(environment = process.env): ConvexAuthoringControlClient {
  const deploymentUrl = environment.WATCHCRAFT_CONVEX_URL;
  const workerToken = environment.WATCHCRAFT_AUTHORING_WORKER_TOKEN;
  if (!deploymentUrl || !workerToken) {
    throw new Error("WATCHCRAFT_CONVEX_URL and WATCHCRAFT_AUTHORING_WORKER_TOKEN are required.");
  }
  return new ConvexAuthoringControlClient(deploymentUrl, workerToken);
}
