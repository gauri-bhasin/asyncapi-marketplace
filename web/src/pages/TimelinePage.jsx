import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { apiGet, getSelectedTopic, wsUrl } from "../api";

const DEPLOY_TOPIC = "marketplace.ops.github.deployment.v1";
const ERROR_TOPIC = "marketplace.ops.sentry.error_event.v1";
const STORY_TOPIC = "marketplace.ops.incident.story.v1";

function formatTs(ts) {
  if (!ts) return "";
  try {
    return new Date(ts).toLocaleString();
  } catch {
    return ts;
  }
}

export default function TimelinePage() {
  const [deploys, setDeploys] = useState([]);
  const [errors, setErrors] = useState([]);
  const [stories, setStories] = useState([]);
  const [incidents, setIncidents] = useState([]);
  const [status, setStatus] = useState("disconnected");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [envFilter, setEnvFilter] = useState("");
  const [serviceFilter, setServiceFilter] = useState("");
  const wsRef = useRef(null);
  const reconnectRef = useRef(null);

  async function loadInitial() {
    setLoading(true);
    try {
      const [d, e, s, i] = await Promise.all([
        apiGet(`/topics/${encodeURIComponent(DEPLOY_TOPIC)}/history?limit=50`),
        apiGet(`/topics/${encodeURIComponent(ERROR_TOPIC)}/history?limit=50`),
        apiGet(`/topics/${encodeURIComponent(STORY_TOPIC)}/history?limit=50`),
        apiGet("/incidents"),
      ]);
      setDeploys(d || []);
      setErrors(e || []);
      setStories(s || []);
      setIncidents(i || []);
      setError("");
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  function connect() {
    if (wsRef.current) wsRef.current.close();
    const topic = getSelectedTopic() || "marketplace.ops.>";
    const ws = new WebSocket(wsUrl(topic.endsWith(".v1") ? "marketplace.ops.>" : topic));
    wsRef.current = ws;
    setStatus("connecting");
    ws.onopen = () => setStatus("connected");
    ws.onclose = () => {
      setStatus("reconnecting");
      reconnectRef.current = setTimeout(connect, 1500);
    };
    ws.onerror = () => setStatus("error");
    ws.onmessage = (evt) => {
      const row = JSON.parse(evt.data);
      if (row.type === "heartbeat") return;
      if (row.topic === DEPLOY_TOPIC) setDeploys((prev) => [row, ...prev].slice(0, 100));
      if (row.topic === ERROR_TOPIC) setErrors((prev) => [row, ...prev].slice(0, 100));
      if (row.topic === STORY_TOPIC) setStories((prev) => [row, ...prev].slice(0, 100));
    };
  }

  useEffect(() => {
    loadInitial();
    connect();
    return () => {
      if (reconnectRef.current) clearTimeout(reconnectRef.current);
      if (wsRef.current) wsRef.current.close();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const allEvents = useMemo(() => {
    const wrap = (rows, type) =>
      (rows || []).map((row) => ({
        ...row,
        __type: type,
      }));
    const combined = [...wrap(deploys, "deploy"), ...wrap(errors, "error"), ...wrap(stories, "story")];
    combined.sort((a, b) => (b.ts || "").localeCompare(a.ts || ""));
    return combined;
  }, [deploys, errors, stories]);

  const envOptions = useMemo(() => {
    const set = new Set();
    allEvents.forEach((e) => {
      const env = e.tags_json?.env;
      if (env) set.add(env);
    });
    return Array.from(set).sort();
  }, [allEvents]);

  const serviceOptions = useMemo(() => {
    const set = new Set();
    allEvents.forEach((e) => {
      const svc = e.tags_json?.service;
      if (svc) set.add(svc);
    });
    return Array.from(set).sort();
  }, [allEvents]);

  const filteredEvents = useMemo(() => {
    return allEvents.filter((evt) => {
      const env = evt.tags_json?.env;
      const service = evt.tags_json?.service;
      if (envFilter && env !== envFilter) return false;
      if (serviceFilter && service !== serviceFilter) return false;
      return true;
    });
  }, [allEvents, envFilter, serviceFilter]);

  return (
    <main>
      <section className="card">
        <div className="section-header">
          <h3>Live operational timeline</h3>
          <span className={`badge ${status === "connected" ? "ok" : "warn"}`}>{status}</span>
        </div>
        <p className="muted">
          A unified stream of deploy markers, Sentry errors, and incident stories. Use environment and
          service filters to zoom in on a slice of your stack.
        </p>
        <div className="row">
          <select value={envFilter} onChange={(e) => setEnvFilter(e.target.value)}>
            <option value="">All environments</option>
            {envOptions.map((env) => (
              <option key={env} value={env}>
                {env}
              </option>
            ))}
          </select>
          <select value={serviceFilter} onChange={(e) => setServiceFilter(e.target.value)}>
            <option value="">All services</option>
            {serviceOptions.map((svc) => (
              <option key={svc} value={svc}>
                {svc}
              </option>
            ))}
          </select>
          <button
            type="button"
            className="secondary sm-btn"
            onClick={() => {
              setEnvFilter("");
              setServiceFilter("");
            }}
          >
            Clear filters
          </button>
        </div>
        {loading && <div className="timeline-empty">Loading recent history…</div>}
        {error && <pre className="error-box">{error}</pre>}
      </section>

      <div className="layout-two-column">
        <section className="card">
          <div className="section-header">
            <h4>Event stream</h4>
            <span className="muted">{filteredEvents.length} events</span>
          </div>
          {filteredEvents.length === 0 && !loading && (
            <div className="timeline-empty">
              No events yet. Once GitHub and Sentry webhooks are connected, new activity will appear here.
            </div>
          )}
          <ul className="timeline-list">
            {filteredEvents.map((evt) => {
              const isDeploy = evt.__type === "deploy";
              const isError = evt.__type === "error";
              const isStory = evt.__type === "story";
              const dotStyle = {
                backgroundColor: isDeploy ? "#38bdf8" : isError ? "#f97316" : "#a855f7",
              };
              const badgeClass = isDeploy
                ? "badge badge-neutral"
                : isError
                ? "badge badge-yellow"
                : "badge badge-outline";
              const label = isDeploy ? "Deploy" : isError ? "Error" : "Story";
              const env = evt.tags_json?.env;
              const repo = evt.tags_json?.repo;
              const commit = evt.tags_json?.commit;
              const fingerprint = evt.tags_json?.fingerprint;

              return (
                <li key={evt.event_id} className="timeline-item">
                  <div className="timeline-type-dot" style={dotStyle} />
                  <div>
                    <div>
                      <span className={badgeClass}>{label}</span>{" "}
                      <span className="muted">{formatTs(evt.ts)}</span>
                    </div>
                    <div className="timeline-meta">
                      {repo && <span>repo {repo}</span>}
                      {commit && <span>commit {commit.slice(0, 7)}</span>}
                      {env && <span>env {env}</span>}
                      {fingerprint && <span>fingerprint {fingerprint}</span>}
                    </div>
                    {isStory && (
                      <div className="muted">
                        {evt.payload_json?.story_text ||
                          JSON.stringify(evt.payload_json || {}, null, 2)}
                      </div>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
        </section>

        <section className="card">
          <div className="section-header">
            <h4>Incidents</h4>
            <span className="muted">{(incidents || []).length} detected</span>
          </div>
          <p className="muted">
            Detector-created incidents summarizing correlated deploys and error spikes. Click into an
            incident to see a full replay and agent context.
          </p>
          <ul>
            {(incidents || []).length === 0 && (
              <li className="timeline-empty">
                No incidents detected yet. Trigger a deploy and error spike to generate one.
              </li>
            )}
            {(incidents || []).map((inc) => (
              <li key={inc.id}>
                <Link to={`/incidents/${inc.id}`}>{inc.title}</Link>{" "}
                <span className="badge badge-outline">{inc.severity}</span>{" "}
                <span className="muted">{inc.status}</span>
              </li>
            ))}
          </ul>
        </section>
      </div>
    </main>
  );
}
