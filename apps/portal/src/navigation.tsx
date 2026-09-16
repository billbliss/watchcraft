import { createRoot } from "react-dom/client";
import { authConfigured, PortalAuth } from "./auth";
import { ErrorBoundary } from "./ErrorBoundary";
import { PortalLink } from "./PortalLink";

const mount = document.querySelector("[data-portal-navigation]");
if (mount && authConfigured) {
  createRoot(mount).render(<ErrorBoundary quiet><PortalAuth><PortalLink /></PortalAuth></ErrorBoundary>);
}
