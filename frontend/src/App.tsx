import { useEffect, useRef, useState } from "react";

import {
  changeAsOf,
  fetchFilterOptions,
  fetchFlaggedDuplicates,
  fetchHeader,
  fetchProcessingQueue,
  fetchReviewPriorities,
  fetchTiles,
  NO_FILTERS,
  reimportWorkbook,
  type FilterOptions,
  type FilterState,
  type FlaggedDuplicatesResponse,
  type HeaderResponse,
  type ProcessingQueueResponse,
  type ReviewPrioritiesResponse,
  type TilesResponse,
} from "./api";
import { CompareTickets, type OpenPair } from "./CompareTickets";
import { EvidenceDrawer, type DrawerTarget } from "./EvidenceDrawer";
import { ActiveFilters, FilterBar } from "./FilterBar";
import { FlaggedDuplicates, type OpenFlagged } from "./FlaggedDuplicates";
import { HeaderTiles } from "./HeaderTiles";
import { ProcessingQueue, type OpenQueueTicket } from "./ProcessingQueue";
import { ReviewPriorities, type OpenEvidence } from "./ReviewPriorities";
import { SnapshotHeaderBar } from "./SnapshotHeaderBar";

type Tab = "overview" | "explore";

type LoadState =
  | { kind: "loading" }
  | { kind: "ready"; header: HeaderResponse }
  | { kind: "failed"; message: string };

export function App() {
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [tab, setTab] = useState<Tab>("overview");
  const [reimportStatus, setReimportStatus] = useState<string>("");
  const [reimporting, setReimporting] = useState(false);
  const [filters, setFilters] = useState<FilterState>(NO_FILTERS);
  const [options, setOptions] = useState<FilterOptions | null>(null);
  const [tiles, setTiles] = useState<TilesResponse | null>(null);
  const [tilesError, setTilesError] = useState("");
  const [priorities, setPriorities] = useState<ReviewPrioritiesResponse | null>(null);
  const [prioritiesError, setPrioritiesError] = useState("");
  const [flagged, setFlagged] = useState<FlaggedDuplicatesResponse | null>(null);
  const [flaggedError, setFlaggedError] = useState("");
  const [queue, setQueue] = useState<ProcessingQueueResponse | null>(null);
  const [queueError, setQueueError] = useState("");
  // Bumped whenever the Snapshot or as-of date changes, so every view refetches its numbers.
  const [generation, setGeneration] = useState(0);
  // Bumped after a review save so the ranked list shows the outcomes and the tiers a settled counterpart moves;
  // review never changes the other numbers.
  const [reviewGeneration, setReviewGeneration] = useState(0);
  const [drawer, setDrawer] = useState<DrawerTarget | null>(null);
  const drawerOpener = useRef<HTMLElement | null>(null);

  const openEvidence: OpenEvidence = (item, opener) => {
    if (!priorities) return;
    drawerOpener.current = opener;
    // Addressed by a member Ticket's Snapshot and Excel row; the display name is never a key (ADR 0004).
    setDrawer({
      kind: "possible_duplicate",
      fingerprint: priorities.snapshot_fingerprint,
      excelRow: item.members[0].excel_row,
      displayId: item.display_id,
    });
  };

  const openFlagged: OpenFlagged = (item, opener) => {
    if (!flagged) return;
    drawerOpener.current = opener;
    // Its possible duplicate when a rule links it, addressed by the flagged Ticket itself; otherwise the Ticket alone.
    setDrawer(
      item.possible_duplicate
        ? {
            kind: "possible_duplicate",
            fingerprint: flagged.snapshot_fingerprint,
            excelRow: item.excel_row,
            displayId: item.possible_duplicate.display_id,
          }
        : {
            kind: "ticket",
            fingerprint: flagged.snapshot_fingerprint,
            excelRow: item.excel_row,
            title: `Flagged duplicate ${item.ticket_number ?? `row ${item.excel_row}`}`,
          },
    );
  };

  const openQueueTicket: OpenQueueTicket = (ticket, population, fingerprint, opener) => {
    drawerOpener.current = opener;
    // The Ticket on its own, addressed by the Snapshot its bucket was listed from and its Excel row.
    setDrawer({
      kind: "ticket",
      fingerprint,
      excelRow: ticket.excel_row,
      title: `${population} ticket ${ticket.ticket_number ?? `row ${ticket.excel_row}`}`,
    });
  };

  const openPair: OpenPair = (rows, opener) => {
    if (state.kind !== "ready") return;
    drawerOpener.current = opener;
    setDrawer({ kind: "pair", fingerprint: state.header.snapshot_fingerprint, rows });
  };

  function closeEvidence() {
    setDrawer(null);
    // The list may have re-rendered while the drawer was open; fall back to its heading.
    const opener = drawerOpener.current;
    if (opener?.isConnected) opener.focus();
    else document.getElementById("priorities-heading")?.focus();
  }

  async function applyAsOf(date: string) {
    const provenance = await changeAsOf(date);
    setState((current) => (current.kind === "ready" ? { kind: "ready", header: { ...current.header, ...provenance } } : current));
    setGeneration((value) => value + 1);
  }

  async function reimport() {
    setReimporting(true);
    setReimportStatus("Reading the workbook again…");
    try {
      const result = await reimportWorkbook();
      setState({ kind: "ready", header: result });
      setGeneration((value) => value + 1);
      setReimportStatus(
        result.imported
          ? `The workbook has changed. It is now Snapshot ${result.snapshot.fingerprint.slice(0, 12)}; the previous Snapshot is unchanged.`
          : "The workbook is unchanged, so the Snapshot stays the same.",
      );
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : String(error);
      setReimportStatus(`The workbook was not reimported and the current Snapshot stays active: ${message}`);
    } finally {
      setReimporting(false);
    }
  }

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

  useEffect(() => {
    const controller = new AbortController();
    fetchFilterOptions(controller.signal)
      .then(setOptions)
      .catch(() => {
        // the bar still offers Clear; the tiles report any failure
      });
    return () => controller.abort();
  }, [generation]);

  useEffect(() => {
    const controller = new AbortController();
    fetchTiles(filters, controller.signal)
      .then((data) => {
        setTiles(data);
        setTilesError("");
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setTilesError(error instanceof Error ? error.message : String(error));
      });
    return () => controller.abort();
  }, [filters, generation]);

  useEffect(() => {
    const controller = new AbortController();
    fetchReviewPriorities(filters, controller.signal)
      .then((data) => {
        setPriorities(data);
        setPrioritiesError("");
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setPrioritiesError(error instanceof Error ? error.message : String(error));
      });
    return () => controller.abort();
  }, [filters, generation, reviewGeneration]);

  useEffect(() => {
    const controller = new AbortController();
    fetchFlaggedDuplicates(filters, controller.signal)
      .then((data) => {
        setFlagged(data);
        setFlaggedError("");
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setFlaggedError(error instanceof Error ? error.message : String(error));
      });
    return () => controller.abort();
  }, [filters, generation, reviewGeneration]);

  useEffect(() => {
    const controller = new AbortController();
    fetchProcessingQueue(filters, controller.signal)
      .then((data) => {
        setQueue(data);
        setQueueError("");
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setQueueError(error instanceof Error ? error.message : String(error));
      });
    return () => controller.abort();
  }, [filters, generation]);

  return (
    <div className="app">
      <header className="masthead">
        <div className="brand">
          <span className="brand-name">Labour Tickets</span>
          <span className="brand-sub">Analytics for one export, every number traceable to its source cells</span>
        </div>
        {state.kind === "ready" ? (
          <div className="snapshot-controls">
            <SnapshotHeaderBar header={state.header} onAsOfChange={applyAsOf} />
            <button type="button" className="reimport" onClick={reimport} disabled={reimporting}>
              Reimport
            </button>
            <p className="status" role="status">
              {reimportStatus}
            </p>
          </div>
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

      <FilterBar options={options} filters={filters} onChange={setFilters} />
      <ActiveFilters filters={tiles?.filters ?? null} grain={tiles?.grain ?? "Ticket"} />
      {tilesError ? (
        <p className="notice notice-error" role="alert">
          The filters could not be applied: {tilesError}. Change them or choose Clear.
        </p>
      ) : null}

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
            {tiles ? <HeaderTiles data={tiles} /> : <p className="status">Loading the tiles…</p>}
            {prioritiesError ? (
              <p className="notice notice-error" role="alert">
                The review priorities could not be loaded: {prioritiesError}. Change the filters or reload the page.
              </p>
            ) : priorities ? (
              <ReviewPriorities data={priorities} onOpen={openEvidence} />
            ) : (
              <p className="status">Loading the review priorities…</p>
            )}
            {flaggedError ? (
              <p className="notice notice-error" role="alert">
                The flagged duplicates could not be loaded: {flaggedError}. Change the filters or reload the page.
              </p>
            ) : flagged ? (
              <FlaggedDuplicates data={flagged} onOpen={openFlagged} />
            ) : (
              <p className="status">Loading the flagged duplicates…</p>
            )}
            {queueError ? (
              <p className="notice notice-error" role="alert">
                The processing queue could not be loaded: {queueError}. Change the filters or reload the page.
              </p>
            ) : queue ? (
              <ProcessingQueue data={queue} filters={filters} onOpen={openQueueTicket} />
            ) : (
              <p className="status">Loading the processing queue…</p>
            )}
            {state.kind === "ready" ? <CompareTickets rowCount={state.header.snapshot.row_count} onCompare={openPair} /> : null}
            <p className="placeholder">The data readiness view arrives with a later ticket.</p>
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
      <EvidenceDrawer
        target={drawer}
        filters={filters}
        onClose={closeEvidence}
        onReviewChange={() => setReviewGeneration((value) => value + 1)}
      />
    </div>
  );
}
