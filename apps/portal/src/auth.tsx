import { ClerkProvider, useAuth } from "@clerk/react";
import { ConvexReactClient } from "convex/react";
import { ConvexProviderWithClerk } from "convex/react-clerk";
import type { ReactNode } from "react";

const publishableKey = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY;
const convexUrl = import.meta.env.VITE_CONVEX_URL;
export const authConfigured = Boolean(publishableKey && convexUrl);
const convex = convexUrl ? new ConvexReactClient(convexUrl, { logger: false }) : null;

export function PortalAuth({ children, redirectPath = "/portal/" }: { children: ReactNode; redirectPath?: string }) {
  if (!authConfigured || !convex) return null;
  return (
    <ClerkProvider publishableKey={publishableKey} telemetry={false} afterSignOutUrl="/"
      signInFallbackRedirectUrl={redirectPath} signUpFallbackRedirectUrl={redirectPath}>
      <ConvexProviderWithClerk client={convex} useAuth={useAuth}>
        {children}
      </ConvexProviderWithClerk>
    </ClerkProvider>
  );
}
