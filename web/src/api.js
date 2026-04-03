const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

export function getApiKey() {
  return localStorage.getItem("signalhub_api_key") || "";
}

export function setApiKey(key) {
  localStorage.setItem("signalhub_api_key", key);
}

export function getSelectedTopic() {
  return localStorage.getItem("signalhub_selected_topic") || "";
}

export function setSelectedTopic(name) {
  localStorage.setItem("signalhub_selected_topic", name);
}

export async function issueApiKey() {
  const resp = await fetch(`${API_BASE}/apikeys`, { method: "POST" });
  const data = await resp.json();
  setApiKey(data.api_key);
  return data.api_key;
}

export async function apiGet(path) {
  const resp = await fetch(`${API_BASE}${path}`, {
    headers: { "X-API-Key": getApiKey() },
  });
  if (!resp.ok) throw new Error(await resp.text());
  return resp.json();
}

export async function apiPost(path, body) {
  const resp = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-API-Key": getApiKey(),
    },
    body: JSON.stringify(body),
  });
  if (!resp.ok) throw new Error(await resp.text());
  return resp.json();
}

export async function apiPatch(path, body) {
  const resp = await fetch(`${API_BASE}${path}`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
      "X-API-Key": getApiKey(),
    },
    body: JSON.stringify(body),
  });
  if (!resp.ok) throw new Error(await resp.text());
  return resp.json();
}

export async function apiDelete(path) {
  const resp = await fetch(`${API_BASE}${path}`, {
    method: "DELETE",
    headers: { "X-API-Key": getApiKey() },
  });
  if (!resp.ok) throw new Error(await resp.text());
  return resp.json();
}

export function wsUrl(topic) {
  const base = API_BASE.replace("http://", "ws://").replace("https://", "wss://");
  return `${base}/ws/subscribe?topic=${encodeURIComponent(topic)}&api_key=${encodeURIComponent(getApiKey())}`;
}
