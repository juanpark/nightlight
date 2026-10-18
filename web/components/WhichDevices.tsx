// "Which devices?": what Nightlight supports today and what comes next, as in docs/DEVICE-SUPPORT.md (the source of
// truth). Shared by the start screen and Add a device.
export default function WhichDevices({ label = "Which devices?" }: { label?: string }) {
  return (
    <details className="small which-devices">
      <summary className="muted">{label}</summary>
      <ul style={{ margin: "6px 0", paddingLeft: 20 }}>
        <li><strong>Looked after</strong> (the helper runs on it): Mac (macOS 10.15+), Linux with systemd: Raspberry Pi
          OS, Ubuntu, Debian and most others.</li>
        <li><strong>Watched from one of those</strong> (nothing installed): routers, NAS boxes, printers, TVs, cameras,
          phones, Windows PCs.</li>
        <li><strong>Watched from the cloud</strong>: websites.</li>
        <li><strong>Coming next</strong>: Windows, NAS boxes (Synology, QNAP, Unraid, TrueNAS), a Linux installer; later
          Linux without systemd.</li>
      </ul>
    </details>
  );
}
