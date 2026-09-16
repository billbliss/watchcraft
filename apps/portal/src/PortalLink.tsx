import { useConvexAuth, useQuery } from "convex/react";
import { api } from "../../../convex/_generated/api";

export function PortalLink() {
  const { isAuthenticated } = useConvexAuth();
  const access = useQuery(api.portal.access, isAuthenticated ? {} : "skip");
  return isAuthenticated && access?.authorized ? <a href="/portal/">Portal</a> : null;
}
