import { SignIn, UserButton, useAuth } from "@clerk/react";
import { useConvexAuth, useQuery } from "convex/react";
import { api } from "../../../convex/_generated/api";
import { authConfigured, PortalAuth } from "./auth";
import { ErrorBoundary } from "./ErrorBoundary";
import { ReviewQueue } from "./ReviewQueue";

function PortalContent() {
  const clerk = useAuth();
  const convex = useConvexAuth();
  const access = useQuery(api.portal.access, convex.isAuthenticated ? {} : "skip");
  if (!clerk.isLoaded) return <p className="notice" role="status">Loading sign-in…</p>;
  if (!clerk.isSignedIn) return <div className="sign-in"><SignIn routing="hash" /></div>;
  if (convex.isLoading) return <p className="notice" role="status">Checking access…</p>;
  if (!convex.isAuthenticated) return <section className="notice" role="alert">
    <h2>Unable to verify your sign-in</h2><p>Please reload to try again. If this continues, the portal’s sign-in connection needs attention.</p>
    <button onClick={() => window.location.reload()}>Reload</button><UserButton />
  </section>;
  if (!access) return <p className="notice" role="status">Checking access…</p>;
  if (!access.authorized) return <section className="notice">
    <h2>This account doesn’t have portal access</h2>
    <p>Use the Watchcraft owner account to continue.</p><UserButton />
  </section>;
  return <><div className="account"><span>Collection authoring workspace</span><UserButton /></div><ReviewQueue /></>;
}

export default function App() {
  return <div className="shell portal-shell">
    <header className="header"><a className="brand" href="/">Watchcraft</a><a href="/">Back to website ↗</a></header>
    <main><div className="page-heading"><p className="eyebrow">Watchcraft</p><h1>Collection Authoring</h1></div>
      <ErrorBoundary>{authConfigured ? <PortalAuth><PortalContent /></PortalAuth> : <section className="notice">
        <h2>Portal setup is in progress</h2><p>Sign-in isn’t available yet. Please check back shortly.</p>
      </section>}</ErrorBoundary>
    </main>
  </div>;
}
