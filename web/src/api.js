const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

export function getApiKey() {
  return localStorage.getItem("marketplace_api_key") || "";
}

export function setApiKey(key) {
  localStorage.setItem("marketplace_api_key", key);
}

export function getUsername() {
  return localStorage.getItem("marketplace_username") || "";
}

export function setUsername(name) {
  localStorage.setItem("marketplace_username", name);
}

// V1 compat
export async function issueApiKey() {
  const resp = await fetch(`${API_BASE}/apikeys`, { method: "POST" });
  const data = await resp.json();
  setApiKey(data.api_key);
  return data.api_key;
}

// V2: create user + initial key
export async function createUser(username, displayName = "") {
  const resp = await fetch(`${API_BASE}/users`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, display_name: displayName }),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }));
    throw new Error(err.detail || resp.statusText);
  }
  const data = await resp.json();
  setApiKey(data.api_key);
  setUsername(data.user.username);
  return data;
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
