import { type FormEvent, useEffect, useState } from "react";

import {
  deleteView,
  fetchViews,
  filtersFromWire,
  inheritedFilters,
  renameView,
  saveView,
  type FilterState,
  type SavedView,
} from "./api";
import type { ExploreState } from "./Explore";

interface SavedViewsProps {
  tab: "overview" | "explore";
  filters: FilterState;
  exploreState: ExploreState | null;
  /** Bumped when the Snapshot, as-of date or review data changes, so each view's differences are read again. */
  refresh: number;
  onOpenOverview: (filters: FilterState) => void;
  onOpenExplore: (state: ExploreState) => void;
}

const dateFormat = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric" });

/**
 * Saved views (ticket #39): save the Overview filters or the Explore chart under a name, and reopen it later.
 * A view saved under another Snapshot, as-of date, version or set of Aliases says what changed and opens
 * only when asked, so it never silently shows different numbers.
 */
export function SavedViews({ tab, filters, exploreState, refresh, onOpenOverview, onOpenExplore }: SavedViewsProps) {
  const [views, setViews] = useState<SavedView[]>([]);
  const [name, setName] = useState("");
  const [status, setStatus] = useState("");
  const [confirming, setConfirming] = useState<{ id: number; action: "open" | "delete" } | null>(null);
  const [renaming, setRenaming] = useState<{ id: number; name: string } | null>(null);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    fetchViews(controller.signal)
      .then(setViews)
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setStatus(`The saved views could not be loaded: ${error instanceof Error ? error.message : String(error)}.`);
      });
    return () => controller.abort();
  }, [refresh, reload]);

  const canSave = tab === "overview" || exploreState !== null;
  const what = tab === "overview" ? "the Overview filters" : "the Explore chart";

  async function save(event: FormEvent) {
    event.preventDefault();
    try {
      const state =
        tab === "overview"
          ? { filters: inheritedFilters(filters) }
          : { plan: exploreState!.plan, inherited: exploreState!.inherited ? inheritedFilters(exploreState!.inherited) : null };
      const view = await saveView(name, tab, state);
      setName("");
      setStatus(`Saved ${what} as "${view.name}".`);
      setReload((value) => value + 1);
    } catch (error: unknown) {
      setStatus(`The view was not saved: ${error instanceof Error ? error.message : String(error)}.`);
    }
  }

  function open(view: SavedView) {
    setConfirming(null);
    if ("filters" in view.state) onOpenOverview(filtersFromWire(view.state.filters));
    else onOpenExplore({ plan: view.state.plan, inherited: view.state.inherited ? filtersFromWire(view.state.inherited) : null });
    setStatus(`Opened "${view.name}".`);
  }

  async function rename(event: FormEvent) {
    event.preventDefault();
    if (!renaming) return;
    try {
      const view = await renameView(renaming.id, renaming.name);
      setRenaming(null);
      setStatus(`Renamed to "${view.name}".`);
      setReload((value) => value + 1);
    } catch (error: unknown) {
      setStatus(`The view was not renamed: ${error instanceof Error ? error.message : String(error)}.`);
    }
  }

  async function remove(view: SavedView) {
    try {
      await deleteView(view.id);
      setConfirming(null);
      setStatus(`Deleted "${view.name}".`);
      setReload((value) => value + 1);
    } catch (error: unknown) {
      setStatus(`The view was not deleted: ${error instanceof Error ? error.message : String(error)}.`);
    }
  }

  return (
    <section className="saved-views" aria-labelledby="saved-views-heading">
      <details>
        <summary>
          <span id="saved-views-heading">Saved views ({views.length})</span>
        </summary>
        <form className="save-view" aria-label="Save this view" onSubmit={save}>
          <label>
            Name
            <input value={name} maxLength={120} onChange={(event) => setName(event.target.value)} />
          </label>
          <button type="submit" className="secondary" disabled={!canSave || !name.trim()}>
            Save {what}
          </button>
          {!canSave ? <span className="muted">Choose how to start on the Explore tab first.</span> : null}
        </form>
        <p className="status" role="status">
          {status}
        </p>
        {views.length ? (
          <ul className="view-list" aria-label="Saved views">
            {views.map((view) => (
              <li key={view.id}>
                <p>
                  <strong>{view.name}</strong>{" "}
                  <span className="muted">
                    {view.kind === "overview" ? "Overview filters" : "Explore chart"} · saved{" "}
                    {dateFormat.format(new Date(view.created_at))}
                  </span>{" "}
                  <span className="tag">{view.current ? "current" : "changed since saved"}</span>
                </p>
                {renaming?.id === view.id ? (
                  <form className="save-view" aria-label={`Rename ${view.name}`} onSubmit={rename}>
                    <label>
                      New name
                      <input
                        value={renaming.name}
                        maxLength={120}
                        onChange={(event) => setRenaming({ id: view.id, name: event.target.value })}
                      />
                    </label>
                    <button type="submit" className="secondary">
                      Save name
                    </button>
                    <button type="button" className="secondary" onClick={() => setRenaming(null)}>
                      Cancel
                    </button>
                  </form>
                ) : (
                  <div className="form-actions">
                    <button
                      type="button"
                      className="secondary"
                      onClick={() => (view.current ? open(view) : setConfirming({ id: view.id, action: "open" }))}
                    >
                      Open {view.name}
                    </button>
                    <button type="button" className="secondary" onClick={() => setRenaming({ id: view.id, name: view.name })}>
                      Rename
                    </button>
                    <button type="button" className="secondary" onClick={() => setConfirming({ id: view.id, action: "delete" })}>
                      Delete
                    </button>
                  </div>
                )}
                {confirming?.id === view.id && confirming.action === "open" ? (
                  <div className="notice" role="alert">
                    <p>This view was saved under different conditions, so its numbers may differ from when it was saved:</p>
                    <ul>
                      {view.differences.map((difference) => (
                        <li key={difference.field}>{difference.message}</li>
                      ))}
                    </ul>
                    <div className="form-actions">
                      <button type="button" className="secondary" onClick={() => open(view)}>
                        Open anyway
                      </button>
                      <button type="button" className="secondary" onClick={() => setConfirming(null)}>
                        Cancel
                      </button>
                    </div>
                  </div>
                ) : null}
                {confirming?.id === view.id && confirming.action === "delete" ? (
                  <div className="notice" role="alert">
                    <p>Delete "{view.name}"? This cannot be undone.</p>
                    <div className="form-actions">
                      <button type="button" className="secondary" onClick={() => remove(view)}>
                        Delete it
                      </button>
                      <button type="button" className="secondary" onClick={() => setConfirming(null)}>
                        Keep it
                      </button>
                    </div>
                  </div>
                ) : null}
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted">No saved views yet.</p>
        )}
      </details>
    </section>
  );
}
