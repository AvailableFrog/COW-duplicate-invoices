import { useId, useState, type FormEvent } from "react";

import {
  linkReplacement,
  saveAlias,
  saveOutcome,
  unlinkReplacement,
  type AliasHistoryValue,
  type AliasProposal,
  type EvidenceMember,
  type HistoryEntry,
  type LinkHistoryValue,
  type OutcomeHistoryValue,
  type OutcomeId,
  type OutcomeValue,
  type PairOutcome,
  type PossibleDuplicateReview,
  type ReplacementLink,
  type RerunCandidate,
} from "./api";

const REVIEWER_KEY = "lta.reviewer";

/** The reviewer label this browser last used; storage may be unavailable, so failure means "none". */
function rememberedReviewer(): string {
  try {
    return window.localStorage.getItem(REVIEWER_KEY) ?? "";
  } catch {
    return "";
  }
}

function rememberReviewer(label: string): void {
  try {
    window.localStorage.setItem(REVIEWER_KEY, label);
  } catch {
    // remembering is a convenience only
  }
}

/** "2026-10-14T09:12:00Z" as "2026-10-14 09:12 UTC". */
function when(recordedAt: string): string {
  return recordedAt.replace("T", " ").replace(/:\d\dZ$/, " UTC");
}

/** A ticket as the review controls name it: its ticket number and Excel row. */
function ticketLabel(ticketNumber: string | null, row: number): string {
  return `${ticketNumber ?? "No ticket number"} (row ${row})`;
}

function message(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

interface ReviewPanelProps {
  fingerprint: string;
  members: EvidenceMember[];
  review: PossibleDuplicateReview;
  /** Called after any save so the drawer and the list show the stored state. */
  onChanged: () => void;
}

/**
 * Local review controls for one possible duplicate: a decision on each proposed Alias, an outcome per Ticket pair,
 * kept/replaced links and history.
 */
export function ReviewPanel({ fingerprint, members, review, onChanged }: ReviewPanelProps) {
  const [reviewer, setReviewer] = useState(rememberedReviewer);
  const reviewerId = useId();
  const label = (row: number) => ticketLabel(members.find((item) => item.excel_row === row)?.ticket_number ?? null, row);

  function changeReviewer(value: string) {
    setReviewer(value);
    rememberReviewer(value);
  }

  /** The trimmed reviewer label, or null after moving focus to the empty field. */
  function requireReviewer(): string | null {
    const trimmed = reviewer.trim();
    if (!trimmed) document.getElementById(reviewerId)?.focus();
    return trimmed || null;
  }

  return (
    <section aria-labelledby="drawer-review" className="review-panel">
      <h3 id="drawer-review">Review outcome</h3>
      <p className="muted">
        Your judgement is kept in this app only, beside this Snapshot; nothing is written to the workbook or the
        company's system. An outcome or a note changes no figure. Only a kept/replaced link can, in an adjusted figure
        that is always labelled as one.
      </p>
      <div className="reviewer-field">
        <label htmlFor={reviewerId}>Reviewer</label>
        <input
          id={reviewerId}
          type="text"
          value={reviewer}
          maxLength={80}
          autoComplete="name"
          aria-describedby={`${reviewerId}-hint`}
          onChange={(event) => changeReviewer(event.target.value)}
        />
        <span id={`${reviewerId}-hint`} className="muted">
          Recorded with every save and remembered in this browser. There are no accounts.
        </span>
      </div>

      {review.aliases.map((alias) => (
        <AliasDecisionForm
          key={alias.labels.join("|")}
          fingerprint={fingerprint}
          alias={alias}
          requireReviewer={requireReviewer}
          onSaved={onChanged}
        />
      ))}

      {review.pairs.map((pair) => (
        <PairOutcomeForm
          key={pair.excel_rows.join("-")}
          fingerprint={fingerprint}
          pair={pair}
          values={review.outcome_values}
          title={`${ticketLabel(pair.ticket_numbers[0], pair.excel_rows[0])} and ${ticketLabel(pair.ticket_numbers[1], pair.excel_rows[1])}`}
          requireReviewer={requireReviewer}
          onSaved={onChanged}
        />
      ))}

      <ReplacementLinks
        fingerprint={fingerprint}
        members={members}
        links={review.links}
        label={label}
        requireReviewer={requireReviewer}
        onChanged={onChanged}
      />

      <ReviewHistory history={review.history} />
    </section>
  );
}

/** "“Mario Collymore” and “Mariocollymore”": the names as written on the tickets. */
function aliasNames(names: string[]): string {
  const quoted = names.map((name) => `“${name}”`);
  return quoted.length > 1 ? `${quoted.slice(0, -1).join(", ")} and ${quoted[quoted.length - 1]}` : quoted.join("");
}

function rerunText(candidates: RerunCandidate[]): string {
  return candidates
    .map((candidate) => `${candidate.rule_label} between rows ${candidate.excel_rows[0]} and ${candidate.excel_rows[1]}`)
    .join("; ");
}

interface AliasDecisionFormProps {
  fingerprint: string;
  alias: AliasProposal;
  requireReviewer: () => string | null;
  onSaved: () => void;
}

/** Confirm or reject a proposed Alias, always with a reason; a change runs the matching rules again. */
function AliasDecisionForm({ fingerprint, alias, requireReviewer, onSaved }: AliasDecisionFormProps) {
  const id = useId();
  const [rationale, setRationale] = useState("");
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState<{ kind: "saved" | "error"; text: string } | null>(null);
  const rows = alias.proposed_by.map(([first, second]) => `rows ${first} and ${second}`).join("; ");

  async function decide(decision: "confirmed" | "rejected") {
    const reviewer = requireReviewer();
    if (!reviewer) {
      setStatus({ kind: "error", text: "Enter your reviewer label above before deciding." });
      return;
    }
    setSaving(true);
    try {
      const saved = await saveAlias(fingerprint, { labels: alias.labels, decision, reviewer, rationale });
      setRationale("");
      if (!saved.changed) {
        setStatus({ kind: "saved", text: `Nothing changed; the Alias stays ${saved.decision.label}.` });
      } else {
        const { added, removed } = saved.rerun;
        const effect = [
          added.length > 0 ? `added ${rerunText(added)}` : "",
          removed.length > 0 ? `removed ${rerunText(removed)}` : "",
        ].filter(Boolean);
        setStatus({
          kind: "saved",
          text: `Saved: ${saved.decision.label}. The matching rules ran again and ${effect.length > 0 ? effect.join(", and ") : "found the same links as before"}.`,
        });
      }
      onSaved();
    } catch (error: unknown) {
      setStatus({ kind: "error", text: `Not saved: ${message(error)}.` });
    } finally {
      setSaving(false);
    }
  }

  return (
    <form
      className="pair-outcome alias-decision"
      aria-labelledby={`${id}-title`}
      onSubmit={(event) => event.preventDefault()}
    >
      <h4 id={`${id}-title`}>Proposed Alias: {aliasNames(alias.names)}</h4>
      <p className="pair-current">
        Decision: <strong>{alias.decision.label}</strong>
        {alias.saved ? (
          <span className="muted">
            {" "}
            by {alias.reviewer}, {when(alias.recorded_at ?? "")}
          </span>
        ) : (
          <span className="muted"> (no decision yet; the two labels stay separate)</span>
        )}
      </p>
      <p className="muted">
        The Name-space variant found the same claim under both names ({rows}): they are equal once spaces and case are
        ignored. Confirm only if you know both labels name one person; the Work-period conflict rule then compares their
        tickets as one employee on every date. Rejecting removes what confirming added. A shared email is never a reason,
        and the employee-label count always counts both labels.
      </p>
      <div className="review-fields">
        <label>
          Reason for this decision (required)
          <input type="text" value={rationale} maxLength={1000} onChange={(event) => setRationale(event.target.value)} />
        </label>
      </div>
      <div className="form-actions">
        <button type="button" className="primary" disabled={saving} onClick={() => void decide("confirmed")}>
          Confirm Alias
        </button>
        <button type="button" className="secondary" disabled={saving} onClick={() => void decide("rejected")}>
          Reject Alias
        </button>
        <p className={status?.kind === "error" ? "form-status unresolved" : "form-status"} role="status">
          {status?.text}
        </p>
      </div>
    </form>
  );
}

interface PairOutcomeFormProps {
  fingerprint: string;
  pair: PairOutcome;
  values: OutcomeValue[];
  title: string;
  requireReviewer: () => string | null;
  onSaved: () => void;
}

function PairOutcomeForm({ fingerprint, pair, values, title, requireReviewer, onSaved }: PairOutcomeFormProps) {
  const id = useId();
  const [outcome, setOutcome] = useState<OutcomeId>(pair.outcome.id);
  const [note, setNote] = useState(pair.note);
  const [reference, setReference] = useState(pair.reference);
  const [rationale, setRationale] = useState("");
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState<{ kind: "saved" | "error"; text: string } | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const reviewer = requireReviewer();
    if (!reviewer) {
      setStatus({ kind: "error", text: "Enter your reviewer label above before saving." });
      return;
    }
    setSaving(true);
    try {
      const saved = await saveOutcome(fingerprint, pair.excel_rows, { outcome, note, reference, reviewer, rationale });
      setRationale("");
      setStatus({
        kind: "saved",
        text: saved.changed ? `Saved: ${saved.outcome.label}.` : `Nothing changed; the outcome stays ${saved.outcome.label}.`,
      });
      onSaved();
    } catch (error: unknown) {
      setStatus({ kind: "error", text: `Not saved: ${message(error)}.` });
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className="pair-outcome" onSubmit={submit} aria-labelledby={`${id}-title`}>
      <h4 id={`${id}-title`}>{title}</h4>
      <p className="pair-current">
        {pair.saved ? (
          <>
            Saved outcome: <strong>{pair.outcome.label}</strong>
            <span className="muted">
              {" "}
              by {pair.reviewer}, {when(pair.recorded_at ?? "")}
            </span>
          </>
        ) : (
          <>
            Saved outcome: <strong>Not reviewed</strong> <span className="muted">(nothing saved yet)</span>
          </>
        )}
      </p>
      <fieldset className="outcome-choices">
        <legend>Outcome</legend>
        {values.map((value) => (
          <label key={value.id} className="outcome-choice">
            <input
              type="radio"
              name={`${id}-outcome`}
              value={value.id}
              checked={outcome === value.id}
              onChange={() => setOutcome(value.id)}
            />
            <span>
              <span className="outcome-label">{value.label}</span>
              <span className="muted outcome-definition">{value.definition}</span>
            </span>
          </label>
        ))}
      </fieldset>
      <div className="review-fields">
        <label>
          Note
          <textarea value={note} maxLength={4000} rows={2} onChange={(event) => setNote(event.target.value)} />
        </label>
        <label>
          Supporting reference
          <input
            type="text"
            value={reference}
            maxLength={500}
            placeholder="For example an email, a payroll run or a document"
            onChange={(event) => setReference(event.target.value)}
          />
        </label>
        <label>
          Reason for this change{pair.saved ? " (required to change a saved outcome)" : " (optional)"}
          <input type="text" value={rationale} maxLength={1000} onChange={(event) => setRationale(event.target.value)} />
        </label>
      </div>
      <div className="form-actions">
        <button type="submit" disabled={saving}>
          Save outcome
        </button>
        <p className={status?.kind === "error" ? "form-status unresolved" : "form-status"} role="status">
          {status?.text}
        </p>
      </div>
      {outcome === "replacement_ticket" ? (
        <p className="muted">Link the kept and replaced tickets below; the outcome alone links nothing.</p>
      ) : null}
    </form>
  );
}

interface ReplacementLinksProps {
  fingerprint: string;
  members: EvidenceMember[];
  links: ReplacementLink[];
  label: (row: number) => string;
  requireReviewer: () => string | null;
  onChanged: () => void;
}

function ReplacementLinks({ fingerprint, members, links, label, requireReviewer, onChanged }: ReplacementLinksProps) {
  const id = useId();
  const [replaced, setReplaced] = useState<number>(members[members.length - 1].excel_row);
  const [kept, setKept] = useState<number[]>([]);
  const [rationale, setRationale] = useState("");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<{ kind: "saved" | "error"; text: string } | null>(null);
  const linked = new Set(links.filter((link) => link.replaced_row === replaced).map((link) => link.retained_row));
  const reversed = new Set(links.filter((link) => link.retained_row === replaced).map((link) => link.replaced_row));

  async function run(action: () => Promise<string>) {
    const reviewer = requireReviewer();
    if (!reviewer) {
      setStatus({ kind: "error", text: "Enter your reviewer label above first." });
      return;
    }
    setBusy(true);
    try {
      setStatus({ kind: "saved", text: await action() });
      setRationale("");
    } catch (error: unknown) {
      setStatus({ kind: "error", text: `Not saved: ${message(error)}.` });
    } finally {
      setBusy(false);
      // Refresh even after a failure: an earlier link in the same batch may already be saved.
      onChanged();
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    const rows = kept.filter((row) => row !== replaced && !linked.has(row));
    if (rows.length === 0) {
      setStatus({ kind: "error", text: "Choose at least one kept ticket that is not linked yet." });
      return;
    }
    void run(async () => {
      const reviewer = requireReviewer() ?? "";
      for (const row of rows) await linkReplacement(fingerprint, replaced, row, { reviewer, rationale });
      setKept([]);
      return `Linked: ${label(replaced)} replaced, kept ${rows.map(label).join(" and ")}.`;
    });
  }

  function remove(link: ReplacementLink) {
    void run(async () => {
      const reviewer = requireReviewer() ?? "";
      await unlinkReplacement(fingerprint, link.replaced_row, link.retained_row, { reviewer, rationale });
      return `Removed the link between ${label(link.replaced_row)} and ${label(link.retained_row)}.`;
    });
  }

  return (
    <div className="replacement-links">
      <h4 id={`${id}-title`}>Kept and replaced tickets</h4>
      <p className="muted">
        Link a replaced ticket to every ticket kept in its place; there can be more than one. Only these links can take
        a ticket out of an adjusted figure.
      </p>
      {links.length === 0 ? (
        <p className="muted">No tickets are linked.</p>
      ) : (
        <ul className="link-list" aria-labelledby={`${id}-title`}>
          {links.map((link) => (
            <li key={`${link.replaced_row}-${link.retained_row}`}>
              <span>
                <strong>{ticketLabel(link.replaced_ticket_number, link.replaced_row)}</strong> replaced,{" "}
                <strong>{ticketLabel(link.retained_ticket_number, link.retained_row)}</strong> kept
                <span className="muted">
                  {" "}
                  · {link.reviewer}, {when(link.recorded_at)}
                  {link.rationale ? ` · ${link.rationale}` : ""}
                </span>
              </span>
              <button
                type="button"
                className="secondary"
                disabled={busy}
                onClick={() => remove(link)}
                aria-label={`Remove the link: ${ticketLabel(link.replaced_ticket_number, link.replaced_row)} replaced, ${ticketLabel(link.retained_ticket_number, link.retained_row)} kept`}
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
      )}
      <form className="link-form" onSubmit={submit}>
        <label>
          Replaced ticket
          <select
            value={replaced}
            onChange={(event) => {
              setReplaced(Number(event.target.value));
              setKept([]);
            }}
          >
            {members.map((member) => (
              <option key={member.excel_row} value={member.excel_row}>
                {label(member.excel_row)}
              </option>
            ))}
          </select>
        </label>
        <fieldset>
          <legend>Kept tickets</legend>
          {members
            .filter((member) => member.excel_row !== replaced)
            .map((member) => {
              const row = member.excel_row;
              const already = linked.has(row);
              return (
                <label key={row} className="kept-choice">
                  <input
                    type="checkbox"
                    checked={already || kept.includes(row)}
                    disabled={already || reversed.has(row)}
                    onChange={(event) =>
                      setKept((current) => (event.target.checked ? [...current, row] : current.filter((item) => item !== row)))
                    }
                  />
                  {label(row)}
                  {already ? <span className="muted"> (linked)</span> : null}
                  {reversed.has(row) ? <span className="muted"> (recorded as replaced by this ticket)</span> : null}
                </label>
              );
            })}
        </fieldset>
        <label>
          Reason (optional, for linking or removing)
          <input type="text" value={rationale} maxLength={1000} onChange={(event) => setRationale(event.target.value)} />
        </label>
        <div className="form-actions">
          <button type="submit" disabled={busy}>
            Link tickets
          </button>
          <p className={status?.kind === "error" ? "form-status unresolved" : "form-status"} role="status">
            {status?.text}
          </p>
        </div>
      </form>
    </div>
  );
}

function outcomeText(value: OutcomeHistoryValue | null): string {
  if (!value) return "Not reviewed";
  const parts = [value.outcome.label];
  if (value.note) parts.push(`note: ${value.note}`);
  if (value.reference) parts.push(`reference: ${value.reference}`);
  return parts.join("; ");
}

function linkText(value: LinkHistoryValue | null): string {
  if (!value) return "No link";
  return `${ticketLabel(value.replaced_ticket_number, value.replaced_row)} replaced, ${ticketLabel(value.retained_ticket_number, value.retained_row)} kept`;
}

function aliasText(value: AliasHistoryValue | null): string {
  return value ? value.decision.label : "Proposed";
}

function historySubject(entry: HistoryEntry): string {
  if (entry.kind === "outcome") {
    return `Outcome for ${ticketLabel(entry.ticket_numbers[0], entry.excel_rows[0])} and ${ticketLabel(entry.ticket_numbers[1], entry.excel_rows[1])}`;
  }
  if (entry.kind === "alias") return `Alias for “${entry.employee_labels[0]}” and “${entry.employee_labels[1]}”`;
  return "Kept/replaced link";
}

function historyValue(entry: HistoryEntry, side: "previous" | "new"): string {
  if (entry.kind === "outcome") return outcomeText(entry[side]);
  if (entry.kind === "alias") return aliasText(entry[side]);
  return linkText(entry[side]);
}

function ReviewHistory({ history }: { history: HistoryEntry[] }) {
  return (
    <div className="review-history">
      <h4>Review history</h4>
      {history.length === 0 ? (
        <p className="muted">Nothing has been saved for these tickets yet.</p>
      ) : (
        <div className="table-scroll">
          <table className="evidence-table history-table">
            <caption className="visually-hidden">Every saved change for these tickets, newest first</caption>
            <thead>
              <tr>
                <th scope="col">When</th>
                <th scope="col">Reviewer</th>
                <th scope="col">What</th>
                <th scope="col">Before</th>
                <th scope="col">After</th>
                <th scope="col">Reason</th>
              </tr>
            </thead>
            <tbody>
              {history.map((entry) => (
                <tr key={entry.entry}>
                  <td className="num">{when(entry.recorded_at)}</td>
                  <td>{entry.reviewer}</td>
                  <td>{historySubject(entry)}</td>
                  <td className="cell-text">{historyValue(entry, "previous")}</td>
                  <td className="cell-text">{historyValue(entry, "new")}</td>
                  <td className="cell-text">{entry.rationale || <span className="muted">None given</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
