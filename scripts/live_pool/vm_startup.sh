#!/bin/sh
# Startup script for the live-demo pool VMs (nl-live-N). Google's guest agent runs it as root on EVERY boot.
# First boot: provision from the "demo-files" metadata (base64 tgz: setup.sh, demo, opt-demo/). Every boot: (re)install
# the demo agent, which resets the home and then applies the scenario in "demo-command".
# Freestyle changes a visitor makes are not undone here: when a lease ends, or the visitor chooses "Start fresh", the
# API restores the whole boot disk from this VM's golden snapshot (live.py), so every visitor starts from that copy.
set -eu
MD=http://metadata.google.internal/computeMetadata/v1/instance/attributes
hostnamectl set-hostname homeserver 2>/dev/null || true  # every pool machine looks like the same small home server
if [ ! -x /usr/local/bin/demo ]; then
  rm -rf /tmp/demo-files && mkdir -p /tmp/demo-files
  curl -fsS -H 'Metadata-Flavor: Google' "$MD/demo-files" | base64 -d | tar xzf - -C /tmp/demo-files
  sh /tmp/demo-files/setup.sh > /var/log/demo-setup.log 2>&1
fi
cat > /usr/local/bin/demo-agent <<'AGENT'
#!/bin/sh
# Applies "demo-command" (scenario:nonce) from instance metadata: `demo reset`, then crash|disk|unhealthy|leftovers
# (or nothing for "none"). Progress goes back as the guest attribute demo/state ("resetting|ready:<nonce>:<unix time>"),
# read by the API with compute.instances.getGuestAttributes. Outgoing only (the metadata server); nothing listens.
MD=http://metadata.google.internal/computeMetadata/v1/instance/attributes/demo-command
GA=http://metadata.google.internal/computeMetadata/v1/instance/guest-attributes/demo/state
ga() { curl -fsS -X PUT --data "$1:$(date +%s)" -H 'Metadata-Flavor: Google' "$GA" >/dev/null 2>&1 || true; }
# The first read returns the current command at once (etag 0), so every boot also starts with a reset.
last=""
etag=0
while :; do
  body=$(curl -fsS -D /run/demo-agent.h -H 'Metadata-Flavor: Google' \
    "$MD?wait_for_change=true&last_etag=$etag&timeout_sec=300" 2>/dev/null) || { sleep 5; etag=0; continue; }
  etag=$(awk 'tolower($1)=="etag:"{print $2}' /run/demo-agent.h | tr -d '\r')
  [ -n "$etag" ] || etag=0
  [ "$body" = "$last" ] && continue
  last=$body
  scen=${body%%:*}
  nonce=${body#*:}
  ga "resetting:$nonce"
  demo reset >/dev/null 2>&1 || true
  case "$scen" in
    crash|disk|unhealthy|leftovers)
      logger -t demo-agent "reset, break $scen"
      demo break "$scen" >/dev/null 2>&1 || logger -t demo-agent "break $scen failed" ;;
    *) logger -t demo-agent "reset" ;;
  esac
  ga "ready:$nonce"
  # The helper reports at start, so a restart puts the fresh state on the map now instead of at its next heartbeat.
  systemctl restart nightlight-helper >/dev/null 2>&1 || true
  logger -t demo-agent "ready $nonce"
done
AGENT
chmod 0755 /usr/local/bin/demo-agent
cat > /etc/systemd/system/demo-agent.service <<'UNIT'
[Unit]
Description=Nightlight live-demo scenario agent (metadata driven)
After=docker.service network-online.target
Wants=docker.service network-online.target
[Service]
ExecStart=/usr/local/bin/demo-agent
Restart=always
RestartSec=5
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable demo-agent >/dev/null 2>&1
systemctl restart demo-agent
