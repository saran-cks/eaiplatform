import type { AgentEvent, AgentStreamOptions } from "./sse";

/**
 * Dev-only mock of the agent named-event stream. Emits the same event shapes
 * `streamAgent` parses (thought / worker_start / worker_done / synthesis /
 * output / done) on timers, so the whole agent surface — ActionStream, answer
 * streaming, interrupt — is demoable without the live LangGraph backend.
 * Swapped for the real `streamAgent` by VITE_MOCK_AGENT (see useConversation).
 * FUTURE: delete once the agent runtime is runnable locally.
 */

function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) return reject(new DOMException("Aborted", "AbortError"));
    const t = setTimeout(resolve, ms);
    signal?.addEventListener(
      "abort",
      () => {
        clearTimeout(t);
        reject(new DOMException("Aborted", "AbortError"));
      },
      { once: true },
    );
  });
}

export async function mockAgentStream({
  prompt,
  onEvent,
  signal,
}: AgentStreamOptions): Promise<void> {
  const script: { delay: number; ev: AgentEvent }[] = [
    { delay: 350, ev: { event: "thought", data: { text: "Planning sub-tasks for the request…" } } },
    { delay: 500, ev: { event: "worker_start", data: { worker_id: "w1", role: "retriever", task: "search the knowledge base" } } },
    { delay: 800, ev: { event: "worker_done", data: { worker_id: "w1", summary: "6 relevant chunks found" } } },
    { delay: 300, ev: { event: "worker_start", data: { worker_id: "w2", role: "analyst", task: "synthesize findings" } } },
    { delay: 600, ev: { event: "thought", data: { text: "Cross-checking sources for consistency…" } } },
    { delay: 700, ev: { event: "worker_done", data: { worker_id: "w2", summary: "draft answer ready" } } },
    { delay: 300, ev: { event: "synthesis", data: { text: "Composing the final response." } } },
  ];

  try {
    for (const { delay, ev } of script) {
      await sleep(delay, signal);
      onEvent(ev);
    }

    const answer =
      `Here's the agent's response to “${prompt}”. ` +
      `This is a mock run — the action stream above shows each planning/worker step, ` +
      `and these tokens arrive over the \`output\` event just like the live agent will.`;
    for (const tok of answer.split(/(\s+)/)) {
      await sleep(35, signal);
      onEvent({ event: "output", data: { text: tok } });
    }

    await sleep(150, signal);
    onEvent({ event: "done", data: {} });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") return;
    throw err;
  }
}
