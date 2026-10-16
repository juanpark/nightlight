"use client";
import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { firebase } from "@/lib/firebase";

const HELPER_URL = "https://raw.githubusercontent.com/juanpark/nightlight/main/helper/nightlight_helper.py";

function Copy({ text }: { text: string }) {
  const [done, setDone] = useState(false);
  return (
    <div style={{ display: "flex", gap: 8, alignItems: "center", margin: "6px 0" }}>
      <pre style={{ flex: 1, margin: 0, padding: 8, background: "var(--bg)", borderRadius: 8, overflowX: "auto" }}>{text}</pre>
      <button onClick={() => navigator.clipboard.writeText(text).then(() => setDone(true))}>{done ? "Copied" : "Copy"}</button>
    </div>
  );
}

export default function AddDevice({ anonymous, onSave }: { anonymous: boolean; onSave: () => void }) {
  const [code, setCode] = useState<{ code: string; expiresAt: string } | null>(null);
  const [apiUrl, setApiUrl] = useState("");
  const [err, setErr] = useState("");
  useEffect(() => { firebase().then(({ config }) => setApiUrl(config.apiUrl)); }, []);
  if (anonymous) {
    return (
      <div className="panel">
        <h3>Add a real device</h3>
        <p>Real devices stay linked to your account, so first save this home with Google.</p>
        <button className="primary" onClick={onSave}>Save with Google</button>
      </div>
    );
  }
  return (
    <div className="panel">
      <h3>Add a real device</h3>
      <p className="small">A small helper on your device reports its health (disk, memory, what is running). It never
        sends passwords, logs, file contents or network addresses, and it changes nothing unless you allow a job on the
        device itself and then approve it here.</p>
      {!code
        ? <button className="primary" onClick={() => api<{ code: string; expiresAt: string }>("POST",
            "/api/devices/enrol-code", {}).then(setCode).catch((e) => setErr(e instanceof ApiError ? e.code : "error"))}>
            Get a one-time code</button>
        : (
          <>
            <p className="small muted">On the device (Linux, Raspberry Pi or Mac), run these. The code works once, for 10
              minutes.</p>
            <Copy text={`curl -fsSLO ${HELPER_URL}`} />
            <Copy text={`python3 nightlight_helper.py enrol ${apiUrl} ${code.code}`} />
            <Copy text="python3 nightlight_helper.py run" />
            <p className="small muted">Optional: let Nightlight restart one container after you approve it:</p>
            <Copy text="python3 nightlight_helper.py allow restart_container <container-name>" />
          </>
        )}
      {err && <p className="small" style={{ color: "var(--crit)" }}>{err}</p>}
    </div>
  );
}
