import { useEffect, useState } from "react";
import { apiGet, apiPost, apiDelete, getApiKey } from "../api";

export default function ApiKeysPage() {
  const [keys, setKeys] = useState([]);
  const [label, setLabel] = useState("");
  const [newKey, setNewKey] = useState("");
  const [error, setError] = useState("");
  const hasKey = !!getApiKey();

  async function load() {
    try {
      const rows = await apiGet("/me/apikeys");
      setKeys(rows);
      setError("");
    } catch (e) {
      setError(String(e));
    }
  }

  async function handleCreate() {
    try {
      const data = await apiPost("/me/apikeys", { label: label || "unnamed" });
      setNewKey(data.api_key);
      setLabel("");
      await load();
    } catch (e) {
      setError(String(e));
    }
  }

  async function handleRotate(id) {
    try {
      const data = await apiPost(`/me/apikeys/${id}/rotate`, {});
      setNewKey(data.api_key);
      await load();
    } catch (e) {
      setError(String(e));
    }
  }

  async function handleRevoke(id) {
    if (!confirm("Revoke this key? This cannot be undone.")) return;
    try {
      await apiDelete(`/me/apikeys/${id}`);
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
          <h3>API Keys</h3>
          <p>Create an account first from the Catalog page.</p>
        </section>
      </main>
    );
  }

  return (
    <main>
      <section className="card">
        <h3>My API Keys</h3>

        <div style={{ display: "flex", gap: 8, marginBottom: 12, flexWrap: "wrap" }}>
          <input
            placeholder="Key label (optional)"
            value={label}
            onChange={(e) => setLabel(e.target.value)}
          />
          <button onClick={handleCreate}>Create Key</button>
        </div>

        {newKey && (
          <div className="highlight-box">
            New key (copy now, it won't be shown again): <code>{newKey}</code>
          </div>
        )}

        <table>
          <thead>
            <tr>
              <th>ID</th>
              <th>Label</th>
              <th>Status</th>
              <th>Created</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {keys.map((k) => (
              <tr key={k.id}>
                <td>{k.id}</td>
                <td>{k.label || "—"}</td>
                <td>{k.revoked ? "Revoked" : "Active"}</td>
                <td>{new Date(k.created_at).toLocaleString()}</td>
                <td>
                  {!k.revoked && (
                    <>
                      <button className="sm-btn" onClick={() => handleRotate(k.id)}>
                        Rotate
                      </button>
                      <button className="sm-btn danger" onClick={() => handleRevoke(k.id)}>
                        Revoke
                      </button>
                    </>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      {error && <pre className="error-box">{error}</pre>}
    </main>
  );
}
