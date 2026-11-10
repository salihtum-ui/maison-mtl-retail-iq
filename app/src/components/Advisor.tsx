import { type FormEvent, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

import { askMtlAdvisor } from '@/services/advisor';

type Message = {
  id: number;
  role: 'user' | 'assistant';
  text: string;
  generatedAt?: string;
};

const SUGGESTIONS = [
  'Which store had the highest net sales in the last 28 days?',
  'What are the top 5 products by net sales in October 2026?',
  'How many parkas do we have in stock in Laval right now?',
  'Which stores have the most products below their reorder point?',
  'Quels produits risquent une rupture de stock cette semaine au magasin de Québec?',
  'List the pending reorder requests submitted in the app.',
];

const WELCOME: Message = {
  id: 0,
  role: 'assistant',
  text: `Bonjour / Hello — I'm **MTL Retail IQ Advisor**, a Fabric Data Agent grounded in **MtlRetailOntology**. I can answer questions about store sales, categories, products, inventory, the ML sales forecast, low-stock risk and reorder requests.

Ask in English or French. Data is **synthetic** and runs to **3 Nov 2026**; I'm read-only and can't place orders.`,
};
function friendlyError(error: unknown): string {
  const detail = error instanceof Error ? error.message : '';
  if (/at least 3 characters|under 1,000 characters/i.test(detail)) return detail;
  return "MTL IQ couldn't answer right now. Try the question again in a moment.";
}

export function Advisor() {
  const [messages, setMessages] = useState<Message[]>([WELCOME]);
  const [question, setQuestion] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const nextId = useRef(1);

  const ask = async (value: string) => {
    const text = value.trim();
    if (text.length < 3 || busy) return;
    const userMessage: Message = { id: nextId.current++, role: 'user', text };
    setMessages(current => [...current, userMessage]);
    setQuestion('');
    setError(null);
    setBusy(true);
    try {
      const result = await askMtlAdvisor(text);
      if (result.status !== 'answered' || !result.answer.trim()) {
        setError(result.message || friendlyError(null));
        return;
      }
      setMessages(current => [...current, {
        id: nextId.current++,
        role: 'assistant',
        text: result.answer,
        generatedAt: result.generatedAt,
      }]);
    } catch (caught) {
      setError(friendlyError(caught));
    } finally {
      setBusy(false);
    }
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    void ask(question);
  };

  return (
    <div className="advisor-layout">
      <section className="advisor-chat panel" aria-label="MTL Retail IQ Advisor chat">
        <div className="advisor-banner">
          <div className="advisor-avatar" aria-hidden="true">IQ</div>
          <div>
            <div className="advisor-title-line">
              <h2>MTL Retail IQ Advisor</h2>
              <span className="advisor-live"><i />PUBLISHED</span>
              <span className="advisor-readonly">READ-ONLY</span>
            </div>
            <p>Fabric Data Agent · grounded in MtlRetailOntology · synthetic data · snapshot 2026-11-03</p>
          </div>
        </div>

        <div className="advisor-messages" aria-live="polite">
          {messages.map(item => (
            <article className={`advisor-message ${item.role}`} key={item.id}>
              <div className="message-avatar" aria-hidden="true">{item.role === 'assistant' ? 'IQ' : 'You'}</div>
              <div className="message-body">
                <div className="message-author">{item.role === 'assistant' ? 'MTL Retail IQ Advisor' : 'You'}</div>
                {item.role === 'assistant'
                  ? <div className="markdown-answer"><ReactMarkdown remarkPlugins={[remarkGfm]}>{item.text}</ReactMarkdown></div>
                  : <p>{item.text}</p>}
                {item.generatedAt && <small>Generated {new Date(item.generatedAt).toLocaleTimeString('en-CA', { hour: '2-digit', minute: '2-digit' })}</small>}
              </div>
            </article>
          ))}
          {busy && (
            <article className="advisor-message assistant">
              <div className="message-avatar" aria-hidden="true">IQ</div>
              <div className="message-body thinking" role="status"><span /><span /><span />Querying the ontology…</div>
            </article>
          )}
        </div>

        {error && <div className="alert error advisor-error" role="alert">{error}</div>}
        <form className="advisor-composer" onSubmit={submit}>
          <label htmlFor="advisor-question" className="sr-only">Ask MTL Retail IQ Advisor</label>
          <textarea
            id="advisor-question"
            value={question}
            onChange={event => setQuestion(event.target.value)}
            onKeyDown={event => {
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault();
                if (question.trim().length >= 3) void ask(question);
              }
            }}
            maxLength={1_000}
            placeholder="Ask about sales, stores, products, stock, forecasts, low-stock risk or reorders — in English or French…"
            rows={3}
            disabled={busy}
          />
          <div className="composer-footer">
            <span>{question.length.toLocaleString()} / 1,000 · Enter to send · Shift+Enter for a new line</span>
            <div>
              {messages.length > 1 && <button className="button secondary" type="button" disabled={busy} onClick={() => { setMessages([WELCOME]); setError(null); }}>Clear</button>}
              <button className="button primary" type="submit" disabled={busy || question.trim().length < 3}>{busy ? 'Thinking…' : 'Ask advisor'}</button>
            </div>
          </div>
        </form>
      </section>

      <aside className="advisor-side">
        <section className="panel">
          <div className="panel-title"><div><h2>Suggested questions</h2><p>Start with a governed retail question</p></div></div>
          <div className="prompt-list">
            {SUGGESTIONS.map((suggestion, index) => (
              <button type="button" key={suggestion} disabled={busy} onClick={() => void ask(suggestion)}>
                <span>{String(index + 1).padStart(2, '0')}</span>{suggestion}
              </button>
            ))}
          </div>
        </section>
        <section className="panel advisor-trust">
          <h2>Why you can trust it</h2>
          <ul>
            <li><strong>Ontology grounded</strong><span>Governed semantic model, Gold lakehouse and ontology, with one business vocabulary.</span></li>
            <li><strong>Control validated</strong><span>20 evaluation questions (EN/FR) checked against deterministic Gold controls.</span></li>
            <li><strong>Bilingual</strong><span>Ask in English or French; answers follow your language.</span></li>
            <li><strong>Read-only</strong><span>It explains evidence and ML recommendations, but cannot place, approve or change orders.</span></li>
          </ul>
          <p>Each message is a fresh grounded query. For auditability, ask “Show me how you calculated that.”</p>
        </section>
      </aside>
    </div>
  );
}
