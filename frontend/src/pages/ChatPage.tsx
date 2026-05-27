import { useEffect, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { useParams } from "react-router-dom";
import { Conversation, Message, ModelsCatalog, cancelConversation, getConversation, listModels, streamChat } from "../api";

type LocalMessage = Message & { isStreaming?: boolean; modelUsed?: string };

export default function ChatPage({ onMessageSent }: { onMessageSent: () => void }) {
  const { id } = useParams<{ id: string }>();
  const [conv, setConv] = useState<Conversation | null>(null);
  const [messages, setMessages] = useState<LocalMessage[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [catalog, setCatalog] = useState<ModelsCatalog | null>(null);
  const [provider, setProvider] = useState<string>("");
  const [model, setModel] = useState<string>("");
  const abortRef = useRef<AbortController | null>(null);
  const threadRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    listModels().then(setCatalog).catch(() => {});
  }, []);

  useEffect(() => {
    if (!id) return;
    setMessages([]);
    getConversation(id).then(c => {
      setConv(c as any);
      setMessages(c.messages || []);
      setProvider(c.provider);
      setModel(c.model);
    });
  }, [id]);

  useEffect(() => {
    threadRef.current?.scrollTo({ top: threadRef.current.scrollHeight });
  }, [messages]);

  const providerEntry = catalog?.providers.find(p => p.name === provider);
  const modelOptions = providerEntry?.models ?? [];

  function onProviderChange(p: string) {
    setProvider(p);
    const entry = catalog?.providers.find(x => x.name === p);
    if (entry && !entry.models.includes(model)) setModel(entry.models[0]);
  }

  async function syncFromServer() {
    if (!id) return;
    try {
      const c = await getConversation(id);
      setMessages(c.messages || []);
    } catch {
      // best-effort; ignore
    }
  }

  async function handleSend() {
    if (!id || !input.trim() || streaming) return;

    const userMsg: LocalMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content: input.trim(),
      created_at: new Date().toISOString(),
    };
    const assistantId = crypto.randomUUID();
    const placeholderAssistant: LocalMessage = {
      id: assistantId,
      role: "assistant",
      content: "",
      isStreaming: true,
      modelUsed: model,
      created_at: new Date().toISOString(),
    };

    // Force the placeholder into the DOM synchronously BEFORE consuming the stream
    flushSync(() => {
      setMessages(m => [...m, userMsg, placeholderAssistant]);
      setInput("");
      setStreaming(true);
    });

    const ctrl = new AbortController();
    abortRef.current = ctrl;
    let accumulated = "";

    const writeContent = (content: string, extra: Partial<LocalMessage> = {}) => {
      flushSync(() => {
        setMessages(prev =>
          prev.map(msg => (msg.id === assistantId ? { ...msg, content, ...extra } : msg))
        );
      });
    };

    try {
      for await (const evt of streamChat(id, userMsg.content, ctrl.signal, { provider, model })) {
        if (evt.type === "token") {
          accumulated += evt.data?.delta ?? "";
          writeContent(accumulated);
        } else if (evt.type === "error") {
          accumulated = accumulated || `⚠️ ${evt.data?.message || "error"}`;
          writeContent(accumulated, { isStreaming: false });
          break;
        } else if (evt.type === "done") {
          writeContent(accumulated, { isStreaming: false });
          break;
        }
      }
    } catch (e) {
      writeContent(accumulated || "⚠️ connection interrupted", { isStreaming: false });
    } finally {
      setStreaming(false);
      abortRef.current = null;
      // Always finalize the streaming flag
      setMessages(prev =>
        prev.map(msg => (msg.id === assistantId ? { ...msg, isStreaming: false } : msg))
      );
      // Belt-and-suspenders: re-sync from DB so the bubble is guaranteed to show
      // the persisted assistant message even if any optimistic update was lost.
      await syncFromServer();
      onMessageSent();
    }
  }

  async function handleStop() {
    if (!id) return;
    await cancelConversation(id);
    abortRef.current?.abort();
  }

  if (!id) return null;

  return (
    <>
      <div className="chat-thread" ref={threadRef}>
        {messages.length === 0 && (
          <div className="empty">Send a message to start the conversation.</div>
        )}
        {messages.map(m => (
          <div key={m.id} className={`msg ${m.role}`}>
            <div className="role">
              {m.role}
              {m.isStreaming ? " · streaming" : ""}
              {m.modelUsed ? ` · ${m.modelUsed}` : ""}
            </div>
            {m.content || (m.isStreaming ? <span className="cursor">▍</span> : "")}
          </div>
        ))}
      </div>
      <div className="composer">
        <div className="composer-row">
          <textarea
            placeholder="Message the assistant…"
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => {
              if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSend(); }
            }}
            disabled={streaming}
          />
          {streaming
            ? <button className="stop" onClick={handleStop}>Stop</button>
            : <button onClick={handleSend} disabled={!input.trim()}>Send</button>
          }
        </div>
        {catalog && (
          <div className="composer-toolbar">
            <div className="model-chip" title="Change model for the next message">
              <select value={provider} onChange={e => onProviderChange(e.target.value)} disabled={streaming}>
                {catalog.providers.map(p => (
                  <option key={p.name} value={p.name} disabled={!p.available}>
                    {p.name}{!p.available ? " (no key)" : ""}
                  </option>
                ))}
              </select>
              <span className="chip-sep">·</span>
              <select value={model} onChange={e => setModel(e.target.value)} disabled={streaming || !modelOptions.length}>
                {modelOptions.map(m => (<option key={m} value={m}>{m}</option>))}
              </select>
            </div>
            <span className="composer-hint">Model can be changed any time. It applies to the next message.</span>
          </div>
        )}
      </div>
    </>
  );
}
