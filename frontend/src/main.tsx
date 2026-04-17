import React from "react";
import ReactDOM from "react-dom/client";
import { App } from "./app/App";
import { ErrorBoundary } from "./shared/errors/ErrorBoundary";
import { installGlobalErrorHandlers } from "./shared/errors/installGlobalErrorHandlers";
import "./theme/styles.css";

// Install BEFORE React mounts so any error during the first render of
// lazily-loaded chunks or async effects is surfaced as a toast rather
// than a silent devtools-only log.
installGlobalErrorHandlers();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    {/*
      Root ErrorBoundary: last line of defense. Feature-level boundaries
      exist inside each tool, but if a bug escapes them (e.g. in the app
      shell, theme, or command palette), React 19 would unmount the whole
      tree. This boundary keeps the window alive with a reload option so
      the user doesn't see a blank webview.
    */}
    <ErrorBoundary
      title="Desktop shell crashed"
      detail="The application hit an unexpected error and has been stopped. Reload to recover; if this persists, copy the error details and send them to support."
    >
      <App />
    </ErrorBoundary>
  </React.StrictMode>,
);
