import { afterEach, expect, test, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { useConvexAuth, useQuery } from "convex/react";
import { PortalLink } from "./PortalLink";

vi.mock("convex/react", () => ({ useConvexAuth: vi.fn(), useQuery: vi.fn() }));
afterEach(() => vi.resetAllMocks());

test("the menu stays empty while signed out or verifying the session", () => {
  vi.mocked(useConvexAuth).mockReturnValue({ isAuthenticated: false, isLoading: true, isRefreshing: false });
  vi.mocked(useQuery).mockReturnValue(undefined);
  expect(renderToStaticMarkup(<PortalLink />)).toBe("");
  expect(vi.mocked(useQuery).mock.calls[0][1]).toBe("skip");
});

test("signing in alone does not show the link", () => {
  vi.mocked(useConvexAuth).mockReturnValue({ isAuthenticated: true, isLoading: false, isRefreshing: false });
  for (const result of [undefined, { authorized: false }]) {
    vi.mocked(useQuery).mockReturnValue(result);
    expect(renderToStaticMarkup(<PortalLink />)).toBe("");
  }
});

test("an authorized session shows the portal link", () => {
  vi.mocked(useConvexAuth).mockReturnValue({ isAuthenticated: true, isLoading: false, isRefreshing: false });
  vi.mocked(useQuery).mockReturnValue({ authorized: true });
  expect(renderToStaticMarkup(<PortalLink />)).toBe('<a href="/portal/">Portal</a>');
});

test("sign-out hides the link even if the prior query result remains cached", () => {
  vi.mocked(useConvexAuth).mockReturnValue({ isAuthenticated: false, isLoading: false, isRefreshing: false });
  vi.mocked(useQuery).mockReturnValue({ authorized: true });
  expect(renderToStaticMarkup(<PortalLink />)).toBe("");
});
