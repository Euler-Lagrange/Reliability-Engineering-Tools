import type { ReactNode } from "react";
import { Component } from "react";

interface ErrorBoundaryProps {
  title: string;
  detail: string;
  onReset?: () => void;
  children: ReactNode;
}

interface ErrorBoundaryState {
  hasError: boolean;
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  public override state: ErrorBoundaryState = {
    hasError: false,
  };

  public static getDerivedStateFromError(): ErrorBoundaryState {
    return { hasError: true };
  }

  public override componentDidCatch(error: unknown) {
    console.error("Desktop shell boundary caught an error", error);
  }

  public override render() {
    if (this.state.hasError) {
      return (
        <section className="error-panel" role="alert">
          <div className="error-panel__body">
            <p className="eyebrow">Recovery</p>
            <h2>{this.props.title}</h2>
            <p className="section-card__description">{this.props.detail}</p>
          </div>
          {this.props.onReset ? (
            <button
              type="button"
              className="primary-button"
              onClick={() => {
                this.setState({ hasError: false });
                this.props.onReset?.();
              }}
            >
              Reload panel
            </button>
          ) : null}
        </section>
      );
    }

    return this.props.children;
  }
}
