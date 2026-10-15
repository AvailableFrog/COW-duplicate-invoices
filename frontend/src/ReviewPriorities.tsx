import type { Member, PatternFilterState, PossibleDuplicate, PriorityMember, ReviewPrioritiesResponse } from "./api";
import { PatternFilter, PatternMatrix } from "./PatternMatrix";

/** The saved Review Outcomes of a possible duplicate's pairs in words; null when none is reviewed. */
function reviewSummary(item: PossibleDuplicate): string | null {
  const reviewed = item.candidates.filter((candidate) => candidate.outcome.id !== "not_reviewed");
  if (reviewed.length === 0) return null;
  const labels = [...new Set(reviewed.map((candidate) => candidate.outcome.label))].join(", ");
  const pairs = new Set(item.candidates.map((candidate) => candidate.excel_rows.join("-"))).size;
  return pairs === 1 ? labels : `${labels} (${new Set(reviewed.map((c) => c.excel_rows.join("-"))).size} of ${pairs} pairs reviewed)`;
}

/** One ticket's source state in words; a blank Keyed or status stays visible as unknown. */
export function sourceState(member: Member): string {
  const status = member.status ?? "Unknown status";
  const keyed = member.keyed === null ? "Keyed unknown" : member.keyed ? "Keyed" : "not Keyed";
  const job = member.job_number === null ? "no usable job" : `Job ${member.job_number}`;
  return `${status}, ${keyed}, ${job}`;
}

function MemberLine({ member, patternFiltered }: { member: PriorityMember; patternFiltered: boolean }) {
  return (
    <li>
      <span className="num">{member.ticket_number ?? "No ticket number"}</span>{" "}
      <span className="muted num">row {member.excel_row}</span> · {sourceState(member)}
      {member.flagged_duplicate ? <span className="tag">Flagged duplicate</span> : null}
      {member.in_filter ? null : <span className="tag tag-muted">Outside the filters</span>}
      {member.in_filter && patternFiltered && !member.in_selection ? (
        <span className="tag tag-muted">Outside the pattern filter</span>
      ) : null}
    </li>
  );
}

/** Opens the evidence for a possible duplicate; `opener` gets focus back when the drawer closes. */
export type OpenEvidence = (item: PossibleDuplicate, opener: HTMLButtonElement) => void;

function PriorityRow({
  item,
  onOpen,
  patternFiltered,
}: {
  item: PossibleDuplicate;
  onOpen: OpenEvidence;
  patternFiltered: boolean;
}) {
  const review = reviewSummary(item);
  return (
    <tr>
      <td className="num">{item.rank}</td>
      <th scope="row">
        <button
          type="button"
          className="open-evidence"
          aria-haspopup="dialog"
          onClick={(event) => onOpen(item, event.currentTarget)}
        >
          {item.display_id}
        </button>
        <span className="priority-who muted">
          {item.members[0].employee ?? "No employee"} · Date {item.members[0].date ?? "not usable"}
        </span>
      </th>
      <td>
        <ul className="pattern-labels">
          {item.exact_repeat_not_flagged ? <li>Exact repeat, not flagged</li> : null}
          {item.pattern_labels.map((label) => (
            <li key={label}>{label}</li>
          ))}
        </ul>
        <p className="priority-summary">{item.summary}</p>
        {review ? (
          <p className="priority-review">
            <span className="muted">Review outcome: </span>
            {review}
          </p>
        ) : null}
      </td>
      <td>
        {item.source_states.length > 1 ? (
          <p className="member-states">
            <span className="muted">Mixed source states: </span>
            {item.source_states.map((state) => `${state.tickets} ${state.label}`).join(" · ")}
          </p>
        ) : null}
        <ul className="members">
          {item.members.map((member) => (
            <MemberLine key={member.excel_row} member={member} patternFiltered={patternFiltered} />
          ))}
        </ul>
      </td>
    </tr>
  );
}

/**
 * The ranked possible duplicates, grouped under their priority tiers, beside the pattern-by-source-state matrix and
 * the multi-label pattern filter it feeds.
 */
export function ReviewPriorities({
  data,
  onOpen,
  patternFilter,
  onPatternFilterChange,
}: {
  data: ReviewPrioritiesResponse;
  onOpen: OpenEvidence;
  patternFilter: PatternFilterState;
  onPatternFilterChange: (selection: PatternFilterState) => void;
}) {
  const stateLabels = new Map(data.pattern_matrix.source_states.map((state) => [state.id, state.label]));
  const patternFiltered = data.pattern_filter.active;
  const tiers = data.tiers
    .map((tier) => ({ tier, items: data.possible_duplicates.filter((item) => item.tier.rank === tier.rank) }))
    .filter(({ items }) => items.length > 0);
  return (
    <section className="priorities" aria-labelledby="priorities-heading">
      <h3 id="priorities-heading" tabIndex={-1}>
        Review priorities
      </h3>
      <p className="muted">{data.note} Open a possible duplicate to see its evidence.</p>
      <div className="pattern-panel">
        <PatternMatrix matrix={data.pattern_matrix} current={patternFilter} onSelect={onPatternFilterChange} />
        <PatternFilter
          payload={data.pattern_filter}
          current={patternFilter}
          stateLabels={stateLabels}
          onSelect={onPatternFilterChange}
        />
      </div>
      {patternFiltered ? (
        <p className="pattern-showing">
          Showing possible duplicates with a ticket matching {data.pattern_filter.description}; every ticket of each
          stays listed, and those the pattern filter does not count are labelled.
        </p>
      ) : null}
      {tiers.length === 0 ? (
        <p className="status">
          {patternFiltered
            ? "No possible duplicates match this pattern filter inside these filters. Choose other patterns or clear the pattern filter."
            : "No possible duplicates have a ticket inside these filters. Widen or clear the filters."}
        </p>
      ) : (
        <div className="table-scroll">
          <table>
            <caption className="visually-hidden">
              Possible duplicates in review-priority order, rules version {data.versions.rules}
            </caption>
            <thead>
              <tr>
                <th scope="col">Rank</th>
                <th scope="col">Possible duplicate</th>
                <th scope="col">Why</th>
                <th scope="col">Tickets and source state</th>
              </tr>
            </thead>
            {tiers.map(({ tier, items }) => (
              <tbody key={tier.id}>
                <tr className="tier-row">
                  <th scope="rowgroup" colSpan={4}>
                    {tier.rank}. {tier.label} <span className="muted num">({items.length})</span>
                  </th>
                </tr>
                {items.map((item) => (
                  <PriorityRow key={item.display_id} item={item} onOpen={onOpen} patternFiltered={patternFiltered} />
                ))}
              </tbody>
            ))}
          </table>
        </div>
      )}
      <p className="muted">
        Rules version {data.versions.rules}. Possible duplicates are recomposed from the rules on every run; their
        names come from the ticket numbers and are not kept as records.
      </p>
    </section>
  );
}
