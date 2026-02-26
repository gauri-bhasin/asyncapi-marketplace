import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { apiGet, apiPost, getApiKey, issueApiKey } from "../api";

export default function HomePage() {
  const navigate = useNavigate();
  const [topics, setTopics] = useState([]);
  const [keyword, setKeyword] = useState("");
  const [goal, setGoal] = useState("");
  const [recommendations, setRecommendations] = useState([]);
  const [apiKey, setApiKeyState] = useState(getApiKey());
  const [error, setError] = useState("");

  async function loadTopics() {
    try {
      const rows = await apiGet("/topics");
      setTopics(rows);
      setError("");
    } catch (e) {
      setError(String(e));
    }
  }

  async function initApiKey() {
    const key = await issueApiKey();
    setApiKeyState(key);
    await loadTopics();
  }

  async function runAssist() {
    const resp = await apiPost("/agent/recommend", { goal });
    setRecommendations(resp.recommended_topics || []);
  }

  function openAndSubscribe(topic) {
    navigate(`/topic/${encodeURIComponent(topic)}?auto_subscribe=1`);
  }

  useEffect(() => {
    if (apiKey) loadTopics();
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

  return (
    <main>
      {!apiKey && (
        <section className="card">
          <h3>Get Started</h3>
          <button onClick={initApiKey}>Issue API Key</button>
        </section>
      )}

      {apiKey && (
        <>
          <section className="card">
            <h3>Topic Catalog</h3>
            <input
              placeholder="Keyword search"
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
            />
            <ul>
              {filtered.map((topic) => (
                <li key={topic.name}>
                  <Link to={`/topic/${encodeURIComponent(topic.name)}`}>{topic.name}</Link> -{" "}
                  {topic.description}
                </li>
              ))}
            </ul>
          </section>
          <section className="card">
            <h3>Agent Assist</h3>
            <input
              placeholder="e.g. Track BTC price spikes"
              value={goal}
              onChange={(e) => setGoal(e.target.value)}
            />
            <button onClick={runAssist}>Recommend Topics</button>
            <ul>
              {recommendations.map((r) => (
                <li key={r.topic}>
                  <Link to={`/topic/${encodeURIComponent(r.topic)}`}>{r.topic}</Link> ({r.score?.toFixed(3)})
                  <button onClick={() => openAndSubscribe(r.topic)}>One-click subscribe</button>
                </li>
              ))}
            </ul>
          </section>
        </>
      )}
      {error && <pre>{error}</pre>}
    </main>
  );
}
