import { useEffect, useMemo, useRef, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { apiGet, wsUrl } from "../api";

export default function TopicPage() {
  const { topicName } = useParams();
  const [searchParams] = useSearchParams();
  const decoded = useMemo(() => decodeURIComponent(topicName), [topicName]);
  const [topic, setTopic] = useState(null);
  const [history, setHistory] = useState([]);
  const [replay, setReplay] = useState([]);
  const [wsState, setWsState] = useState("disconnected");
  const [feed, setFeed] = useState([]);
  const [since, setSince] = useState("");
  const [until, setUntil] = useState("");
  const wsRef = useRef(null);
  const feedRef = useRef(null);

  async function loadTopic() {
    const data = await apiGet(`/topics/${encodeURIComponent(decoded)}`);
    setTopic(data);
  }

  async function loadHistory() {
    const data = await apiGet(`/topics/${encodeURIComponent(decoded)}/history?limit=100`);
    setHistory(data);
  }

  async function runReplay() {
    const data = await apiGet(
      `/topics/${encodeURIComponent(decoded)}/replay?since=${encodeURIComponent(since)}&until=${encodeURIComponent(until)}`
    );
    setReplay(data);
  }

  function connectWs() {
    if (wsRef.current) wsRef.current.close();
    const ws = new WebSocket(wsUrl(decoded));
    wsRef.current = ws;
    ws.onopen = () => setWsState("connected");
    ws.onclose = () => setWsState("disconnected");
    ws.onerror = () => setWsState("error");
    ws.onmessage = (event) => {
      const row = JSON.parse(event.data);
      setFeed((prev) => [...prev.slice(-199), row]);
    };
  }

  useEffect(() => {
    loadTopic();
    loadHistory();
    if (searchParams.get("auto_subscribe") === "1") {
      setTimeout(() => connectWs(), 400);
    }
    return () => {
      if (wsRef.current) wsRef.current.close();
    };
  }, [decoded, searchParams]);

  useEffect(() => {
    if (feedRef.current) {
      feedRef.current.scrollTop = feedRef.current.scrollHeight;
    }
  }, [feed]);

  return (
    <main>
      <section className="card">
        <h2>{decoded}</h2>
        <p>{topic?.description}</p>
        <h4>Schema / Spec</h4>
        <pre>{JSON.stringify(topic?.asyncapi_json || {}, null, 2)}</pre>
      </section>
      <section className="card">
        <h4>Connect</h4>
        <button onClick={connectWs}>Subscribe WebSocket</button>
        <span>Status: {wsState}</span>
      </section>
      <section className="card">
        <h4>Live Feed</h4>
        <div className="feed" ref={feedRef}>
          {feed.map((item) => (
            <pre key={item.event_id}>{JSON.stringify(item, null, 2)}</pre>
          ))}
        </div>
      </section>
      <section className="card">
        <h4>History (last 100)</h4>
        <table>
          <thead>
            <tr>
              <th>ts</th>
              <th>event_id</th>
              <th>source</th>
            </tr>
          </thead>
          <tbody>
            {history.map((row) => (
              <tr key={row.event_id}>
                <td>{row.ts}</td>
                <td>{row.event_id}</td>
                <td>{row.source}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      <section className="card">
        <h4>Replay</h4>
        <input placeholder="since ISO" value={since} onChange={(e) => setSince(e.target.value)} />
        <input placeholder="until ISO" value={until} onChange={(e) => setUntil(e.target.value)} />
        <button onClick={runReplay}>Replay</button>
        <pre>{JSON.stringify(replay, null, 2)}</pre>
      </section>
    </main>
  );
}
