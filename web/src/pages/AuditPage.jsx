import { useEffect, useState } from "react";
import { apiGet, getApiKey } from "../api";

export default function AuditPage() {
  const [data, setData] = useState({ items: [], total: 0 });
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState("");
  const limit = 50;
  const hasKey = !!getApiKey();

  async function load(off = offset) {
    try {
      const resp = await apiGet(`/ops/audit?limit=${limit}&offset=${off}`);
      setData(resp);
      setError("");
    } catch (e) {
      setError(String(e));
    }
  }

  useEffect(() => {
    if (hasKey) load(0);
  }, [hasKey]);

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
          <h3>Audit Log</h3>
          <p>Authenticate first from the Catalog page.</p>
        </section>
      </main>
    );
  }

  return (
    <main>
      <section className="card">
        <h3>Audit Log</h3>
        <p className="muted">
          Showing {offset + 1}–{Math.min(offset + limit, data.total)} of {data.total}
        </p>

        <table>
          <thead>
            <tr>
              <th>ID</th>
              <th>Action</th>
              <th>Details</th>
              <th>Time</th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((item) => (
              <tr key={item.id}>
                <td>{item.id}</td>
                <td>{item.action}</td>
                <td className="truncate">
                  <code>{JSON.stringify(item.details)}</code>
                </td>
                <td>{new Date(item.created_at).toLocaleString()}</td>
              </tr>
            ))}
            {data.items.length === 0 && (
              <tr>
                <td colSpan={4} style={{ textAlign: "center", opacity: 0.6 }}>
                  No audit entries
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
