import { useEffect, useState } from "react";

import {
  fetchClaimedHours,
  fetchExploreCatalogue,
  type ClaimedHoursMeasure,
  type ClaimedHoursResponse,
  type DrilldownRow,
  type ExploreCatalogue,
  type FilterState,
  type PlanRequest,
} from "./api";
import { ResultView } from "./Explore";

interface ClaimedHoursByJobProps {
  filters: FilterState;
  /** Bumped when the Snapshot or as-of date changes. */
  generation: number;
  /** Bumped after every review save, which can add or remove the analyst-reviewed alternative. */
  reviewGeneration: number;
  onOpenTicket: (row: DrilldownRow, fingerprint: string, opener: HTMLElement) => void;
}

type Loaded = { data: ClaimedHoursResponse; filters: FilterState };

/**
 * Claimed hours by job (ticket #33): a fixed Explore plan run under the Overview filters, so its table,
 * source rows, CSV and "How this was calculated" are Explore's own. The reviewed alternative appears only
 * once a reviewer has linked replaced and kept tickets, beside the recorded figure.
 */
export function ClaimedHoursByJob({ filters, generation, reviewGeneration, onOpenTicket }: ClaimedHoursByJobProps) {
  const [measure, setMeasure] = useState<ClaimedHoursMeasure["id"]>("claimed_hours");
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [error, setError] = useState("");
  const [catalogue, setCatalogue] = useState<ExploreCatalogue | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetchExploreCatalogue(controller.signal)
      .then(setCatalogue)
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : String(reason));
      });
    return () => controller.abort();
  }, [generation]);

  useEffect(() => {
    const controller = new AbortController();
    fetchClaimedHours(filters, measure, controller.signal)
      .then((data) => {
        setLoaded({ data, filters });
        setError("");
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : String(reason));
      });
    return () => controller.abort();
  }, [filters, measure, generation, reviewGeneration]);

  if (error) {
    return (
      <p className="notice notice-error" role="alert">
        Claimed hours by job could not be loaded: {error}. Change the filters or reload the page.
      </p>
    );
  }
  if (!loaded || !catalogue) return <p className="status">Loading claimed hours by job…</p>;

  const { data } = loaded;
  // The same request the server ran, so drilldowns and downloads come from the same evaluation.
  const requestFor = (plan: ClaimedHoursResponse["request"]["plan"]): PlanRequest => ({
    plan,
    inherited: loaded.filters,
    snapshotFingerprint: data.snapshot_fingerprint,
  });

  return (
    <section className="priorities claimed-hours" aria-labelledby="claimed-hours-heading">
      <h3 id="claimed-hours-heading" tabIndex={-1}>
        {data.title}
      </h3>
      <p>{data.question}</p>
      <p className="muted">{data.note}</p>
      <fieldset className="flagged-filter">
        <legend>Measure</legend>
        {data.measures.map((option) => (
          <label key={option.id}>
            <input
              type="radio"
              name="claimed-hours-measure"
              value={option.id}
              checked={measure === option.id}
              onChange={() => setMeasure(option.id)}
            />
            {option.label}
          </label>
        ))}
      </fieldset>
      <section className="explore-result" aria-labelledby="claimed-hours-result-heading">
        <ResultView
          result={data.result}
          staleReason={null}
          catalogue={catalogue}
          request={requestFor(data.request.plan)}
          onRerun={() => undefined}
          onOpenTicket={onOpenTicket}
          idPrefix="claimed-hours"
        />
      </section>
      {data.reviewed ? (
        <section className="explore-result reviewed-alternative" aria-labelledby="claimed-hours-reviewed-result-heading">
          <p className="reviewed-label">
            <strong>{data.reviewed.label}</strong> · {data.reviewed.replaced_tickets}{" "}
            {data.reviewed.replaced_tickets === 1 ? "ticket" : "tickets"} linked as replaced. {data.reviewed.note}
          </p>
          <ResultView
            result={data.reviewed.result}
            staleReason={null}
            catalogue={catalogue}
            request={requestFor(data.reviewed.request.plan)}
            onRerun={() => undefined}
            onOpenTicket={onOpenTicket}
            idPrefix="claimed-hours-reviewed"
          />
        </section>
      ) : null}
    </section>
  );
}
