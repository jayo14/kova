from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse, urlunparse


def normalize_url(url: str) -> str:
    try:
        parsed = urlparse(url)
        # Normalize scheme/host case, drop fragments, normalize trailing slash
        scheme = parsed.scheme.lower()
        netloc = parsed.netloc.lower()
        path = parsed.path or "/"
        if path != "/" and path.endswith("/"):
            path = path.rstrip("/")
        query = parsed.query
        normalized = urlunparse((scheme, netloc, path, parsed.params, query, ""))
        return normalized
    except Exception:
        return url


def compute_state_fingerprint(observation: dict[str, Any] | None) -> str:
    if not observation:
        return "empty"
    parts: list[str] = []
    for key in ["title", "headings", "forms", "primary_actions", "interactive_elements", "routes"]:
        if key in observation:
            try:
                parts.append(json.dumps(observation[key], sort_keys=True))
            except Exception:
                parts.append(str(observation[key]))
    raw = "||".join(parts)
    return hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()[:16]


@dataclass
class SiteNode:
    node_id: str
    url: str
    url_norm: str
    fingerprint: str
    title: str | None = None
    headings: list[dict] = field(default_factory=list)
    forms: list[dict] = field(default_factory=list)
    primary_actions: list[dict] = field(default_factory=list)
    interactive_elements: list[dict] = field(default_factory=list)
    needs_auth: bool = False
    screenshot_ref: str | None = None
    visited_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SiteEdge:
    edge_id: str
    from_node_id: str
    to_node_id: str
    action: dict[str, Any]
    created_at: float = 0.0


class SiteMap:
    def __init__(self):
        self.nodes: dict[str, SiteNode] = {}
        self.edges: list[SiteEdge] = []
        self._url_to_node: dict[str, str] = {}  # normalized key -> node_id

    def get_or_create_node(self, url: str, observation: dict[str, Any] | None = None) -> SiteNode:
        url_norm = normalize_url(url)
        fp = compute_state_fingerprint(observation)
        key = f"{url_norm}::{fp}"
        if key in self._url_to_node:
            node_id = self._url_to_node[key]
            node = self.nodes[node_id]
            node.visited_count += 1
            if observation:
                if observation.get("title") and not node.title:
                    node.title = observation.get("title")
                if observation.get("needs_auth") is not None:
                    node.needs_auth = bool(observation.get("needs_auth"))
                if observation.get("screenshot_ref"):
                    node.screenshot_ref = observation.get("screenshot_ref")
            return node

        node_id = hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]
        node = SiteNode(
            node_id=node_id,
            url=url,
            url_norm=url_norm,
            fingerprint=fp,
            title=(observation or {}).get("title"),
            headings=(observation or {}).get("headings") or [],
            forms=(observation or {}).get("forms") or [],
            primary_actions=(observation or {}).get("primary_actions") or [],
            interactive_elements=(observation or {}).get("interactive_elements") or [],
            needs_auth=bool((observation or {}).get("needs_auth")),
            screenshot_ref=(observation or {}).get("screenshot_ref"),
            visited_count=1,
            metadata={},
        )
        self.nodes[node_id] = node
        self._url_to_node[key] = node_id
        return node

    def add_edge(self, from_node_id: str, to_node_id: str, action: dict[str, Any]) -> SiteEdge:
        import time

        edge_id = hashlib.sha256(f"{from_node_id}:{to_node_id}:{json.dumps(action, sort_keys=True)}".encode("utf-8")).hexdigest()[:12]
        edge = SiteEdge(edge_id=edge_id, from_node_id=from_node_id, to_node_id=to_node_id, action=action, created_at=time.time())
        self.edges.append(edge)
        return edge

    def get_frontier(self) -> list[str]:
        # Return node ids not fully explored or with low visit count
        frontier = []
        for nid, node in self.nodes.items():
            if node.visited_count < 3:
                frontier.append(nid)
        return frontier

    def has_new_state_from_branch(self, node_id: str) -> bool:
        # Simple heuristic: if we've seen this exact node fingerprint recently with no new edges producing unseen fingerprints
        node = self.nodes.get(node_id)
        if not node:
            return False
        # Consider it productive if visited_count small or has forms/actions
        if node.visited_count <= 1:
            return True
        if node.forms or node.primary_actions or node.interactive_elements:
            return True
        return False

    def summarize(self) -> dict[str, Any]:
        return {
            "nodes": [
                {
                    "node_id": n.node_id,
                    "url": n.url_norm,
                    "title": n.title,
                    "fingerprint": n.fingerprint,
                    "needs_auth": n.needs_auth,
                    "forms": len(n.forms),
                    "actions": len(n.primary_actions),
                    "interactive": len(n.interactive_elements),
                    "visited_count": n.visited_count,
                }
                for n in self.nodes.values()
            ],
            "edges": [
                {"edge_id": e.edge_id, "from": e.from_node_id, "to": e.to_node_id, "action": e.action}
                for e in self.edges
            ],
        }
