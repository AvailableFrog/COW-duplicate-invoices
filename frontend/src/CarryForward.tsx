import { useEffect, useId, useState } from "react";

import {
  answerCarryForward,
  fetchCarryForward,
  type CarryForwardResponse,
  type CarryProposal,
  type CarryRecord,
} from "./api";
import { rememberedReviewer, rememberReviewer } from "./ReviewPanel";

interface CarryForwardProps {
  fingerprint: string;
  /** Bumped when the Snapshot or review data changes, so the proposals are read again. */
  refresh: number;
  /** Called after a proposal is carried, so every view shows the review data now saved on this Snapshot. */
  onChanged: () => void;
}

function message(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/** "2026-10-14T09:12:00Z" as "2026-10-14 09:12 UTC". */
function when(recordedAt: string): string {
  return recordedAt.replace("T", " ").replace(/:\d\dZ$/, " UTC");
}

function shown(value: string | number | boolean | null): string {
  if (value === null || value === "") return "(blank)";
  return String(value);
}

/** What a proposal or record is about, in a reviewer's words. */
function describe(kind: CarryProposal["kind"], subject: (string | null)[], proposal?: CarryProposal): string {
  const [first, second] = subject.map((item) => item ?? "no ticket number");
  if (kind === "outcome") {
    const outcome = proposal?.decision.value.outcome?.label;
    return `${outcome ? `“${outcome}” on ` : "Outcome on "}${first} and ${second}`;
  }
  if (kind === "link") return `${first} replaced, ${second} kept`;
  const decision = proposal?.decision.value.decision?.label;
  const names = proposal?.names?.join(" and ") ?? `“${first}” and “${second}”`;
  return `${decision ? `Alias ${decision.toLowerCase()} for ` : "Alias for "}${names}`;
}

/**
 * Earlier review decisions (ticket #40): the outcomes, kept/replaced links and Alias decisions saved on an earlier
 * export, proposed for this one. Nothing is carried until a reviewer chooses to; a proposal whose tickets changed
 * shows what changed and is carried only once the reviewer confirms the decision still holds.
 */
export function CarryForward({ fingerprint, refresh, onChanged }: CarryForwardProps) {
  const [data, setData] = useState<CarryForwardResponse | null>(null);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [reviewer, setReviewer] = useState(rememberedReviewer);
  const reviewerId = useId();

  useEffect(() => {
    const controller = new AbortController();
    fetchCarryForward(fingerprint, controller.signal)
      .then((response) => {
        setData(response);
        setError("");
      })
      .catch((failure: unknown) => {
        if (!controller.signal.aborted) setError(message(failure));
      });
    return () => controller.abort();
  }, [fingerprint, refresh]);

  if (error) {
    return (
      <p className="notice notice-error" role="alert">
        The earlier review decisions could not be loaded: {error}. Reload the page to try again.
      </p>
    );
  }
  if (!data || data.proposals.length + data.carried.length + data.declined.length === 0) return null;

  async function respond(proposal: CarryProposal, action: "carry" | "decline", rationale: string, revalidated: boolean) {
    const label = reviewer.trim();
    if (!label) {
      document.getElementById(reviewerId)?.focus();
      setStatus("Enter your reviewer label first.");
      return false;
    }
    try {
      const response = await answerCarryForward(fingerprint, { id: proposal.id, action, reviewer: label, rationale, revalidated });
      setData(response);
      const what = describe(proposal.kind, proposal.subject, proposal);
      setStatus(action === "carry" ? `Carried forward: ${what}.` : `Not carried: ${what}.`);
      if (action === "carry") onChanged();
      return true;
    } catch (failure: unknown) {
      setStatus(`Nothing was saved: ${message(failure)}.`);
      return false;
    }
  }

  const waiting = data.proposals.length;
  return (
    <section className="carry-forward" aria-labelledby="carry-forward-heading">
      <h3 id="carry-forward-heading">
        Earlier review decisions{waiting ? ` (${waiting} to answer)` : ""}
      </h3>
      <p className="muted">{data.note}</p>
      {waiting ? (
        <div className="reviewer-field">
          <label htmlFor={reviewerId}>Reviewer</label>
          <input
            id={reviewerId}
            type="text"
            value={reviewer}
            maxLength={80}
            autoComplete="name"
            onChange={(event) => {
              setReviewer(event.target.value);
              rememberReviewer(event.target.value);
            }}
          />
        </div>
      ) : null}
      <p className="status" role="status">
        {status}
      </p>
      {waiting ? (
        <ul className="view-list" aria-label="Proposed decisions">
          {data.proposals.map((proposal) => (
            <ProposalItem key={proposal.id} proposal={proposal} onRespond={respond} />
          ))}
        </ul>
      ) : (
        <p className="muted">Every earlier decision has been answered for this export.</p>
      )}
      {data.carried.length + data.declined.length ? (
        <details>
          <summary>Already answered ({data.carried.length + data.declined.length})</summary>
          <ul className="view-list" aria-label="Answered decisions">
            {[...data.carried, ...data.declined].map((record) => (
              <AnsweredItem key={`${record.kind}:${record.subject.join("|")}`} record={record} />
            ))}
          </ul>
        </details>
      ) : null}
    </section>
  );
}

interface ProposalItemProps {
  proposal: CarryProposal;
  onRespond: (proposal: CarryProposal, action: "carry" | "decline", rationale: string, revalidated: boolean) => Promise<boolean>;
}

function ProposalItem({ proposal, onRespond }: ProposalItemProps) {
  const [rationale, setRationale] = useState("");
  const [revalidated, setRevalidated] = useState(false);
  const [busy, setBusy] = useState(false);
  const id = useId();
  const title = describe(proposal.kind, proposal.subject, proposal);
  const { decision } = proposal;

  async function act(action: "carry" | "decline") {
    setBusy(true);
    await onRespond(proposal, action, rationale, revalidated);
    setBusy(false);
  }

  return (
    <li aria-labelledby={`${id}-title`}>
      <p>
        <strong id={`${id}-title`}>
          {proposal.kind_label}: {title}
        </strong>{" "}
        <span className="tag">{proposal.status_label}</span>
      </p>
      <p className="muted">
        Saved by {decision.reviewer} at {when(decision.recorded_at)} on Snapshot{" "}
        <code>{proposal.source.snapshot_fingerprint.slice(0, 12)}</code>
        {decision.rationale ? ` — “${decision.rationale}”` : ""}
        {decision.value.note ? ` Note: ${decision.value.note}` : ""}
      </p>
      {proposal.reason ? <p>{proposal.reason}</p> : null}
      {proposal.differences.length ? (
        <div className="table-scroll" role="region" aria-label={`What changed for ${title}`} tabIndex={0}>
          <table className="evidence-table">
            <thead>
              <tr>
                <th scope="col">Ticket</th>
                <th scope="col">Field</th>
                <th scope="col">Earlier export</th>
                <th scope="col">This export</th>
              </tr>
            </thead>
            <tbody>
              {proposal.differences.map((difference) => (
                <tr key={`${difference.ticket_number}:${difference.field}`}>
                  <td>{difference.ticket_number}</td>
                  <th scope="row">{difference.field}</th>
                  <td className="cell-text">{shown(difference.before)}</td>
                  <td className="cell-text">{shown(difference.after)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      {proposal.status !== "cannot_carry" && proposal.needs_revalidation ? (
        <label className="checkbox">
          <input type="checkbox" checked={revalidated} onChange={(event) => setRevalidated(event.target.checked)} />
          I have checked {proposal.differences.length ? "what changed" : "these tickets"} and the decision still holds
        </label>
      ) : null}
      <label className="carry-reason">
        Reason{proposal.needs_revalidation && proposal.status !== "cannot_carry" ? " (needed to carry it)" : " (optional)"}
        <textarea value={rationale} maxLength={1000} rows={2} onChange={(event) => setRationale(event.target.value)} />
      </label>
      <div className="form-actions">
        {proposal.status !== "cannot_carry" ? (
          <button
            type="button"
            className="secondary"
            disabled={busy || (proposal.needs_revalidation && (!revalidated || !rationale.trim()))}
            onClick={() => act("carry")}
          >
            Carry forward
          </button>
        ) : null}
        <button type="button" className="secondary" disabled={busy} onClick={() => act("decline")}>
          Don't carry
        </button>
      </div>
    </li>
  );
}

function AnsweredItem({ record }: { record: CarryRecord }) {
  return (
    <li>
      <p>
        {record.kind === "outcome" ? "Review outcome" : record.kind === "link" ? "Kept/replaced link" : "Alias decision"}:{" "}
        {describe(record.kind, record.subject)}{" "}
        <span className="tag">{record.action === "accepted" ? (record.revalidated ? "carried after revalidating" : "carried") : "not carried"}</span>
      </p>
      <p className="muted">
        By {record.reviewer} at {when(record.recorded_at)}
        {record.rationale ? ` — “${record.rationale}”` : ""}
      </p>
    </li>
  );
}
