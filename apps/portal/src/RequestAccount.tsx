import { SignInButton, UserButton, useAuth } from "@clerk/react";
import { useConvexAuth } from "convex/react";
import type { ReactNode } from "react";
import { PortalAuth } from "./auth";
function Account({ children }: { children: (signedIn: boolean) => ReactNode }) {
  const clerk = useAuth(); const convex = useConvexAuth();
  return <><div className="request-account">{clerk.isSignedIn ? <><span>{convex.isAuthenticated ? "Your requests will appear in your account." : "Connecting your account…"}</span><UserButton /></> : <><span>Sign in to save your request history.</span><SignInButton mode="modal"><button className="request-secondary">Sign in</button></SignInButton></>}</div>
    {clerk.isSignedIn && !convex.isAuthenticated ? <p role="status">{convex.isLoading ? "Checking sign-in…" : "We couldn't connect your account. Retry or continue without signing in."}</p> : children(Boolean(convex.isAuthenticated))}</>;
}
export default function RequestAccount({ children, returnTo }: { children: (signedIn: boolean) => ReactNode; returnTo: string }) {
  return <PortalAuth redirectPath={returnTo}><Account>{children}</Account></PortalAuth>;
}
