import { Component, type ReactNode } from "react";

export class ErrorBoundary extends Component<
  { children: ReactNode; quiet?: boolean }, { failed: boolean }
> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() {
    if (!this.state.failed) return this.props.children;
    if (this.props.quiet) return null;
    return <section className="notice" role="alert">
      <h2>Unable to open the portal</h2>
      <p>Your connection or access may have changed. Reload to try again.</p>
      <button onClick={() => window.location.reload()}>Reload</button>
      <a href="/">Back to Watchcraft</a>
    </section>;
  }
}
