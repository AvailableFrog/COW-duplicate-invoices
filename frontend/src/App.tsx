import { useEffect, useState } from "react";

import { fetchHeader, type HeaderResponse } from "./api";
import { SnapshotHeaderBar } from "./SnapshotHeaderBar";

type Tab = "overview" | "explore";

type LoadState =
  | { kind: "loading" }
  | { kind: "ready"; header: HeaderResponse }
  | { kind: "failed"; message: string };

export function App() {
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [tab, setTab] = useState<Tab>("overview");

  useEffect(() => {
    const controller = new AbortController();
    fetchHeader(controller.signal)
      .then((header) => setState({ kind: "ready", header }))
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setState({ kind: "failed", message: error instanceof Error ? error.message : String(error) });
      });
    return () => controller.abort();
  }, []);

  return (
    <div className="app">
      <header className="masthead">
        <div className="brand">
          <span className="brand-name">Labour Tickets</span>
          <span className="brand-sub">Analytics for one export, every number traceable to its source cells</span>
        </div>
        {state.kind === "ready" ? (
          <SnapshotHeaderBar header={state.header} />
        ) : (
          <p className="status" role="status">
            {state.kind === "loading" ? "Loading the Snapshot header…" : null}
          </p>
        )}
      </header>

      <nav className="tabs" aria-label="Primary">
        <button type="button" role="tab" aria-selected={tab === "overview"} onClick={() => setTab("overview")}>
          Overview
        </button>
        <button type="button" role="tab" aria-selected={tab === "explore"} onClick={() => setTab("explore")}>
          Explore
        </button>
      </nav>

      <main className="content">
        {state.kind === "failed" ? (
          <section className="notice notice-error" role="alert">
            <h2>The Snapshot header could not be loaded</h2>
            <p>{state.message}</p>
            <p>
              Check that the service is still running in the terminal where you launched it, then reload this page.
              If it has stopped, launch it again with the workbook path.
            </p>
          </section>
        ) : tab === "overview" ? (
          <section aria-labelledby="overview-heading">
            <h2 id="overview-heading">Overview</h2>
            <p className="placeholder">
              The header above identifies the Snapshot. The review priorities, Recorded Markers, processing queue and
              data readiness views arrive with later tickets.
            </p>
          </section>
        ) : (
          <section aria-labelledby="explore-heading">
            <h2 id="explore-heading">Explore</h2>
            <p className="placeholder">
              Chart building from metric, grouping, filter, date-basis and chart chips arrives with a later ticket.
              There is no prompt field in release one.
            </p>
          </section>
        )}
      </main>
    </div>
  );
}
