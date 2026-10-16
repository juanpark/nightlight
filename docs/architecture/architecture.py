"""Nightlight's architecture as code (mingrammer/diagrams + Graphviz). Regenerate after a change:

    uv run --with diagrams python docs/architecture/architecture.py

Writes docs/architecture/architecture.png (README and deck use it)."""

from pathlib import Path

from diagrams import Cluster, Diagram, Edge
from diagrams.firebase.develop import Authentication
from diagrams.gcp.compute import Run
from diagrams.gcp.database import Firestore
from diagrams.gcp.devtools import Scheduler
from diagrams.gcp.ml import VertexAI
from diagrams.onprem.client import Users
from diagrams.onprem.compute import Server
from diagrams.programming.framework import Nextjs
from diagrams.programming.language import Python

OUT = Path(__file__).with_name("architecture")
GRAPH = {"fontname": "Helvetica", "fontsize": "22", "pad": "0.4", "nodesep": "0.9", "ranksep": "1.3", "size": "16,9!", "ratio": "compress", "dpi": "220",
         "bgcolor": "white", "splines": "spline"}
NODE = {"fontname": "Helvetica", "fontsize": "13"}
EDGE = {"fontname": "Helvetica", "fontsize": "11", "color": "#5f6b7a"}

with Diagram("Nightlight", filename=str(OUT), outformat="png", show=False, direction="LR",
             graph_attr=GRAPH, node_attr=NODE, edge_attr=EDGE):
    owner = Users("Owner\n(browser)")

    with Cluster("Home and small office", graph_attr={"bgcolor": "#fff8ec", "fontsize": "15"}):
        devices = Server("Your devices\nRaspberry Pi, Mac mini,\nMacBook...")
        helper = Python("Nightlight helper\ndials out; runs only\nwhat the device allows")

    with Cluster("Google Cloud", graph_attr={"bgcolor": "#eef4ff", "fontsize": "15"}):
        auth = Authentication("Firebase Auth")
        with Cluster("Cloud Run", graph_attr={"bgcolor": "#ffffff"}):
            web = Nextjs("Web app")
            api = Run("API + ADK agent\nplaybooks, approvals")
        db = Firestore("Firestore\nlive state")
        with Cluster("Agent Platform", graph_attr={"bgcolor": "#ffffff"}):
            gemini = VertexAI("Gemini")
            memory = VertexAI("Memory Bank")
        sweep = Scheduler("Cloud Scheduler\nevery 5 min")

    owner >> Edge(label="sign in") >> auth
    owner >> Edge(label="map, chat, approve") >> web >> api
    db >> Edge(label="live updates", style="dashed") >> owner
    api >> Edge(label="tools, words") >> gemini
    api >> memory
    api >> Edge(label="one transaction\nper approval") >> db
    sweep >> Edge(label="silent devices,\nwebsites") >> api
    devices - Edge(style="dotted") - helper
    helper >> Edge(label="reports, job results\n(HTTPS, scrubbed)") >> api
    api >> Edge(label="job names, signed updates\n(never commands)", style="dashed") >> helper
