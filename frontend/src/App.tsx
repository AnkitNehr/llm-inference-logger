import { useEffect, useMemo, useState } from "react";
import { Link, NavLink, Route, Routes, useNavigate, useParams } from "react-router-dom";
import { Conversation, ModelsCatalog, createConversation, listConversations, listModels } from "./api";
import ChatPage from "./pages/ChatPage";
import DashboardPage from "./pages/DashboardPage";

export default function App() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [catalog, setCatalog] = useState<ModelsCatalog | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const navigate = useNavigate();

  async function refresh() { setConversations(await listConversations()); }
  useEffect(() => {
    refresh();
    listModels().then(setCatalog).catch(() => {});
    const t = setInterval(refresh, 5000);
    return () => clearInterval(t);
  }, []);

  async function handleCreate(provider?: string, model?: string) {
    const c = await createConversation({ provider, model });
    setPickerOpen(false);
    await refresh();
    navigate(`/chat/${c.id}`);
  }

  return (
    <div className="app">
      <aside className="sidebar">
        <header>
          <h1>Ollive Chat</h1>
          <button className="new-btn" onClick={() => setPickerOpen(true)}>+ New</button>
        </header>
        <nav>
          <NavLink to="/" end>Chat</NavLink>
          <NavLink to="/dashboard">Dashboard</NavLink>
        </nav>
        <div className="list">
          {conversations.length === 0 && <div className="empty" style={{ padding: 24, fontSize: 12 }}>No conversations yet</div>}
          {conversations.map(c => <ConvItem key={c.id} c={c} />)}
        </div>
      </aside>
      <main className="main">
        <Routes>
          <Route path="/" element={<EmptyState onNew={() => setPickerOpen(true)} hasConversations={conversations.length > 0} />} />
          <Route path="/chat/:id" element={<ChatPage onMessageSent={refresh} />} />
          <Route path="/dashboard" element={<DashboardPage />} />
        </Routes>
      </main>
      {pickerOpen && catalog && (
        <NewChatPicker catalog={catalog} onCancel={() => setPickerOpen(false)} onStart={handleCreate} />
      )}
    </div>
  );
}

function ConvItem({ c }: { c: Conversation }) {
  const { id } = useParams();
  const active = id === c.id;
  return (
    <Link to={`/chat/${c.id}`} style={{ textDecoration: "none", color: "inherit" }}>
      <div className={`conv-item ${active ? "active" : ""}`}>
        <div className="title">{c.title}</div>
        <div className="meta">{c.message_count ?? 0} msgs · {c.status} · {c.model}</div>
      </div>
    </Link>
  );
}

function EmptyState({ onNew, hasConversations }: { onNew: () => void; hasConversations: boolean }) {
  return (
    <div className="empty-state">
      <div className="empty-state-card">
        <div className="empty-state-icon">💬</div>
        <h2>No conversation open</h2>
        {hasConversations ? (
          <>
            <p>Pick a conversation from the sidebar on the left, or start a new one.</p>
            <button className="primary-btn" onClick={onNew}>+ Start a new conversation</button>
          </>
        ) : (
          <>
            <p>You don't have any conversations yet. Start your first one to begin chatting.</p>
            <button className="primary-btn" onClick={onNew}>+ Start a new conversation</button>
          </>
        )}
      </div>
    </div>
  );
}

function NewChatPicker({
  catalog,
  onCancel,
  onStart,
}: {
  catalog: ModelsCatalog;
  onCancel: () => void;
  onStart: (provider: string, model: string) => void;
}) {
  // Default to whichever provider is available + default, else first available
  const initialProvider = useMemo(() => {
    const def = catalog.providers.find(p => p.name === catalog.default_provider && p.available);
    return (def ?? catalog.providers.find(p => p.available) ?? catalog.providers[0]).name;
  }, [catalog]);
  const [provider, setProvider] = useState(initialProvider);
  const providerEntry = catalog.providers.find(p => p.name === provider)!;
  const initialModel = providerEntry.models.includes(catalog.default_model)
    ? catalog.default_model
    : providerEntry.models[0];
  const [model, setModel] = useState(initialModel);

  // When provider changes, snap model to that provider's first option
  useEffect(() => {
    setModel(providerEntry.models[0]);
  }, [provider]);

  return (
    <div className="modal-backdrop" onClick={onCancel}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <h3>New conversation</h3>
        <p className="modal-hint">Pick the model for this chat. Once started it's locked for this thread so analytics stay consistent.</p>

        <label>Provider</label>
        <select value={provider} onChange={e => setProvider(e.target.value)}>
          {catalog.providers.map(p => (
            <option key={p.name} value={p.name} disabled={!p.available}>
              {p.name}{!p.available ? "  (no API key set)" : ""}
            </option>
          ))}
        </select>

        <label>Model</label>
        <select value={model} onChange={e => setModel(e.target.value)}>
          {providerEntry.models.map(m => (
            <option key={m} value={m}>{m}</option>
          ))}
        </select>

        <div className="modal-actions">
          <button className="secondary-btn" onClick={onCancel}>Cancel</button>
          <button className="primary-btn" onClick={() => onStart(provider, model)} disabled={!providerEntry.available}>
            Start chat
          </button>
        </div>
      </div>
    </div>
  );
}
