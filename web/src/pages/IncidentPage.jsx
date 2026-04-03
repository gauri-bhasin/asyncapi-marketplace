import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { apiGet, apiPost } from "../api";

function formatTs(ts) {
  if (!ts) return "";
  try {
    return new Date(ts).toLocaleString();
  } catch {
    return ts;
  }
}

function severityBadgeClass(sev) {
  if (!sev) return "badge badge-outline";
  const value = String(sev).toLowerCase();
  if (value === "critical") return "badge badge-sev-critical";
  if (value === "high") return "badge badge-sev-high";
  if (value === "medium") return "badge badge-sev-medium";
  if (value === "low") return "badge badge-sev-low";
  return "badge badge-outline";
}

function statusBadgeClass(status) {
  if (!status) return "badge badge-outline";
  const value = String(status).toLowerCase();
  if (value.includes("open")) return "badge badge-status-open";
  if (value.includes("investigat")) return "badge badge-status-investigating";
  if (value.includes("closed") || value.includes("resolved")) return "badge badge-status-closed";
  return "badge badge-outline";
}

export default function IncidentPage() {
  const { id } = useParams();
  const [incident, setIncident] = useState(null);
  const [replay, setReplay] = useState(null);
  const [windowMinutes, setWindowMinutes] = useState(30);
  const [recommendations, setRecommendations] = useState([]);
  const [error, setError] = useState("");
  const [loadingIncident, setLoadingIncident] = useState(false);
  const [loadingReplay, setLoadingReplay] = useState(false);
  const [loadingAssist, setLoadingAssist] = useState(false);

  async function loadIncident() {
    setLoadingIncident(true);
    try {
      const data = await apiGet(`/incidents/${id}`);
      setIncident(data);
      setError("");
    } catch (e) {
      setError(String(e));
    } finally {
      setLoadingIncident(false);
    }
  }

  async function loadReplay(nextWindow) {
    if (!incident) return;
    const value = nextWindow ?? windowMinutes;
    setWindowMinutes(value);
    setLoadingReplay(true);
    try {
      const data = await apiGet(`/incidents/${id}/replay?window_minutes=${value}`);
      setReplay(data);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoadingReplay(false);
    }
  }

  async function loadAssist() {
    if (!incident) return;
    setLoadingAssist(true);
    try {
      const goal = `Help me understand incident "${incident.title}" and its deploy + error context.`;
      const resp = await apiPost("/agent/recommend", { goal });
      setRecommendations(resp.recommended_topics || []);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoadingAssist(false);
    }
  }

  useEffect(() => {
    setReplay(null);
    setRecommendations([]);
    loadIncident();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  useEffect(() => {
    if (incident) {
      loadReplay(windowMinutes);
      loadAssist();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [incident]);

  const flatEvents = useMemo(() => {
    if (!replay) return [];
    const deploys = (replay.deploy_events || []).map((e) => ({
      ...e,
      __type: "deploy",
    }));
    const errors = (replay.error_events || []).map((e) => ({
      ...e,
      __type: "error",
    }));
    const stories = (replay.story_events || []).map((e) => ({
      ...e,
      __type: "story",
    }));
    return [...deploys, ...errors, ...stories].sort((a, b) => (a.ts || "").localeCompare(b.ts || ""));
  }, [replay]);

  return (
    <main>
      <section className="card">
        <div className="incident-header">
          <div className="incident-title-row">
            <h2>{incident?.title || `Incident ${id}`}</h2>
            {incident && (
              <>
                <span className={severityBadgeClass(incident.severity)}>{incident.severity}</span>
                <span className={statusBadgeClass(incident.status)}>{incident.status}</span>
              </>
            )}
          </div>
          <div className="incident-meta-row">
            <span className="muted">
              Incident ID <code>{id}</code>
            </span>
            {incident?.created_at && (
              <span className="muted">Created {formatTs(incident.created_at)}</span>
            )}
            {replay?.center_ts && (
              <span className="muted">
                Replay center {formatTs(replay.center_ts)} (±{replay.window_minutes}m)
              </span>
            )}
          </div>
          {error && <pre className="error-box">{error}</pre>}
          {loadingIncident && <div className="timeline-empty">Loading incident…</div>}
        </div>
      </section>

      <div className="incident-grid">
        <section className="card">
          <div className="section-header">
            <h3>Summary</h3>
          </div>
          {!incident && !loadingIncident && (
            <p className="timeline-empty">
              Incident details are not available. Ensure the detector has created incidents in this
              environment.
            </p>
          )}
          {incident && (
            <>
              <p>{incident.summary}</p>
              <div className="pill-row">
                {incident.suspected_deploy_id && (
                  <div className="pill">
                    <span className="pill-label">Suspected deploy</span>{" "}
                    <span className="truncate">{incident.suspected_deploy_id}</span>
                  </div>
                )}
                <div className="pill">
                  <span className="pill-label">Detector confidence</span>{" "}
                  <strong>{Math.round((incident.confidence || 0) * 100)}%</strong>
                </div>
              </div>
            </>
          )}
        </section>

        <section className="card">
          <div className="section-header">
            <h3>AI perspective</h3>
            {loadingAssist && <span className="badge badge-outline">Refreshing…</span>}
          </div>
          {!incident && <div className="timeline-empty">Waiting for incident details…</div>}
          {incident && recommendations.length === 0 && !loadingAssist && (
            <p className="timeline-empty">
              No specific topic recommendations yet. This incident will use semantic context from past
              events to improve over time.
            </p>
          )}
          <ul>
            {recommendations.map((r) => (
              <li key={r.topic}>
                <span className="badge badge-outline">{r.topic}</span>{" "}
                <span className="muted">
                  score {typeof r.score === "number" ? r.score.toFixed(3) : r.score},{" "}
                  {r.recent_event_count != null
                    ? `${r.recent_event_count} recent events`
                    : "semantic only"}
                </span>
              </li>
            ))}
          </ul>
        </section>
      </div>

      <div className="incident-grid">
        <section className="card">
          <div className="section-header">
            <h3>Replay window</h3>
            <div className="row">
              <button
                type="button"
                className="secondary sm-btn"
                onClick={() => loadReplay(15)}
                disabled={loadingReplay}
              >
                ±15m
              </button>
              <button
                type="button"
                className="secondary sm-btn"
                onClick={() => loadReplay(30)}
                disabled={loadingReplay}
              >
                ±30m
              </button>
              <button
                type="button"
                className="secondary sm-btn"
                onClick={() => loadReplay(60)}
                disabled={loadingReplay}
              >
                ±60m
              </button>
            </div>
          </div>
          {loadingReplay && <div className="timeline-empty">Loading correlated events…</div>}
          {!loadingReplay && flatEvents.length === 0 && (
            <div className="timeline-empty">
              No deploy, error, or story events found around this incident in the selected window.
            </div>
          )}
          <ul className="timeline-list">
            {flatEvents.map((evt) => {
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
            <h3>Incident story</h3>
          </div>
          <ul>
            {(incident?.stories || []).length === 0 && (
              <li className="timeline-empty">
                No narrative stories have been generated yet for this incident.
              </li>
            )}
            {(incident?.stories || []).map((s) => (
              <li key={s.id}>
                <div className="muted">{formatTs(s.ts)}</div>
                <div>{s.story_text}</div>
              </li>
            ))}
          </ul>
        </section>
      </div>
    </main>
  );
}
