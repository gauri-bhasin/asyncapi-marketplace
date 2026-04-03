import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { apiGet, apiPost, getApiKey, issueApiKey, setSelectedTopic } from "../api";

export default function HomePage() {
  const navigate = useNavigate();
  const [topics, setTopics] = useState([]);
  const [incidents, setIncidents] = useState([]);
  const [keyword, setKeyword] = useState("");
  const [semanticQuery, setSemanticQuery] = useState("");
  const [semanticResults, setSemanticResults] = useState([]);
  const [goal, setGoal] = useState("");
  const [recommendations, setRecommendations] = useState([]);
  const [apiKey, setApiKeyState] = useState(getApiKey());
  const [loading, setLoading] = useState(false);
  const [semanticLoading, setSemanticLoading] = useState(false);
  const [assistLoading, setAssistLoading] = useState(false);
  const [error, setError] = useState("");

  async function loadData() {
    if (!apiKey) return;
    setLoading(true);
    try {
      const [rows, inc] = await Promise.all([apiGet("/topics"), apiGet("/incidents")]);
      setTopics(rows);
      setIncidents(inc || []);
      setError("");
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  async function handleKey() {
    const key = await issueApiKey();
    setApiKeyState(key);
    await loadData();
  }

  async function runSemanticSearch() {
    if (!semanticQuery.trim()) return;
    setSemanticLoading(true);
    try {
      const resp = await apiPost("/search/semantic", { query: semanticQuery });
      setSemanticResults(resp.results || []);
    } catch (e) {
      setError(String(e));
    } finally {
      setSemanticLoading(false);
    }
  }

  async function runAssist() {
    if (!goal.trim()) return;
    setAssistLoading(true);
    try {
      const resp = await apiPost("/agent/recommend", { goal });
      setRecommendations(resp.recommended_topics || []);
    } catch (e) {
      setError(String(e));
    } finally {
      setAssistLoading(false);
    }
  }

  function openTopic(topic) {
    setSelectedTopic(topic);
    navigate(`/topics/${encodeURIComponent(topic)}`);
  }

  useEffect(() => {
    loadData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiKey]);

  const filtered = useMemo(() => {
    const key = keyword.toLowerCase().trim();
    if (!key) return topics;
    return topics.filter((t) => {
      return (
        t.name.toLowerCase().includes(key) ||
        t.description.toLowerCase().includes(key) ||
        (t.tags || []).join(" ").toLowerCase().includes(key)
      );
    });
  }, [topics, keyword]);

  const activeIncidents = (incidents || []).slice(0, 3);

  return (
    <main>
      {!apiKey && (
        <section className="card">
          <div className="section-header">
            <h3>Welcome to SignalHub</h3>
            <span className="badge badge-neutral">Demo mode</span>
          </div>
          <p>
            Issue a short-lived API key to explore deploys, errors, incidents, and AI recommendations in a
            unified operational timeline.
          </p>
          <button onClick={handleKey}>Create API Key</button>
        </section>
      )}

      {apiKey && (
        <>
          <section className="card">
            <div className="section-header">
              <h3>Operational overview</h3>
              <span className="muted">
                {activeIncidents.length > 0 ? `${activeIncidents.length} recent incidents` : "No recent incidents"}
              </span>
            </div>
            <div className="pill-row">
              <div className="pill">
                <span className="pill-label">Catalog topics</span>{" "}
                <strong>{topics.length || 0}</strong>
              </div>
              <div className="pill">
                <span className="pill-label">API key</span>{" "}
                <span className="truncate">{apiKey}</span>
              </div>
              {activeIncidents[0] && (
                <div className="pill">
                  <span className="pill-label">Newest incident</span>{" "}
                  <span className="truncate">{activeIncidents[0].title}</span>
                </div>
              )}
            </div>
          </section>

          <div className="layout-two-column">
            <section className="card">
              <div className="section-header">
                <h3>Topic catalog</h3>
                {loading && <span className="badge badge-outline">Loading…</span>}
              </div>
              <p className="muted">
                Browse normalized operational topics backed by AsyncAPI schemas. Use search to jump to a
                deploy, error, or incident story stream.
              </p>
              <input
                placeholder="Filter by name, tag, or description"
                value={keyword}
                onChange={(e) => setKeyword(e.target.value)}
              />
              {filtered.length === 0 && !loading && (
                <div className="timeline-empty">
                  No topics match <code>{keyword}</code>. Try clearing the filter.
                </div>
              )}
              <ul>
                {filtered.map((topic) => (
                  <li key={topic.name}>
                    <Link to={`/topics/${encodeURIComponent(topic.name)}`}>{topic.name}</Link>{" "}
                    <span className="muted">· {topic.description}</span>
                  </li>
                ))}
              </ul>
            </section>

            <section className="card">
              <div className="section-header">
                <h3>Active incidents</h3>
                <button
                  type="button"
                  className="secondary sm-btn"
                  onClick={() => navigate("/timeline")}
                >
                  Open live timeline
                </button>
              </div>
              {activeIncidents.length === 0 && (
                <div className="timeline-empty">
                  No incidents yet. Once deploys and errors are ingested, new incidents will appear here.
                </div>
              )}
              <ul>
                {activeIncidents.map((inc) => (
                  <li key={inc.id}>
                    <Link to={`/incidents/${inc.id}`}>{inc.title}</Link>{" "}
                    <span className="badge badge-outline">{inc.severity}</span>{" "}
                    <span className="muted">{inc.status}</span>
                  </li>
                ))}
              </ul>
            </section>
          </div>

          <div className="layout-two-column">
            <section className="card">
              <div className="section-header">
                <h3>Semantic search</h3>
                {semanticLoading && <span className="badge badge-outline">Searching…</span>}
              </div>
              <p className="muted">
                Ask natural-language questions about your operational history. SignalHub searches a
                Chroma-backed index of past events.
              </p>
              <input
                placeholder="e.g. deploy related errors in staging"
                value={semanticQuery}
                onChange={(e) => setSemanticQuery(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && runSemanticSearch()}
              />
              <button onClick={runSemanticSearch} disabled={semanticLoading}>
                Run search
              </button>
              <ul>
                {semanticResults.length === 0 && !semanticLoading && (
                  <li className="timeline-empty">No semantic matches yet. Try a broader query.</li>
                )}
                {semanticResults.map((r, idx) => (
                  <li key={`${r.metadata?.topic}-${idx}`}>
                    <strong>{r.metadata?.topic || "unknown topic"}</strong> ·{" "}
                    <span className="muted">{r.snippet}</span>
                  </li>
                ))}
              </ul>
            </section>

            <section className="card">
              <div className="section-header">
                <h3>Agent assist</h3>
                {assistLoading && <span className="badge badge-outline">Thinking…</span>}
              </div>
              <p className="muted">
                Describe an operational goal and let the agent recommend the most relevant topics to
                subscribe and replay.
              </p>
              <input
                placeholder="e.g. monitor deploy impact in prod"
                value={goal}
                onChange={(e) => setGoal(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && runAssist()}
              />
              <button onClick={runAssist} disabled={assistLoading}>
                Recommend topics
              </button>
              <ul>
                {recommendations.length === 0 && !assistLoading && (
                  <li className="timeline-empty">
                    No recommendations yet. Start by describing what you want to understand.
                  </li>
                )}
                {recommendations.map((r) => (
                  <li key={r.topic}>
                    <Link to={`/topics/${encodeURIComponent(r.topic)}`}>{r.topic}</Link>{" "}
                    <span className="muted">
                      score {typeof r.score === "number" ? r.score.toFixed(3) : r.score}
                    </span>{" "}
                    <button className="sm-btn" onClick={() => openTopic(r.topic)}>
                      Open stream
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          </div>
        </>
      )}

      {error && <pre className="error-box">{error}</pre>}
    </main>
  );
}
