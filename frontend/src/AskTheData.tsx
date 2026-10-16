import { useEffect, useId, useRef, useState, type FormEvent } from "react";

import { askQuestion, type AnswerOption, type AnswerView, type Plan, type ProviderInfo, type QuestionAnswer } from "./api";

interface AskTheDataProps {
  provider: ProviderInfo;
  /** The plan the chips hold now: what a follow-up edits. */
  plan: Plan;
  /** The displayed result's one-sentence summary, shown as the interpretation once a question set the chips. */
  summary: string | null;
  onPlan: (plan: Plan) => void;
  onOpenView: (view: AnswerView) => void;
}

type Phase =
  | { kind: "idle" }
  | { kind: "asking"; question: string; followUp: boolean; started: number }
  | { kind: "answered"; question: string; followUp: boolean; answer: QuestionAnswer }
  | { kind: "stopped"; question: string; reason: "cancelled" | "timeout" }
  | { kind: "error"; question: string; message: string };

/** Seconds the browser waits beyond the service's own model timeout before giving up itself. */
const MARGIN_SECONDS = 5;

/**
 * Ask the data (ticket #42): a question in words becomes a plan of chips through the local model, checked by the
 * service before anything runs. Progress is shown while the model works; the question can be cancelled and gives up
 * after the model timeout. Nothing the model writes is shown as a result: the interpretation is the plan's own
 * summary.
 */
export function AskTheData({ provider, plan, summary, onPlan, onOpenView }: AskTheDataProps) {
  const [question, setQuestion] = useState("");
  const [followUp, setFollowUp] = useState("");
  const [phase, setPhase] = useState<Phase>({ kind: "idle" });
  const [elapsed, setElapsed] = useState(0);
  // Set once a question's plan is on the chips, so a follow-up has a chart to edit.
  const [asked, setAsked] = useState<Plan | null>(null);
  const controller = useRef<AbortController | null>(null);
  const stopReason = useRef<"cancelled" | "timeout">("cancelled");
  const hintId = useId();

  useEffect(() => {
    if (phase.kind !== "asking") return;
    const timer = window.setInterval(() => setElapsed(Math.floor((Date.now() - phase.started) / 1000)), 250);
    return () => window.clearInterval(timer);
  }, [phase]);

  useEffect(() => () => controller.current?.abort(), []);

  async function ask(text: string, previous: Plan | null) {
    const trimmed = text.trim();
    if (!trimmed) return;
    controller.current?.abort();
    const current = new AbortController();
    controller.current = current;
    stopReason.current = "cancelled";
    const timer = window.setTimeout(() => {
      stopReason.current = "timeout";
      current.abort();
    }, (provider.timeout_seconds + MARGIN_SECONDS) * 1000);
    setElapsed(0);
    setPhase({ kind: "asking", question: trimmed, followUp: previous !== null, started: Date.now() });
    try {
      const response = await askQuestion(trimmed, previous, current.signal);
      const answer = response.answer;
      setPhase({ kind: "answered", question: trimmed, followUp: previous !== null, answer });
      if (answer.kind === "plan") {
        setAsked(answer.plan);
        onPlan(answer.plan);
      }
    } catch (error: unknown) {
      if (current.signal.aborted) setPhase({ kind: "stopped", question: trimmed, reason: stopReason.current });
      else setPhase({ kind: "error", question: trimmed, message: error instanceof Error ? error.message : String(error) });
    } finally {
      window.clearTimeout(timer);
      if (controller.current === current) controller.current = null;
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    void ask(question, null);
  }

  function submitFollowUp(event: FormEvent) {
    event.preventDefault();
    void ask(followUp, plan);
    setFollowUp("");
  }

  function choose(option: AnswerOption, original: string, wasFollowUp: boolean) {
    if (option.plan) {
      setAsked(option.plan);
      setPhase({ kind: "idle" });
      onPlan(option.plan);
    } else if (option.view) {
      onOpenView(option.view);
    } else if (option.answer) {
      void ask(`${original} (${option.answer})`, wasFollowUp ? plan : null);
    }
  }

  const asking = phase.kind === "asking";
  if (!provider.proposes_plans) {
    return (
      <section className="ask" aria-labelledby="ask-heading">
        <h3 id="ask-heading">Ask the data</h3>
        <p className="muted" id={hintId}>
          No language model is configured, so questions in words are switched off. Relaunch with{" "}
          <code>--model</code> and a local Ollama model to ask in words (see the README, "Questions in words"). The
          chips below build every chart either way.
        </p>
      </section>
    );
  }
  return (
    <section className="ask" aria-labelledby="ask-heading">
      <h3 id="ask-heading">Ask the data</h3>
      <form className="ask-form" aria-label="Ask the data" onSubmit={submit}>
        <label htmlFor={`${hintId}-question`} className="visually-hidden">
          Question
        </label>
        <input
          id={`${hintId}-question`}
          type="text"
          value={question}
          maxLength={500}
          placeholder="For example: show pending tickets by supervisor as a bar chart"
          aria-describedby={hintId}
          disabled={asking}
          onChange={(event) => setQuestion(event.target.value)}
        />
        <button type="submit" disabled={asking || !question.trim()}>
          Ask
        </button>
      </form>
      <p className="muted" id={hintId}>
        Answered by {provider.label} on this machine. It proposes chips only; the service checks them and computes every
        number. No ticket data is sent to the model.
      </p>

      <div className="ask-outcome" aria-live="polite">
        {asking ? (
          <p className="status ask-progress" role="status">
            Asking {provider.model ?? "the model"}… {elapsed} s{" "}
            <button type="button" className="secondary" onClick={() => controller.current?.abort()}>
              Cancel
            </button>
          </p>
        ) : null}
        {phase.kind === "stopped" ? (
          <p className="notice" role="alert">
            {phase.reason === "cancelled"
              ? "Cancelled. Nothing ran, and the chips still show the earlier chart."
              : `No answer within ${provider.timeout_seconds + MARGIN_SECONDS} seconds. Nothing ran. Ask again, shorten the question, or use the chips.`}
          </p>
        ) : null}
        {phase.kind === "error" ? (
          <p className="notice notice-error" role="alert">
            The question could not be sent: {phase.message}. Nothing ran; ask again or use the chips.
          </p>
        ) : null}
        {phase.kind === "answered" ? (
          <AnswerPanel phase={phase} summary={summary} onChoose={(option) => choose(option, phase.question, phase.followUp)} onOpenView={onOpenView} />
        ) : null}
      </div>

      {asked && !asking ? (
        <form className="ask-form" aria-label="Follow up on this chart" onSubmit={submitFollowUp}>
          <label htmlFor={`${hintId}-follow`}>Follow up</label>
          <input
            id={`${hintId}-follow`}
            type="text"
            value={followUp}
            maxLength={500}
            placeholder="For example: only September, or make it a bar chart"
            onChange={(event) => setFollowUp(event.target.value)}
          />
          <button type="submit" className="secondary" disabled={!followUp.trim()}>
            Change the chart
          </button>
        </form>
      ) : null}
    </section>
  );
}

interface AnswerPanelProps {
  phase: Extract<Phase, { kind: "answered" }>;
  summary: string | null;
  onChoose: (option: AnswerOption) => void;
  onOpenView: (view: AnswerView) => void;
}

function AnswerPanel({ phase, summary, onChoose, onOpenView }: AnswerPanelProps) {
  const { answer } = phase;
  if (answer.kind === "plan") {
    return (
      <p className="ask-interpretation" role="status">
        <strong>Interpreted as:</strong> {summary ?? "running the plan…"}{" "}
        <span className="muted">Change any chip to correct it.</span>
      </p>
    );
  }
  if (answer.kind === "view") {
    return (
      <div className="notice" role="status">
        <p>{answer.view.explanation}</p>
        <button type="button" className="secondary" onClick={() => onOpenView(answer.view)}>
          Open {answer.view.label} on the Overview
        </button>
      </div>
    );
  }
  if (answer.kind === "clarify") {
    return (
      <div className="notice" role="status">
        <p>{answer.clarification.question}</p>
        <Options options={answer.clarification.options} onChoose={onChoose} />
      </div>
    );
  }
  if (answer.kind === "unsupported") {
    return (
      <div className="notice" role="status">
        <p>{answer.unsupported.explanation}</p>
        <Options options={answer.unsupported.alternatives} onChoose={onChoose} />
      </div>
    );
  }
  return (
    <div className="notice notice-error" role="alert">
      <p>
        {answer.failure.message} Nothing ran; ask again in other words, or use the chips.
      </p>
      {answer.failure.issues.length ? (
        <ul>
          {answer.failure.issues.map((issue, index) => (
            <li key={index}>
              <code>{issue.field}</code>: {issue.message}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function Options({ options, onChoose }: { options: AnswerOption[]; onChoose: (option: AnswerOption) => void }) {
  if (!options.length) return null;
  return (
    <div className="form-actions">
      {options.map((option) => (
        <button key={option.label} type="button" className="secondary" onClick={() => onChoose(option)}>
          {option.label}
        </button>
      ))}
    </div>
  );
}
