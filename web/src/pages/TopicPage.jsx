import { useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { apiGet, getSelectedTopic, setSelectedTopic, wsUrl } from "../api";

function formatTs(ts) {
  if (!ts) return "";
  try {
    return new Date(ts).toLocaleString();
  } catch {
    return ts;
  }
}

export default function TopicPage() {
  const { name } = useParams();
  const decoded = useMemo(() => decodeURIComponent(name || getSelectedTopic()), [name]);
  const [topic, setTopic] = useState(null);
  const [history, setHistory] = useState([]);
  const [replay, setReplay] = useState([]);
  const [wsState, setWsState] = useState("disconnected");
  const [feed, setFeed] = useState([]);
  const [since, setSince] = useState("");
  const [until, setUntil] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const wsRef = useRef(null);
  const reconnectRef = useRef(null);

  async function loadTopic() {
    setLoading(true);
    try {
      const data = await apiGet(`/topics/${encodeURIComponent(decoded)}`);
      setTopic(data);
      setSelectedTopic(decoded);
      const hist = await apiGet(`/topics/${encodeURIComponent(decoded)}/history?limit=100`);
      setHistory(hist || []);
      setError("");
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  async function runReplay() {
    try {
      const data = await apiGet(
        `/topics/${encodeURIComponent(decoded)}/replay?since=${encodeURIComponent(
          since,
        )}&until=${encodeURIComponent(until)}`,
      );
      setReplay(data || []);
    } catch (e) {
      setError(String(e));
    }
  }

  function connectWs() {
    if (!decoded) return;
    if (wsRef.current) wsRef.current.close();
    const ws = new WebSocket(wsUrl(decoded));
    wsRef.current = ws;
    setWsState("connecting");
    ws.onopen = () => setWsState("connected");
    ws.onclose = () => {
      setWsState("reconnecting");
      reconnectRef.current = setTimeout(connectWs, 1500);
    };
    ws.onerror = () => setWsState("error");
    ws.onmessage = (event) => {
      const row = JSON.parse(event.data);
      if (row.type === "heartbeat") return;
      setFeed((prev) => [...prev.slice(-199), row]);
    };
  }

  function presetMinutes(minutes) {
    const end = new Date();
    const start = new Date(end.getTime() - minutes * 60 * 1000);
    setSince(start.toISOString());
    setUntil(end.toISOString());
  }

  useEffect(() => {
    loadTopic();
    connectWs();
    return () => {
      if (reconnectRef.current) clearTimeout(reconnectRef.current);
      if (wsRef.current) wsRef.current.close();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [decoded]);

  const topicKind =
    decoded && decoded.includes("github.deployment")
      ? "Deploy"
      : decoded && decoded.includes("sentry.error")
      ? "Error"
      : decoded && decoded.includes("incident.story")
      ? "Story"
      : "Topic";

  return (
    <main>
      <section className="card">
        <div className="section-header">
          <h2>{decoded}</h2>
          <span className={`badge ${wsState === "connected" ? "ok" : "warn"}`}>WS: {wsState}</span>
        </div>
        <p className="muted">
          {topic?.description ||
            "AsyncAPI-backed stream describing a normalized operational signal in the SignalHub catalog."}
        </p>
        <div className="pill-row">
          <div className="pill">
            <span className="pill-label">Kind</span> {topicKind}
          </div>
          <div className="pill">
            <span className="pill-label">Known tags</span>{" "}
            {(topic?.tags || []).slice(0, 4).join(", ") || "n/a"}
          </div>
        </div>
        {loading && <div className="timeline-empty">Loading topic details…</div>}
        {error && <pre className="error-box">{error}</pre>}
      </section>

      <div className="layout-two-column">
        <section className="card">
          <div className="section-header">
            <h4>Recent events</h4>
            <span className="muted">{history.length} rows</span>
          </div>
          <table>
            <thead>
              <tr>
                <th>ts</th>
                <th>source</th>
                <th>env</th>
                <th>event_id</th>
              </tr>
            </thead>
            <tbody>
              {history.length === 0 && (
                <tr>
                  <td colSpan={4} className="timeline-empty">
                    No recent events yet for this topic.
                  </td>
                </tr>
              )}
              {history.map((row) => (
                <tr key={row.event_id}>
                  <td>{formatTs(row.ts)}</td>
                  <td>{row.source}</td>
                  <td>{row.tags_json?.env}</td>
                  <td className="truncate">{row.event_id}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        <section className="card">
          <div className="section-header">
            <h4>Schema</h4>
          </div>
          <pre>{JSON.stringify(topic?.asyncapi_json || {}, null, 2)}</pre>
        </section>
      </div>

      <section className="card">
        <div className="section-header">
          <h4>Live feed</h4>
        </div>
        <p className="muted">
          Real-time events delivered over WebSocket for this topic. Use this view while triggering deploys
          or errors from your tools.
        </p>
        <div className="feed">
          {feed.map((item) => (
            <pre key={item.event_id || item.ts}>{JSON.stringify(item, null, 2)}</pre>
          ))}
        </div>
      </section>

      <section className="card">
        <div className="section-header">
          <h4>Replay window</h4>
        </div>
        <p className="muted">
          Choose a time window to reconstruct the exact sequence of events on this topic. This is the same
          mechanism used by the incident hero screen.
        </p>
        <div className="row">
          <input
            placeholder="since ISO8601"
            value={since}
            onChange={(e) => setSince(e.target.value)}
          />
          <input
            placeholder="until ISO8601"
            value={until}
            onChange={(e) => setUntil(e.target.value)}
          />
          <button onClick={() => presetMinutes(30)}>Last 30m</button>
          <button onClick={() => presetMinutes(60)}>Last 60m</button>
          <button onClick={runReplay}>Replay</button>
        </div>
        {replay.length === 0 ? (
          <div className="timeline-empty">
            No replay loaded. Select a window and click <code>Replay</code>.
          </div>
        ) : (
          <pre>{JSON.stringify(replay, null, 2)}</pre>
        )}
      </section>
    </main>
  );
}
