import { useEffect, useState } from "react";
import { apiGet, apiPost, getApiKey } from "../api";

export default function DlqPage() {
  const [data, setData] = useState({ items: [], total: 0 });
  const [offset, setOffset] = useState(0);
  const [statusFilter, setStatusFilter] = useState("all");
  const [error, setError] = useState("");
  const limit = 25;
  const hasKey = !!getApiKey();

  async function load(off = offset) {
    try {
      const resp = await apiGet(`/ops/dlq?limit=${limit}&offset=${off}&status=${statusFilter}`);
      setData(resp);
      setError("");
    } catch (e) {
      setError(String(e));
    }
  }

  async function handleReplay(id) {
    try {
      await apiPost(`/ops/dlq/${id}/replay`, {});
      await load();
    } catch (e) {
      setError(String(e));
    }
  }

  useEffect(() => {
    if (hasKey) load(0);
    setOffset(0);
  }, [hasKey, statusFilter]);

  function nextPage() {
    const next = offset + limit;
    setOffset(next);
    load(next);
  }

  function prevPage() {
    const prev = Math.max(0, offset - limit);
    setOffset(prev);
    load(prev);
  }

  if (!hasKey) {
    return (
      <main>
        <section className="card">
          <h3>Dead Letter Queue</h3>
          <p>Authenticate first from the Catalog page.</p>
        </section>
      </main>
    );
  }

  return (
    <main>
      <section className="card">
        <h3>Dead Letter Queue</h3>

        <div style={{ display: "flex", gap: 8, marginBottom: 12, alignItems: "center" }}>
          <label>Filter:</label>
          <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
            <option value="all">All</option>
            <option value="pending">Pending</option>
            <option value="replayed">Replayed</option>
          </select>
          <span className="muted">
            Showing {offset + 1}–{Math.min(offset + limit, data.total)} of {data.total}
          </span>
        </div>

        <table>
          <thead>
            <tr>
              <th>ID</th>
              <th>Topic</th>
              <th>Reason</th>
              <th>Created</th>
              <th>Status</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((item) => (
              <tr key={item.id}>
                <td>{item.id}</td>
                <td>{item.topic}</td>
                <td className="truncate">{item.reason}</td>
                <td>{new Date(item.created_at).toLocaleString()}</td>
                <td>
                  <span className={`badge ${item.replayed ? "badge-green" : "badge-red"}`}>
                    {item.replayed ? "Replayed" : "Pending"}
                  </span>
                </td>
                <td>
                  {!item.replayed && (
                    <button className="sm-btn" onClick={() => handleReplay(item.id)}>
                      Replay
                    </button>
                  )}
                </td>
              </tr>
            ))}
            {data.items.length === 0 && (
              <tr>
                <td colSpan={6} style={{ textAlign: "center", opacity: 0.6 }}>
                  No DLQ events
                </td>
              </tr>
            )}
          </tbody>
        </table>

        <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
          <button className="sm-btn" onClick={prevPage} disabled={offset === 0}>
            Prev
          </button>
          <button className="sm-btn" onClick={nextPage} disabled={offset + limit >= data.total}>
            Next
          </button>
        </div>
      </section>
      {error && <pre className="error-box">{error}</pre>}
    </main>
  );
}
