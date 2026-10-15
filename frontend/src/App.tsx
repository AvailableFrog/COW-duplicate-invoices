import { useEffect, useRef, useState } from "react";

import {
  changeAsOf,
  DEFAULT_REPORTING_WINDOW,
  fetchDataReadiness,
  fetchFilterOptions,
  fetchFlaggedDuplicates,
  fetchHeader,
  fetchProcessingQueue,
  fetchReviewPriorities,
  fetchTiles,
  fetchValueContext,
  NO_FILTERS,
  NO_PATTERN_FILTER,
  reimportWorkbook,
  type DataReadinessResponse,
  type DrilldownRow,
  type FilterOptions,
  type FilterState,
  type FlaggedDuplicatesResponse,
  type PatternFilterState,
  type HeaderResponse,
  type ProcessingQueueResponse,
  type ReportingWindowState,
  type ReviewPrioritiesResponse,
  type TilesResponse,
  type ValueContextResponse,
} from "./api";
import { CompareTickets, type OpenPair } from "./CompareTickets";
import { DataReadiness, type OpenReadinessAlias, type OpenReadinessTicket } from "./DataReadiness";
import { EvidenceDrawer, type DrawerTarget } from "./EvidenceDrawer";
import { Explore } from "./Explore";
import { ActiveFilters, FilterBar } from "./FilterBar";
import { FlaggedDuplicates, type OpenFlagged } from "./FlaggedDuplicates";
import { HeaderTiles } from "./HeaderTiles";
import { ProcessingQueue, type OpenQueueTicket } from "./ProcessingQueue";
import { ReviewPriorities, type OpenEvidence } from "./ReviewPriorities";
import { SnapshotHeaderBar } from "./SnapshotHeaderBar";
import { ValueContext } from "./ValueContext";

type Tab = "overview" | "explore";

type LoadState =
  | { kind: "loading" }
  | { kind: "ready"; header: HeaderResponse }
  | { kind: "failed"; message: string };

/** The first state a reviewer sees; it says what to do if loading never finishes. */
const LOADING_HEADER =
  "Loading the Snapshot header… If it has not appeared within a few seconds, check the terminal where the service is running.";

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
  // The multi-label pattern filter narrows only the ranked list; the matrix and every other view ignore it.
  const [patternFilter, setPatternFilter] = useState<PatternFilterState>(NO_PATTERN_FILTER);
  const [prioritiesError, setPrioritiesError] = useState("");
  const [flagged, setFlagged] = useState<FlaggedDuplicatesResponse | null>(null);
  const [flaggedError, setFlaggedError] = useState("");
  const [queue, setQueue] = useState<ProcessingQueueResponse | null>(null);
  const [queueError, setQueueError] = useState("");
  const [readiness, setReadiness] = useState<DataReadinessResponse | null>(null);
  const [readinessError, setReadinessError] = useState("");
  // The data readiness view's reporting window; a null end follows the default, the years Created covers.
  const [reportingWindow, setReportingWindow] = useState<ReportingWindowState>(DEFAULT_REPORTING_WINDOW);
  const [value, setValue] = useState<ValueContextResponse | null>(null);
  const [valueError, setValueError] = useState("");
  // Bumped whenever the Snapshot or as-of date changes, so every view refetches its numbers.
  const [generation, setGeneration] = useState(0);
  // Bumped after a review save so the ranked list shows the outcomes and the tiers a settled counterpart moves, and
  // the value panel offers or withdraws its analyst-reviewed alternative; review never changes the other numbers.
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

  const openReadinessTicket: OpenReadinessTicket = (row, fingerprint, opener) => {
    drawerOpener.current = opener;
    setDrawer({ kind: "ticket", fingerprint, excelRow: row.excel_row, title: `Ticket ${row.ticket_number ?? `row ${row.excel_row}`}` });
  };

  const openReadinessAlias: OpenReadinessAlias = (row, fingerprint, opener) => {
    drawerOpener.current = opener;
    // The proposal is decided in the possible duplicate of its proposing tickets, addressed by one of them.
    setDrawer(
      row.possible_duplicate
        ? { kind: "possible_duplicate", fingerprint, excelRow: row.excel_row, displayId: row.possible_duplicate }
        : { kind: "ticket", fingerprint, excelRow: row.excel_row, title: `Ticket row ${row.excel_row}` },
    );
  };

  const openExploreTicket = (row: DrilldownRow, fingerprint: string, opener: HTMLElement) => {
    drawerOpener.current = opener;
    setDrawer({ kind: "ticket", fingerprint, excelRow: row.excel_row, title: `Ticket ${row.ticket_number ?? `row ${row.excel_row}`}` });
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
      setReimportStatus(
        `The workbook was not reimported and the current Snapshot stays active: ${message}. ` +
          "Correct the workbook at the path the service was launched with, then choose Reimport again.",
      );
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
    fetchReviewPriorities(filters, patternFilter, controller.signal)
      .then((data) => {
        setPriorities(data);
        setPrioritiesError("");
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setPrioritiesError(error instanceof Error ? error.message : String(error));
      });
    return () => controller.abort();
  }, [filters, patternFilter, generation, reviewGeneration]);

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

  useEffect(() => {
    const controller = new AbortController();
    fetchDataReadiness(filters, reportingWindow, controller.signal)
      .then((data) => {
        setReadiness(data);
        setReadinessError("");
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setReadinessError(error instanceof Error ? error.message : String(error));
      });
    return () => controller.abort();
    // A confirmed or rejected Alias drops out of the unresolved name proposals.
  }, [filters, reportingWindow, generation, reviewGeneration]);

  useEffect(() => {
    const controller = new AbortController();
    fetchValueContext(filters, controller.signal)
      .then((data) => {
        setValue(data);
        setValueError("");
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setValueError(error instanceof Error ? error.message : String(error));
      });
    return () => controller.abort();
  }, [filters, generation, reviewGeneration]);

  return (
    <div className="app">
      <header className="masthead">
        <div className="brand">
          <h1 className="brand-name">Labour Tickets</h1>
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
            {state.kind === "loading" ? LOADING_HEADER : null}
          </p>
        )}
      </header>

      <nav aria-label="Primary">
        <div className="tabs" role="tablist" aria-label="Views">
          <button type="button" role="tab" aria-selected={tab === "overview"} onClick={() => setTab("overview")}>
            Overview
          </button>
          <button type="button" role="tab" aria-selected={tab === "explore"} onClick={() => setTab("explore")}>
            Explore
          </button>
        </div>
      </nav>

      {tab === "overview" ? (
        <>
          <FilterBar options={options} filters={filters} onChange={setFilters} />
          <ActiveFilters filters={tiles?.filters ?? null} grain={tiles?.grain ?? "Ticket"} />
          {tilesError ? (
            <p className="notice notice-error" role="alert">
              The filters could not be applied: {tilesError}. Change them or choose Clear.
            </p>
          ) : null}
        </>
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
              <ReviewPriorities
                data={priorities}
                onOpen={openEvidence}
                patternFilter={patternFilter}
                onPatternFilterChange={setPatternFilter}
              />
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
            {readinessError ? (
              <p className="notice notice-error" role="alert">
                The data readiness counts could not be loaded: {readinessError}. Change the filters or the reporting
                window, or reload the page.
              </p>
            ) : readiness ? (
              <DataReadiness
                data={readiness}
                filters={filters}
                reportingWindow={reportingWindow}
                onWindowChange={setReportingWindow}
                onOpenTicket={openReadinessTicket}
                onOpenAlias={openReadinessAlias}
              />
            ) : (
              <p className="status">Loading the data readiness counts…</p>
            )}
            {valueError ? (
              <p className="notice notice-error" role="alert">
                The value context could not be loaded: {valueError}. Change the filters or reload the page.
              </p>
            ) : value ? (
              <ValueContext data={value} />
            ) : (
              <p className="status">Loading the value context…</p>
            )}
          </section>
        ) : state.kind !== "ready" ? (
          <p className="status">{LOADING_HEADER}</p>
        ) : null}
        {/* Kept mounted while the Overview shows, so the starting choice and chips survive a tab switch. */}
        {state.kind === "ready" ? (
          <div hidden={tab !== "explore"}>
            <Explore
              header={state.header}
              overviewFilters={filters}
              reviewGeneration={reviewGeneration}
              onOpenTicket={openExploreTicket}
            />
          </div>
        ) : null}
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
