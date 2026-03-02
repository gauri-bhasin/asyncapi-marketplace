import { useEffect, useState } from "react";
import { apiGet, apiPatch, apiPost, getApiKey } from "../api";

export default function SubscriptionsPage() {
  const [subs, setSubs] = useState([]);
  const [topic, setTopic] = useState("");
  const [error, setError] = useState("");
  const hasKey = !!getApiKey();

  async function load() {
    try {
      const rows = await apiGet("/me/subscriptions");
      setSubs(rows);
      setError("");
    } catch (e) {
      setError(String(e));
    }
  }

  async function handleCreate() {
    if (!topic.trim()) return;
    try {
      await apiPost("/subscriptions", { topic: topic.trim() });
      setTopic("");
      await load();
    } catch (e) {
      setError(String(e));
    }
  }

  async function toggleStatus(sub) {
    const next = sub.status === "ACTIVE" ? "PAUSED" : "ACTIVE";
    try {
      await apiPatch(`/subscriptions/${sub.id}`, { status: next });
      await load();
    } catch (e) {
      setError(String(e));
    }
  }

  useEffect(() => {
    if (hasKey) load();
  }, [hasKey]);

  if (!hasKey) {
    return (
      <main>
        <section className="card">
          <h3>Subscriptions</h3>
          <p>Create an account first from the Catalog page.</p>
        </section>
      </main>
    );
  }

  return (
    <main>
      <section className="card">
        <h3>My Subscriptions</h3>

        <div style={{ display: "flex", gap: 8, marginBottom: 12, flexWrap: "wrap" }}>
          <input
            placeholder="Topic name"
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
          />
          <button onClick={handleCreate}>Subscribe</button>
        </div>

        <table>
          <thead>
            <tr>
              <th>ID</th>
              <th>Topic</th>
              <th>Status</th>
              <th>Created</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {subs.map((s) => (
              <tr key={s.id}>
                <td>{s.id}</td>
                <td>{s.topic}</td>
                <td>
                  <span className={`badge ${s.status === "ACTIVE" ? "badge-green" : "badge-yellow"}`}>
                    {s.status}
                  </span>
                </td>
                <td>{new Date(s.created_at).toLocaleString()}</td>
                <td>
                  <button className="sm-btn" onClick={() => toggleStatus(s)}>
                    {s.status === "ACTIVE" ? "Pause" : "Resume"}
                  </button>
                </td>
              </tr>
            ))}
            {subs.length === 0 && (
              <tr>
                <td colSpan={5} style={{ textAlign: "center", opacity: 0.6 }}>
                  No subscriptions yet
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </section>
      {error && <pre className="error-box">{error}</pre>}
    </main>
  );
}
