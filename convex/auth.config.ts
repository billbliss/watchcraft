import type { AuthConfig } from "convex/server";

// Machine-to-machine authoring endpoints retain their independent credentials.
// Deployments without portal configuration accept no browser identities.
const issuer = process.env.CLERK_JWT_ISSUER_DOMAIN;
export default {
  providers: issuer ? [{ domain: issuer, applicationID: "convex" }] : [],
} satisfies AuthConfig;
