import { useState } from "react";

import type { Counterpart, CounterpartStatusId, FlaggedDuplicate, FlaggedDuplicatesResponse } from "./api";
import { sourceState } from "./ReviewPriorities";

/** Opens the drawer for a flagged duplicate; `opener` gets focus back when the drawer closes. */
export type OpenFlagged = (item: FlaggedDuplicate, opener: HTMLButtonElement) => void;

type Shown = "all" | CounterpartStatusId;

/** The relationship in words: found (uncertain when every counterpart is) or unresolved. */
function relationship(item: FlaggedDuplicate): string {
  if (item.counterparts.length === 0) return "Unresolved: no counterpart found";
  const uncertain = item.counterparts.every((counterpart) => !counterpart.certain);
  const count = item.counterparts.length;
  return `${item.counterpart_status.label}${uncertain ? ", uncertain" : ""}${count > 1 ? ` (${count})` : ""}`;
}

function CounterpartLine({ counterpart }: { counterpart: Counterpart }) {
  return (
    <li>
      <span className="num">{counterpart.ticket_number ?? "No ticket number"}</span>{" "}
      <span className="muted num">row {counterpart.excel_row}</span> · {sourceState(counterpart)}
      {counterpart.flagged_duplicate ? <span className="tag">Flagged duplicate</span> : null}
      {counterpart.certain ? null : <span className="tag">Uncertain</span>}
      {counterpart.in_filter ? null : <span className="tag tag-muted">Outside the filters</span>}
      {counterpart.outcome.id !== "not_reviewed" ? (
        <span className="muted"> · Review outcome: {counterpart.outcome.label}</span>
      ) : null}
    </li>
  );
}

function FlaggedRow({ item, onOpen }: { item: FlaggedDuplicate; onOpen: OpenFlagged }) {
  return (
    <tr>
      <th scope="row">
        <button
          type="button"
          className="open-evidence"
          aria-haspopup="dialog"
          aria-label={`Flagged duplicate ${item.ticket_number ?? `row ${item.excel_row}`}`}
          onClick={(event) => onOpen(item, event.currentTarget)}
        >
          {item.ticket_number ?? `Row ${item.excel_row}`}
        </button>
        <span className="priority-who muted">
          {item.employee ?? "No employee"} · Date {item.date ?? "not usable"} · <span className="num">row {item.excel_row}</span>
        </span>
      </th>
      <td>
        <span className={item.counterparts.length === 0 ? "unresolved" : undefined}>{relationship(item)}</span>
        {item.settled_by_review ? <span className="tag tag-muted">Settled by review</span> : null}
      </td>
      <td>
        {item.counterparts.length === 0 ? (
          <span className="muted">None found</span>
        ) : (
          <ul className="members">
            {item.counterparts.map((counterpart) => (
              <CounterpartLine key={counterpart.excel_row} counterpart={counterpart} />
            ))}
          </ul>
        )}
      </td>
      <td>
        {item.possible_duplicate ? (
          <>
            {item.possible_duplicate.display_id}
            <span className="muted"> · priority {item.possible_duplicate.tier.rank}</span>
          </>
        ) : (
          <span className="muted">In no possible duplicate</span>
        )}
      </td>
    </tr>
  );
}

/**
 * Every flagged duplicate the tile counts, filtered by whether a counterpart was found. The split is shown here,
 * beside the tile and never folded into its count.
 */
export function FlaggedDuplicates({ data, onOpen }: { data: FlaggedDuplicatesResponse; onOpen: OpenFlagged }) {
  const [shown, setShown] = useState<Shown>("all");
  const { counts } = data;
  const options: { id: Shown; label: string; count: number }[] = [
    { id: "all", label: "All flagged duplicates", count: counts.flagged_duplicates },
    { id: "counterpart_found", label: "Counterpart found", count: counts.counterpart_found },
    { id: "unresolved", label: "Unresolved", count: counts.unresolved },
  ];
  const rows = data.flagged_duplicates.filter((item) => shown === "all" || item.counterpart_status.id === shown);
  return (
    <section className="priorities flagged" aria-labelledby="flagged-heading">
      <h3 id="flagged-heading" tabIndex={-1}>
        Flagged duplicates
      </h3>
      <p className="muted">{data.note}</p>
      <fieldset className="flagged-filter">
        <legend>Show</legend>
        {options.map((option) => (
          <label key={option.id}>
            <input
              type="radio"
              name="flagged-shown"
              value={option.id}
              checked={shown === option.id}
              onChange={() => setShown(option.id)}
            />
            {option.label} <span className="num">({option.count})</span>
          </label>
        ))}
      </fieldset>
      <ul className="flagged-definitions muted">
        {data.counterpart_statuses.map((status) => (
          <li key={status.id}>
            <strong>{status.label}:</strong> {status.definition}
          </li>
        ))}
      </ul>
      {rows.length === 0 ? (
        <p className="status">No flagged duplicates are inside these filters. Widen or clear the filters.</p>
      ) : (
        <div className="table-scroll">
          <table>
            <caption className="visually-hidden">
              Flagged duplicates with counterpart found or unresolved, rules version {data.versions.rules}
            </caption>
            <thead>
              <tr>
                <th scope="col">Flagged duplicate</th>
                <th scope="col">Relationship</th>
                <th scope="col">Counterparts and source state</th>
                <th scope="col">Possible duplicate</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((item) => (
                <FlaggedRow key={item.excel_row} item={item} onOpen={onOpen} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
