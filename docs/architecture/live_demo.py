"""Demo machine pool as code (mingrammer/diagrams + Graphviz). Regenerate after a change:

    uv run --with diagrams python docs/architecture/live_demo.py

Writes docs/architecture/live_demo.png. Source of truth: api/src/nightlight_api/live.py and scripts/live_pool/
(lease in a Firestore transaction, custom token bound to the lease, idle 15 min / hard 60 min, golden-snapshot
restore, sweep stops VMs without a live lease). Mermaid version: live_demo.mmd."""

from pathlib import Path

from diagrams import Cluster, Diagram, Edge
from diagrams.firebase.develop import Authentication
from diagrams.gcp.compute import ComputeEngine, Run
from diagrams.gcp.database import Firestore
from diagrams.gcp.devtools import Scheduler
from diagrams.gcp.security import IAP
from diagrams.gcp.storage import PersistentDisk
from diagrams.onprem.client import User

OUT = Path(__file__).with_name("live_demo")
GRAPH = {"fontname": "Helvetica-Bold", "fontsize": "26", "pad": "0.5", "nodesep": "0.6", "ranksep": "1.2",
         "size": "16,9!", "ratio": "fill", "dpi": "160", "bgcolor": "white", "splines": "spline",
         "labelloc": "t", "label": "Demo machines: a real server per visitor, reset after every visit\n "}
NODE = {"fontname": "Helvetica", "fontsize": "18"}
CLUSTER = {"fontname": "Helvetica-Bold", "fontsize": "17", "margin": "18"}
INNER = {**CLUSTER, "bgcolor": "#ffffff", "fontsize": "15"}
RESET = "#c0392b"


def E(**kw):  # Edge() sets its own font size, so a graph-wide edge_attr does not reach the labels
    return Edge(**{"fontsize": "17", "fontname": "Helvetica", "color": "#5f6b7a", "penwidth": "1.6", **kw})


with Diagram("", filename=str(OUT), outformat="png", show=False, direction="LR", graph_attr=GRAPH, node_attr=NODE):
    with Cluster("Visitor", graph_attr={**CLUSTER, "bgcolor": "#f3f0ff"}):
        visitor = User("Browser")

    with Cluster("Google Cloud", graph_attr={**CLUSTER, "bgcolor": "#eef4ff"}):
        auth = Authentication("Firebase Authentication\npool account login")
        api = Run("API (Cloud Run)\nlease, release, sweep")
        db = Firestore("Firestore\nslot leases (transaction)\nidle 15 min, hard cap 60 min")
        sweep = Scheduler("Cloud Scheduler\nsweep every 5 min")
        with Cluster("Compute Engine pool (asia-northeast3-a): 5 x e2-small, stopped when idle", graph_attr=INNER):
            vms = ComputeEngine("nl-live-1 .. nl-live-5\nsmall home server, Docker apps,\nsigned helper paired\nto its own pool account")
            golden = PersistentDisk("Golden snapshot\nper VM\n(nl-live-N-golden)")
        iap = IAP("IAP-only SSH\n(operators; no other\ninbound)")

    visitor >> E(label="1. ask for a machine;\n4. get a custom token\n(lease id as a claim)") >> api
    api >> E(label="2. lease a free slot") >> db
    api >> E(label="3. start on demand") >> vms
    visitor >> E(label="5. sign in with it; the login\nends when the lease ends", style="dashed") >> auth
    vms >> E(label="helper reports outward\nlike any device", constraint="false") >> api
    api >> E(label="release: wipe app data,\nrestore boot disk, stop", color=RESET, fontcolor=RESET) >> golden
    golden >> E(label="restore", color=RESET, fontcolor=RESET, style="dashed") >> vms
    sweep >> E(label="expired leases,\nstop orphan VMs") >> api
    iap >> E(style="dotted") >> vms
