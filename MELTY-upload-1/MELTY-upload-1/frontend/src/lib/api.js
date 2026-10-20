import axios from "axios";

export const BACKEND = process.env.REACT_APP_BACKEND_URL;
export const api = axios.create({ baseURL: `${BACKEND}/api` });

export const errMsg = (e) => {
  const d = e?.response?.data?.detail;
  if (Array.isArray(d)) return d.map((x) => x.msg).join(", ");
  return d || e?.message || "Something went wrong";
};
export const usd = (n, d = 4) => `$${Number(n || 0).toFixed(d)}`;
export const ago = (iso) => {
  if (!iso) return "—";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return `${Math.round(s)}s ago`;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return new Date(iso).toLocaleDateString();
};
export const ASPECTS = [
  { key: "mechanics", label: "Mechanics" },
  { key: "world_structure", label: "World" },
  { key: "progression", label: "Progression" },
  { key: "atmosphere", label: "Atmosphere" },
  { key: "visual_style", label: "Visual style" },
  { key: "characters", label: "Characters" },
  { key: "audio", label: "Audio" },
];
export const ROLES = [
  { key: "asset-source", label: "Asset source", hint: "models, sounds or textures read from your install at runtime" },
  { key: "mechanic-inspiration", label: "Mechanic inspiration", hint: "behaviour re-implemented in the host, no files read" },
];
