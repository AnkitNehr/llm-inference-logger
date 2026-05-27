export const CHATBOT_URL = (import.meta as any).env.VITE_CHATBOT_URL || "http://localhost:8001";
export const INGESTION_URL = (import.meta as any).env.VITE_INGESTION_URL || "http://localhost:8002";

export type Conversation = {
  id: string;
  title: string;
  status: string;
  provider: string;
  model: string;
  created_at: string;
  updated_at: string;
  message_count?: number;
};

export type Message = {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  created_at: string;
};

export async function listConversations(): Promise<Conversation[]> {
  const r = await fetch(`${CHATBOT_URL}/v1/conversations`);
  return r.json();
}

export async function createConversation(opts: { provider?: string; model?: string } = {}): Promise<Conversation> {
  const r = await fetch(`${CHATBOT_URL}/v1/conversations`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(opts),
  });
  return r.json();
}

export type ProviderCatalogEntry = { name: string; available: boolean; models: string[] };
export type ModelsCatalog = {
  default_provider: string;
  default_model: string;
  providers: ProviderCatalogEntry[];
};
export async function listModels(): Promise<ModelsCatalog> {
  const r = await fetch(`${CHATBOT_URL}/v1/conversations/models`);
  return r.json();
}

export async function getConversation(id: string): Promise<Conversation & { messages: Message[] }> {
  const r = await fetch(`${CHATBOT_URL}/v1/conversations/${id}`);
  return r.json();
}

export async function cancelConversation(id: string): Promise<void> {
  await fetch(`${CHATBOT_URL}/v1/conversations/${id}/cancel`, { method: "POST" });
}

/** Stream chat tokens via SSE. Returns an async iterator. */
export async function* streamChat(
  conversationId: string,
  content: string,
  signal: AbortSignal,
  override?: { provider?: string; model?: string },
): AsyncIterableIterator<{ type: string; data: any }> {
  const body: any = { content };
  if (override?.provider) body.provider = override.provider;
  if (override?.model) body.model = override.model;
  const r = await fetch(`${CHATBOT_URL}/v1/conversations/${conversationId}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify(body),
    signal,
  });
  if (!r.ok || !r.body) throw new Error(`stream failed: ${r.status}`);
  const reader = r.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = buffer.indexOf("\n\n")) !== -1) {
      const raw = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      const evt = parseSSE(raw);
      if (evt) yield evt;
    }
  }
}

function parseSSE(raw: string): { type: string; data: any } | null {
  let event = "message";
  const dataLines: string[] = [];
  for (const line of raw.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
  }
  if (!dataLines.length) return null;
  try {
    return { type: event, data: JSON.parse(dataLines.join("\n")) };
  } catch {
    return { type: event, data: dataLines.join("\n") };
  }
}

export async function getOverview(windowMin = 1440) {
  const r = await fetch(`${INGESTION_URL}/v1/stats/overview?window_minutes=${windowMin}`);
  return r.json();
}
export async function getLatency(windowMin = 1440) {
  const r = await fetch(`${INGESTION_URL}/v1/stats/latency?window_minutes=${windowMin}`);
  return r.json();
}
export async function getThroughput(windowMin = 1440) {
  const r = await fetch(`${INGESTION_URL}/v1/stats/throughput?window_minutes=${windowMin}`);
  return r.json();
}
export async function getErrors(windowMin = 1440) {
  const r = await fetch(`${INGESTION_URL}/v1/stats/errors?window_minutes=${windowMin}`);
  return r.json();
}
