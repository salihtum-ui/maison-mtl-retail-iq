import { Component, type ErrorInfo, type ReactNode } from 'react';

export class AppErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state: { error: Error | null } = { error: null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('MTL Retail IQ rendering failed', error, info.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return <main className="startup-error">
      <h1>MTL Retail IQ</h1>
      <p role="alert">The application could not display this view. {this.state.error.message}</p>
      <p>Reload the application. If the problem continues, share this error with the workspace administrator.</p>
      <button className="button primary" onClick={() => window.location.reload()}>Reload application</button>
    </main>;
  }
}
