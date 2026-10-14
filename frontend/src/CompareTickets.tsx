import { useState, type FormEvent } from "react";

/** Opens the drawer on two Tickets by Excel row; `opener` gets focus back when the drawer closes. */
export type OpenPair = (rows: [number, number], opener: HTMLElement) => void;

// The header is Excel row 1, so Tickets run from row 2 to row_count + 1.
const FIRST_ROW = 2;

/**
 * Compare any two Tickets by Excel row, linked or not: the drawer says which rules matched and why,
 * so separate work (such as two equal-hour periods on different jobs) is explained, not just absent.
 */
export function CompareTickets({ rowCount, onCompare }: { rowCount: number; onCompare: OpenPair }) {
  const [first, setFirst] = useState("");
  const [second, setSecond] = useState("");
  const [problem, setProblem] = useState("");
  const lastRow = rowCount + 1;

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const rows = [Number(first), Number(second)];
    if (rows.some((row) => !Number.isInteger(row) || row < FIRST_ROW || row > lastRow)) {
      setProblem(`Give two Excel rows from ${FIRST_ROW} to ${lastRow}.`);
      return;
    }
    if (rows[0] === rows[1]) {
      setProblem("Give two different Excel rows.");
      return;
    }
    setProblem("");
    const button = event.currentTarget.querySelector("button");
    onCompare([rows[0], rows[1]], button ?? event.currentTarget);
  }

  return (
    <section className="compare" aria-labelledby="compare-heading">
      <h3 id="compare-heading">Compare two tickets</h3>
      <p className="muted">
        See whether any rule links two tickets and why, including tickets that are not in a possible duplicate.
      </p>
      <form className="filter-bar compare-form" aria-labelledby="compare-heading" onSubmit={submit} noValidate>
        <label>
          <span>First ticket, Excel row</span>
          <input
            type="number"
            inputMode="numeric"
            min={FIRST_ROW}
            max={lastRow}
            value={first}
            onChange={(event) => setFirst(event.target.value)}
          />
        </label>
        <label>
          <span>Second ticket, Excel row</span>
          <input
            type="number"
            inputMode="numeric"
            min={FIRST_ROW}
            max={lastRow}
            value={second}
            onChange={(event) => setSecond(event.target.value)}
          />
        </label>
        <button type="submit" className="secondary" aria-haspopup="dialog">
          Compare
        </button>
        <p className="status" role="status">
          {problem}
        </p>
      </form>
    </section>
  );
}
