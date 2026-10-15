import { Fragment, useEffect, useRef, useState, type ReactNode } from "react";

import {
  ApiError,
  fetchEvidence,
  fetchPairExplanation,
  type Annotation,
  type EvidenceCandidate,
  type EvidenceMember,
  type EvidenceResponse,
  type FilterState,
  type PairExplanation,
  type ShownEvidence,
  type SourceCell,
  type TimeComparison,
  type TimeParse,
} from "./api";
import { ReviewPanel } from "./ReviewPanel";

/**
 * What the drawer was opened on: a possible duplicate by one member Ticket (never its display name),
 * or any two Tickets to compare, linked or not.
 */
export type DrawerTarget =
  | { kind: "possible_duplicate"; fingerprint: string; excelRow: number; displayId: string }
  | { kind: "pair"; fingerprint: string; rows: [number, number] };

type Loaded = { kind: "possible_duplicate"; data: EvidenceResponse } | { kind: "pair"; data: PairExplanation };

interface EvidenceDrawerProps {
  target: DrawerTarget | null;
  filters: FilterState;
  onClose: () => void;
  /** Called after a Review Outcome or link is saved, so the list can show it. */
  onReviewChange: () => void;
}

// Each settled state remembers its target, so a newly opened drawer never shows the previous one's evidence.
type LoadState =
  | { kind: "loading" }
  | { kind: "ready"; target: DrawerTarget; loaded: Loaded }
  | { kind: "failed"; target: DrawerTarget; message: string; status: number | null };

// Visible stand-ins for whitespace, shown only while "Show whitespace" is on.
const WHITESPACE_MARKS: Record<string, string> = { " ": "·", "\t": "→", " ": "°", "\n": "↵\n", "\r": "←" };

/** Text with each whitespace character drawn as a mark; the value itself is never changed. */
function revealWhitespace(text: string): ReactNode[] {
  return text.split(/([ \t \r\n])/).map((part, index) =>
    part in WHITESPACE_MARKS ? (
      <span key={index} className="ws-mark" aria-hidden="true">
        {WHITESPACE_MARKS[part]}
      </span>
    ) : (
      part
    ),
  );
}

/** One source cell as text. Blank, zero, false and the text "0" stay distinguishable; markup is never interpreted. */
function CellValue({ cell, showWhitespace }: { cell: SourceCell | null; showWhitespace: boolean }) {
  if (cell === null) return <span className="cell-absent">column absent</span>;
  const { raw_type: rawType, value } = cell;
  if (rawType === "blank" || value === null) return <span className="cell-blank">(blank)</span>;
  if (typeof value === "boolean") return <span className="cell-typed">{value ? "true" : "false"}</span>;
  if (typeof value === "number") return <span className="cell-typed num">{String(value)}</span>;
  if (rawType === "datetime") return <span className="num">{value.replace("T", " ")}</span>;
  if (rawType === "str" && value === "") return <span className="cell-blank">(empty text)</span>;
  const kind = rawType === "str" ? null : <span className="cell-kind">{rawType}</span>;
  if (!showWhitespace) {
    return (
      <span className="cell-text">
        {value}
        {kind}
      </span>
    );
  }
  // Quoted, as the evidence report prints text, so leading and trailing spaces have visible edges.
  return (
    <span className="cell-text">
      <span className="ws-mark" aria-hidden="true">“</span>
      {revealWhitespace(value)}
      <span className="ws-mark" aria-hidden="true">”</span>
      {kind}
    </span>
  );
}

function memberHeading(member: EvidenceMember): string {
  return member.ticket_number ?? `Row ${member.excel_row}`;
}

const COMPARISON_LABELS: Record<TimeComparison["result"], string> = {
  overlap: "Work periods overlap",
  separate: "Work periods are separate",
  ambiguous: "Overlap cannot be established; assumed readings compared",
  undetermined: "Work periods cannot be compared",
};

function interval(value: { start: string; end: string }): string {
  return `${value.start}–${value.end}`;
}

/** How two Tickets' work periods compare; an overlap read from Plausible Readings is labelled assumed. */
function ComparisonLine({ comparison }: { comparison: TimeComparison }) {
  return (
    <p>
      {COMPARISON_LABELS[comparison.result]}
      {comparison.intersection.length > 0 ? (
        <span className="num">
          {" "}
          ({comparison.intersection.map(interval).join(", ")}, {comparison.overlap_minutes} minutes
          {comparison.assumed ? ", assumed" : ""})
        </span>
      ) : null}
      . <span className="muted">{comparison.explanation}</span>
    </p>
  );
}

function CandidateItem({ candidate }: { candidate: EvidenceCandidate }) {
  const [first, second] = candidate.excel_rows;
  return (
    <li className="candidate">
      <p>
        <strong>{candidate.rule_label}</strong> between rows <span className="num">{first}</span> and{" "}
        <span className="num">{second}</span> · {candidate.evidence_strength} matching evidence
      </p>
      <p>{candidate.reason}</p>
      <p className="muted">Fields compared: {candidate.fields_compared.join(", ")}</p>
      <ComparisonLine comparison={candidate.time_comparison} />
    </li>
  );
}

function AnnotationPanel({ annotation }: { annotation: Annotation }) {
  const headingId = `annotation-${annotation.letter}`;
  return (
    <section className="annotation" aria-labelledby={headingId}>
      <h3 id={headingId}>
        <span className="example-letter" aria-hidden="true">
          {annotation.letter}
        </span>
        <span>
          Evidence report example {annotation.letter}: {annotation.title}
        </span>
      </h3>
      <p className="muted">
        Pattern {annotation.pattern.number}: {annotation.pattern.title}. {annotation.summary}
      </p>
      <figure className="review-note">
        <figcaption>
          {annotation.review_note_reworded
            ? "Review note (condensed paraphrase, reworded to the display language)"
            : "Review note (condensed paraphrase from the evidence report)"}
        </figcaption>
        {annotation.review_note ? (
          <blockquote>{annotation.review_note}</blockquote>
        ) : (
          <p className="muted">The evidence report has no review note for this example.</p>
        )}
      </figure>
      <h4>Questions for Oliver</h4>
      <ol className="questions">
        {annotation.questions_for_oliver.map((question) => (
          <li key={question}>{question}</li>
        ))}
      </ol>
      <p className="muted">What the answer changes: {annotation.what_the_answer_changes}</p>
      <p className="muted">Evidence report section: {annotation.source_section}.</p>
      {annotation.tickets.some((ticket) => !ticket.in_possible_duplicate) ? (
        <p className="muted">
          The example also names{" "}
          {annotation.tickets
            .filter((ticket) => !ticket.in_possible_duplicate)
            .map((ticket) => `${ticket.ticket_number} (row ${ticket.excel_row ?? "not in this Snapshot"})`)
            .join(", ")}
          , which the matching rules did not link here.
        </p>
      ) : null}
    </section>
  );
}

function TimeParseCard({ member, parse }: { member: EvidenceMember; parse: TimeParse }) {
  return (
    <li className="parse-card">
      <p>
        <strong>{memberHeading(member)}</strong> <span className="muted num">row {member.excel_row}</span>
      </p>
      <dl>
        <dt>Time as written</dt>
        <dd>
          <CellValue cell={{ ...parse.raw_time, number_format: null }} showWhitespace={false} />
        </dd>
        <dt>Reading</dt>
        <dd>{parse.status}</dd>
        {parse.periods.map((period, index) => (
          <Fragment key={index}>
            <dt>Period {index + 1}</dt>
            <dd>
              <span className="num">{period.text}</span>: {period.confidence === "confident" ? "Confident" : "Ambiguous"}
              {period.interval ? <span className="num"> {interval(period.interval)}</span> : null}
              {period.plausible_reading ? (
                <span>
                  {" "}
                  · Plausible Reading <span className="num">{interval(period.plausible_reading)}</span>{" "}
                  <span className="tag">assumed</span>
                </span>
              ) : null}
              {period.flags.map((flag) => (
                <span key={flag} className="tag">
                  {flag.replace(/_/g, " ")}
                </span>
              ))}
            </dd>
          </Fragment>
        ))}
        <dt>Parser version</dt>
        <dd className="num">{parse.parser_version}</dd>
      </dl>
      {parse.notes.map((note) => (
        <p key={note} className="muted">
          {note}
        </p>
      ))}
    </li>
  );
}

function Evidence({ data, onReviewChange }: { data: EvidenceResponse; onReviewChange: () => void }) {
  return (
    <>
      <section aria-labelledby="drawer-why">
        <h3 id="drawer-why">Why these tickets are together</h3>
        <ul className="pattern-labels">
          {data.exact_repeat_not_flagged ? <li>Exact repeat, not flagged</li> : null}
          {data.pattern_labels.map((label) => (
            <li key={label}>{label}</li>
          ))}
        </ul>
        <p className="drawer-reason">{data.reason}</p>
        <ul className="candidates">
          {data.candidates.map((candidate) => (
            <CandidateItem key={`${candidate.rule_id}-${candidate.excel_rows.join("-")}`} candidate={candidate} />
          ))}
        </ul>
        <p>
          <span className="muted">Ticket states: </span>
          {data.status_breakdown
            .map((state) => `${state.tickets} ${state.tickets === 1 ? "ticket" : "tickets"} ${state.label}`)
            .join("; ")}
          .
        </p>
      </section>

      <ReviewPanel
        fingerprint={data.snapshot_fingerprint}
        members={data.members}
        review={data.review}
        onChanged={onReviewChange}
      />

      <SharedEvidence data={data} />
    </>
  );
}

/** Two compared Tickets: why they are or are not linked, then the same evidence a possible duplicate shows. */
function PairEvidence({ data }: { data: PairExplanation }) {
  return (
    <>
      <section aria-labelledby="drawer-why">
        <h3 id="drawer-why">{data.linked ? "Why these tickets are linked" : "Why these tickets are not linked"}</h3>
        <p className="drawer-reason">{data.summary}</p>
        <ComparisonLine comparison={data.time_comparison} />
        <ul className="candidates" aria-label="Each rule's verdict">
          {data.rules.map((rule) => (
            <li key={rule.rule_id} className={rule.matched ? "candidate" : "candidate candidate-unmatched"}>
              <p>
                <strong>{rule.rule_label}</strong>:{" "}
                {rule.matched ? `matched · ${rule.evidence_strength} matching evidence` : "not matched"}
              </p>
              <p>{rule.reason}</p>
              <p className="muted">Fields compared: {rule.fields_compared.join(", ")}</p>
            </li>
          ))}
        </ul>
        <ul className="pair-membership">
          {data.members.map((member) => (
            <li key={member.excel_row}>
              <strong>{memberHeading(member)}</strong> <span className="muted num">row {member.excel_row}</span>:{" "}
              {member.possible_duplicate ? `in ${member.possible_duplicate}` : "in no possible duplicate"}
            </li>
          ))}
        </ul>
      </section>

      <SharedEvidence data={data} />
    </>
  );
}

/** Annotations, timeline, source rows, Time as parsed and provenance: shown for any set of Tickets. */
function SharedEvidence({ data }: { data: ShownEvidence }) {
  const [showWhitespace, setShowWhitespace] = useState(false);
  const differing = data.differing_fields.length;
  return (
    <>
      {data.annotations.map((annotation) => (
        <AnnotationPanel key={annotation.letter} annotation={annotation} />
      ))}

      <section aria-labelledby="drawer-timeline">
        <h3 id="drawer-timeline">Claim timeline</h3>
        <div className="table-scroll">
          <table className="evidence-table timeline-table">
            <caption className="visually-hidden">Tickets in Created order, oldest first</caption>
            <thead>
              <tr>
                <th scope="col">Ticket</th>
                {data.timeline.fields.map((field) => (
                  <th key={field} scope="col">
                    {field}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.timeline.entries.map((entry) => (
                <tr key={entry.excel_row}>
                  <th scope="row">
                    {entry.ticket_number ?? "No ticket number"} <span className="muted num">row {entry.excel_row}</span>
                  </th>
                  {entry.cells.map((cell, index) => (
                    <td key={data.timeline.fields[index]}>
                      <CellValue cell={cell} showWhitespace={false} />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section aria-labelledby="drawer-source">
        <div className="section-head">
          <h3 id="drawer-source">Source rows, side by side</h3>
          <label className="toggle">
            <input
              type="checkbox"
              checked={showWhitespace}
              onChange={(event) => setShowWhitespace(event.target.checked)}
            />
            Show whitespace
          </label>
        </div>
        <p className="muted">
          All {data.fields.length} columns as imported.{" "}
          {differing === 0
            ? "No value differs between the tickets."
            : `${differing} ${differing === 1 ? "field differs" : "fields differ"}, marked Differs: ${data.differing_fields.join(", ")}.`}
          {showWhitespace ? " Text is quoted; · is a space, → a tab, ↵ a line break. The values are unchanged." : ""}
        </p>
        <div className="table-scroll">
          <table className="evidence-table source-table">
            <caption className="visually-hidden">Source fields down the side, one column per ticket</caption>
            <thead>
              <tr>
                <th scope="col" className="field-name">
                  Field
                </th>
                {data.members.map((member) => (
                  <th key={member.excel_row} scope="col">
                    {memberHeading(member)}
                    <span className="muted num member-sub">
                      Excel row {member.provenance.excel_row} · dataframe {member.provenance.dataframe_index}
                    </span>
                    {member.flagged_duplicate ? <span className="tag">Flagged duplicate</span> : null}
                    {member.in_filter ? null : <span className="tag tag-muted">Outside the filters</span>}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.fields.map((row) => (
                <tr key={row.field} className={row.differs ? "differs" : undefined}>
                  <th scope="row" className="field-name">
                    {row.field}
                    {row.differs ? <span className="differs-mark">Differs</span> : null}
                  </th>
                  {row.cells.map((cell) => (
                    <td key={cell.excel_row}>
                      <CellValue cell={cell} showWhitespace={showWhitespace} />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section aria-labelledby="drawer-time">
        <h3 id="drawer-time">Time as parsed</h3>
        <ul className="parse-cards">
          {data.members.map((member) => (
            <TimeParseCard key={member.excel_row} member={member} parse={member.time_parse} />
          ))}
        </ul>
      </section>

      <section aria-labelledby="drawer-provenance">
        <h3 id="drawer-provenance">Where each ticket comes from</h3>
        <ul className="provenance">
          {data.members.map((member) => (
            <li key={member.excel_row}>
              <strong>{memberHeading(member)}</strong>: Excel row{" "}
              <span className="num">{member.provenance.excel_row}</span>, dataframe index{" "}
              <span className="num">{member.provenance.dataframe_index}</span>, sheet {member.provenance.sheet}, workbook
              fingerprint <code className="fingerprint">{member.provenance.snapshot_fingerprint}</code>
              {member.issues.length > 0 ? (
                <span className="unresolved">
                  {" "}
                  · import issues: {member.issues.map((issue) => issue.message).join("; ")}
                </span>
              ) : null}
            </li>
          ))}
        </ul>
      </section>
    </>
  );
}

/** The wide evidence drawer for one possible duplicate: a modal dialog closed by its button or Escape. */
export function EvidenceDrawer({ target, filters, onClose, onReviewChange }: EvidenceDrawerProps) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [settled, setState] = useState<LoadState>({ kind: "loading" });
  // Bumped after a review save: the evidence is fetched again in place, keeping the drawer open.
  const [reviewGeneration, setReviewGeneration] = useState(0);
  // The target whose evidence a review save last reloaded: an Alias decision can unlink its tickets.
  const [reviewedTarget, setReviewedTarget] = useState<DrawerTarget | null>(null);
  const state: LoadState = settled.kind !== "loading" && settled.target === target ? settled : { kind: "loading" };

  useEffect(() => {
    const element = dialog.current;
    if (!element) return;
    if (target && !element.open) element.showModal();
    if (!target && element.open) element.close();
  }, [target]);

  useEffect(() => {
    if (!target) return;
    const controller = new AbortController();
    const load: Promise<Loaded> =
      target.kind === "pair"
        ? fetchPairExplanation(target.fingerprint, target.rows, filters, controller.signal).then((data) => ({
            kind: "pair",
            data,
          }))
        : fetchEvidence(target.fingerprint, target.excelRow, filters, controller.signal).then((data) => ({
            kind: "possible_duplicate",
            data,
          }));
    load
      .then((loaded) => setState({ kind: "ready", target, loaded }))
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setState({
          kind: "failed",
          target,
          message: error instanceof Error ? error.message : String(error),
          status: error instanceof ApiError ? error.status : null,
        });
      });
    return () => controller.abort();
  }, [target, filters, reviewGeneration]);

  function reviewChanged() {
    setReviewGeneration((value) => value + 1);
    setReviewedTarget(target);
    onReviewChange();
  }

  const loaded = state.kind === "ready" ? state.loaded : null;
  // Who and which day: one line when every ticket shown shares them, otherwise each ticket's own.
  const who = loaded
    ? [...new Set(loaded.data.members.map((m) => `${m.employee ?? "No employee"} · Date ${m.date ?? "not usable"}`))].join(
        "; ",
      )
    : null;
  return (
    <dialog ref={dialog} className="drawer" aria-labelledby="drawer-title" onClose={onClose}>
      {target ? (
        <>
          <header className="drawer-head">
            <div>
              <p className="eyebrow">
                {target.kind === "pair"
                  ? "Two tickets compared"
                  : `Possible duplicate${loaded?.kind === "possible_duplicate" ? ` · priority ${loaded.data.tier.rank}: ${loaded.data.tier.label}` : ""}`}
              </p>
              <h2 id="drawer-title">
                {target.kind === "pair" ? `Excel rows ${target.rows[0]} and ${target.rows[1]}` : target.displayId}
              </h2>
              {who ? (
                <p className="muted">
                  {who} · Snapshot <code className="fingerprint">{target.fingerprint.slice(0, 12)}</code>
                </p>
              ) : null}
            </div>
            <button type="button" className="secondary" onClick={() => dialog.current?.close()} autoFocus>
              Close
            </button>
          </header>
          <div className="drawer-body">
            {state.kind === "loading" ? <p className="status">Loading the evidence…</p> : null}
            {state.kind === "failed" && state.status === 404 && reviewedTarget === target ? (
              <p className="notice" role="status">
                After that decision the matching rules no longer link these tickets, so there is no possible duplicate
                to show. The decision and its history stay saved; close the drawer to see the updated list.
              </p>
            ) : state.kind === "failed" ? (
              <p className="notice notice-error" role="alert">
                The evidence could not be loaded: {state.message}.{" "}
                {target.kind === "pair"
                  ? "Check both Excel rows and compare again; if it still fails, reload the page."
                  : "Close the drawer and open the possible duplicate again; if it still fails, reload the page."}
              </p>
            ) : null}
            {loaded?.kind === "possible_duplicate" ? <Evidence data={loaded.data} onReviewChange={reviewChanged} /> : null}
            {loaded?.kind === "pair" ? <PairEvidence data={loaded.data} /> : null}
          </div>
        </>
      ) : null}
    </dialog>
  );
}
