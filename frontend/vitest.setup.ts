import "@testing-library/jest-dom/vitest";
import { configure } from "@testing-library/react";

// Under heavy machine load (parallel cargo/PyInstaller builds, AV scans) the
// full 41-file suite's collect phase balloons (~62s -> ~220s aggregate) and
// each Vitest fork is CPU-starved. Several tests render the App shell, whose
// tools are `React.lazy`; a `findBy*`/`waitFor` that gates on first use of a
// tool then has to transform+evaluate that lazy chunk while the CPU is
// contended. The COLD chunk import was measured at 434-693ms under a moderate
// 16-thread load (climbing run-over-run), and field load is heavier — enough
// to push it past Testing Library's 1000ms DEFAULT asyncUtilTimeout. When it
// does, findBy rejects with "Unable to find role ..." — the reported
// App.keepalive/RefDes/FailureRate flake. That is an RTL async-util timeout,
// NOT a Vitest testTimeout (which was the 5000ms default, and never fired
// first), so the binding constraint is asyncUtilTimeout — raising testTimeout
// alone could not fix it. We raise the per-wait budget to 5000ms (~7x the
// worst observed cold load) so a starved lazy import has headroom. It stays
// strictly below the 15000ms testTimeout (see vite.config.ts) so RTL still
// wins the race and reports the helpful "Unable to find ..." message on a
// genuine failure, and a truly stuck query is still bounded by testTimeout.
// This standardises the 3000ms local override FmeaTool.test.tsx already used.
configure({ asyncUtilTimeout: 5000 });

if (!window.matchMedia) {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    }),
  });
}

if (!HTMLElement.prototype.hasPointerCapture) {
  HTMLElement.prototype.hasPointerCapture = () => false;
}

if (!HTMLElement.prototype.setPointerCapture) {
  HTMLElement.prototype.setPointerCapture = () => {};
}

if (!HTMLElement.prototype.releasePointerCapture) {
  HTMLElement.prototype.releasePointerCapture = () => {};
}

if (!HTMLElement.prototype.scrollIntoView) {
  HTMLElement.prototype.scrollIntoView = () => {};
}
