import type { Member, PossibleDuplicate, ReviewPrioritiesResponse } from "./api";

/** The saved Review Outcomes of a possible duplicate's pairs in words; null when none is reviewed. */
function reviewSummary(item: PossibleDuplicate): string | null {
  const reviewed = item.candidates.filter((candidate) => candidate.outcome.id !== "not_reviewed");
  if (reviewed.length === 0) return null;
  const labels = [...new Set(reviewed.map((candidate) => candidate.outcome.label))].join(", ");
  const pairs = new Set(item.candidates.map((candidate) => candidate.excel_rows.join("-"))).size;
  return pairs === 1 ? labels : `${labels} (${new Set(reviewed.map((c) => c.excel_rows.join("-"))).size} of ${pairs} pairs reviewed)`;
}

/** One ticket's source state in words; a blank Keyed or status stays visible as unknown. */
function sourceState(member: Member): string {
  const status = member.status ?? "Unknown status";
  const keyed = member.keyed === null ? "Keyed unknown" : member.keyed ? "Keyed" : "not Keyed";
  const job = member.job_number === null ? "no usable job" : `Job ${member.job_number}`;
  return `${status}, ${keyed}, ${job}`;
}

function MemberLine({ member }: { member: Member }) {
  return (
    <li>
      <span className="num">{member.ticket_number ?? "No ticket number"}</span>{" "}
      <span className="muted num">row {member.excel_row}</span> · {sourceState(member)}
      {member.flagged_duplicate ? <span className="tag">Flagged duplicate</span> : null}
      {member.in_filter ? null : <span className="tag tag-muted">Outside the filters</span>}
    </li>
  );
}

/** Opens the evidence for a possible duplicate; `opener` gets focus back when the drawer closes. */
export type OpenEvidence = (item: PossibleDuplicate, opener: HTMLButtonElement) => void;

function PriorityRow({ item, onOpen }: { item: PossibleDuplicate; onOpen: OpenEvidence }) {
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
        <ul className="members">
          {item.members.map((member) => (
            <MemberLine key={member.excel_row} member={member} />
          ))}
        </ul>
      </td>
    </tr>
  );
}

/** The ranked possible duplicates, grouped under their priority tiers. */
export function ReviewPriorities({ data, onOpen }: { data: ReviewPrioritiesResponse; onOpen: OpenEvidence }) {
  const tiers = data.tiers
    .map((tier) => ({ tier, items: data.possible_duplicates.filter((item) => item.tier.rank === tier.rank) }))
    .filter(({ items }) => items.length > 0);
  return (
    <section className="priorities" aria-labelledby="priorities-heading">
      <h3 id="priorities-heading" tabIndex={-1}>
        Review priorities
      </h3>
      <p className="muted">{data.note} Open a possible duplicate to see its evidence.</p>
      {tiers.length === 0 ? (
        <p className="status">No possible duplicates have a ticket inside these filters. Widen or clear the filters.</p>
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
                  <PriorityRow key={item.display_id} item={item} onOpen={onOpen} />
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
