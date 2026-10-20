import { useCallback, useEffect, useState } from "react";
import { api } from "../lib/api";

// The paired PC this browser works with (pinned once chosen) and its detected games.
export default function usePC(poll = 8000, wantId = null) {
  if (wantId && localStorage.getItem("ws-device") !== wantId) localStorage.setItem("ws-device", wantId);
  const [devices, setDevices] = useState(null);
  const [games, setGames] = useState([]);
  const pinned = localStorage.getItem("ws-device");
  const device = devices ? devices.find((d) => d.id === pinned && !d.revoked) || devices.find((d) => d.online) || devices[0] || null : undefined;
  const load = useCallback(async () => {
    const r = await api.get("/devices").catch(() => ({ data: [] }));
    setDevices(r.data);
  }, []);
  useEffect(() => { load(); const t = setInterval(load, poll); return () => clearInterval(t); }, [load, poll]);
  const id = device?.id;
  useEffect(() => {
    if (!id) return undefined;
    localStorage.setItem("ws-device", id);
    const g = () => api.get(`/devices/${id}/games`).then((r) => setGames(r.data)).catch(() => {});
    g();
    const t = setInterval(g, poll);
    return () => clearInterval(t);
  }, [id, poll]);
  return { device, devices, games, reload: load };
}
