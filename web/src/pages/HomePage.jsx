import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { apiGet, apiPost, createUser, getApiKey, getUsername, issueApiKey, setApiKey } from "../api";

export default function HomePage() {
  const navigate = useNavigate();
  const [topics, setTopics] = useState([]);
  const [keyword, setKeyword] = useState("");
  const [goal, setGoal] = useState("");
  const [recommendations, setRecommendations] = useState([]);
  const [apiKey, setApiKeyState] = useState(getApiKey());
  const [username, setUsernameState] = useState(getUsername());
  const [newUsername, setNewUsername] = useState("");
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

  async function handleCreateUser() {
    if (!newUsername.trim()) return;
    try {
      const data = await createUser(newUsername.trim());
      setApiKeyState(data.api_key);
      setUsernameState(data.user.username);
      setError("");
      await loadTopics();
    } catch (e) {
      setError(String(e));
    }
  }

  async function handleLegacyKey() {
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
          <p>Create a developer account to access the marketplace.</p>
          <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            <input
              placeholder="Choose a username"
              value={newUsername}
              onChange={(e) => setNewUsername(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleCreateUser()}
            />
            <button onClick={handleCreateUser}>Create Account</button>
          </div>
          <p className="muted" style={{ marginTop: 8 }}>
            Or{" "}
            <button className="link-btn" onClick={handleLegacyKey}>
              issue an anonymous API key
            </button>
          </p>
        </section>
      )}

      {apiKey && (
        <>
          {username && (
            <p className="muted" style={{ marginBottom: 8 }}>
              Signed in as <strong>{username}</strong>
            </p>
          )}
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
      {error && <pre className="error-box">{error}</pre>}
    </main>
  );
}
