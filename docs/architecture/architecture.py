"""Nightlight's architecture as code (mingrammer/diagrams + Graphviz). Regenerate after a change:

    uv run --with diagrams python docs/architecture/architecture.py

Writes docs/architecture/architecture.png (README and deck use it). Every box is checked against the code:
config.py and deploy_api.sh (model, thinking, Memory Bank, sweep), research.py (Search grounding), auth.py and
expert.py (Firebase Auth, passkeys), main.py (/helper/*, /internal/sweep), deploy_*.sh (`gcloud run deploy --source`,
which builds with Cloud Build into Artifact Registry). No Secret Manager: the API needs no secrets."""

from pathlib import Path

from diagrams import Cluster, Diagram, Edge
from diagrams.firebase.develop import Authentication
from diagrams.gcp.compute import Run
from diagrams.gcp.database import Firestore
from diagrams.gcp.devtools import Build, ContainerRegistry, Scheduler
from diagrams.gcp.ml import VertexAI
from diagrams.gcp.security import KeyManagementService
from diagrams.onprem.client import User
from diagrams.onprem.compute import Server
from diagrams.programming.framework import Nextjs
from diagrams.programming.language import Python

OUT = Path(__file__).with_name("architecture")
GRAPH = {"fontname": "Helvetica-Bold", "fontsize": "26", "pad": "0.5", "nodesep": "0.55", "ranksep": "1.1",
         "size": "16,9!", "ratio": "fill", "dpi": "160", "bgcolor": "white", "splines": "spline",
         "labelloc": "t", "label": "Nightlight: how the pieces talk\n "}
NODE = {"fontname": "Helvetica", "fontsize": "18"}
EDGE = {"fontname": "Helvetica", "fontsize": "16", "color": "#5f6b7a", "fontcolor": "#2b3440", "penwidth": "1.6"}
CLUSTER = {"fontname": "Helvetica-Bold", "fontsize": "17", "margin": "18"}
INNER = {**CLUSTER, "bgcolor": "#ffffff", "fontsize": "15"}
CONTROL = "#c0392b"  # the control path: approval taps and signed things


def E(**kw):  # Edge() sets its own font size, so the graph-wide edge_attr alone does not reach the labels
    return Edge(**{"fontsize": "17", "fontname": "Helvetica", **kw})


with Diagram("", filename=str(OUT), outformat="png", show=False, direction="LR",
             graph_attr=GRAPH, node_attr=NODE, edge_attr=EDGE):
    with Cluster("Owner", graph_attr={**CLUSTER, "bgcolor": "#f3f0ff"}):
        owner = User("Browser\nmap, chat,\napproval cards")
        passkey = KeyManagementService("Passkey (WebAuthn)\nsigns expert commands")

    with Cluster("Google Cloud", graph_attr={**CLUSTER, "bgcolor": "#eef4ff"}):
        auth = Authentication("Firebase Authentication\nGoogle sign-in,\nanonymous demo")
        with Cluster("Cloud Run (asia-northeast3)", graph_attr=INNER):
            web = Nextjs("Web app\nNext.js")
            api = Run("API: FastAPI + ADK agent\napproval cards, trust ladder,\nbudgets, signed helper release")
        db = Firestore("Firestore\ndevices, cards, trust,\nchats, quotas")
        sweep = Scheduler("Cloud Scheduler\nevery 5 min")
        with Cluster("Google Agent Platform", graph_attr=INNER):
            gemini = VertexAI("Gemini 3.8 Flash\nQuick: low thinking\nInvestigate: medium thinking")
            memory = VertexAI("Memory Bank\nfacts per person")
            search = VertexAI("Google Search\ngrounding\n(research)")
        with Cluster("Deploy (gcloud run deploy --source)", graph_attr=INNER):
            build = Build("Cloud Build")
            registry = ContainerRegistry("Artifact Registry\nimages")

    with Cluster("Owner's devices (Linux, macOS)", graph_attr={**CLUSTER, "bgcolor": "#fff8ec"}):
        helper = Python("Signed helper\nsystemd / launchd\nno open ports")
        apps = Server("Apps and services\nDocker, systemd")

    owner >> E(label="page, /config") >> web
    owner >> E(label="sign in") >> auth
    owner >> E(label="ID token: chat,\ntap to approve", color=CONTROL, fontcolor=CONTROL) >> api
    passkey >> E(label="signed command", color=CONTROL, fontcolor=CONTROL, style="dashed") >> api
    db >> E(label="read-only listeners\n(own data only)", style="dashed", constraint="false") >> owner

    api >> E(label="one transaction\nper approval") >> db
    api >> E(label="tools, capped\noutput + thinking") >> gemini
    api >> memory
    api >> E(label="20/day") >> search
    sweep >> E(label="/internal/sweep\n(Google-signed token)") >> api
    build >> registry >> E(label="deploy", style="dotted") >> api

    helper >> E(label="report every minute\n(outgoing HTTPS only)", constraint="false") >> api
    api >> E(label="job name + target, only after a tap;\nsigned release (helper checks signature)",
                color=CONTROL, fontcolor=CONTROL, style="dashed") >> helper
    helper >> E(label="fixed jobs,\nlocal allow-list", style="dotted") >> apps
