const API_BASE = "";

export async function postJson(path, payload) {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload || {}),
  });
  const txt = await res.text();
  let data = {};
  try {
    data = JSON.parse(txt);
  } catch {
    data = { error: txt };
  }
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

export async function getJson(path) {
  const res = await fetch(`${API_BASE}${path}`, { credentials: "include" });
  const txt = await res.text();
  let data = {};
  try {
    data = JSON.parse(txt);
  } catch {
    data = { error: txt };
  }
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}
