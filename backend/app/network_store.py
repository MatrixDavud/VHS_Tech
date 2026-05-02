from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RoadRef:
    edge_id: str
    u: str | None
    v: str | None


class NetworkStore:
    def __init__(self, geojson_path: Path) -> None:
        self.geojson_path = geojson_path

        self.geojson: dict[str, Any] | None = None
        self.roads: dict[str, dict[str, Any]] = {}
        self.roads_by_node: dict[str, list[str]] = {}
        self.centroids: dict[str, tuple[float, float]] = {}

        self._mtime: float | None = None

    @property
    def is_loaded(self) -> bool:
        return self.geojson is not None

    def try_load(self) -> None:
        try:
            self.load()
        except Exception:
            return

    def ensure_loaded(self) -> None:
        if self.geojson is None:
            self.load()
            return

        try:
            mtime = self.geojson_path.stat().st_mtime
        except FileNotFoundError:
            raise

        if self._mtime is not None and mtime > self._mtime:
            self.load()

    def load(self) -> None:
        if not self.geojson_path.exists():
            raise FileNotFoundError(
                f"Network GeoJSON not found: {self.geojson_path}. "
                "Run data/export_osm.py to generate it."
            )

        raw = json.loads(self.geojson_path.read_text(encoding="utf-8"))
        features = raw.get("features") or []

        roads: dict[str, dict[str, Any]] = {}
        roads_by_node: dict[str, list[str]] = {}
        centroids: dict[str, tuple[float, float]] = {}

        for feature in features:
            props = feature.get("properties") or {}
            edge_id = props.get("edge_id") or props.get("road_id")
            if edge_id is None:
                continue

            edge_id = str(edge_id)
            roads[edge_id] = feature

            u = props.get("u")
            v = props.get("v")

            if u is not None:
                roads_by_node.setdefault(str(u), []).append(edge_id)
            if v is not None:
                roads_by_node.setdefault(str(v), []).append(edge_id)

            centroid = geometry_centroid_latlon(feature.get("geometry"))
            if centroid is not None:
                centroids[edge_id] = centroid

        self.geojson = raw
        self.roads = roads
        self.roads_by_node = roads_by_node
        self.centroids = centroids
        self._mtime = self.geojson_path.stat().st_mtime

    def get_road(self, edge_id: str) -> dict[str, Any]:
        return self.roads[str(edge_id)]

    def get_road_ref(self, edge_id: str) -> RoadRef:
        feature = self.get_road(edge_id)
        props = feature.get("properties") or {}
        u = props.get("u")
        v = props.get("v")
        return RoadRef(edge_id=str(edge_id), u=str(u) if u is not None else None, v=str(v) if v is not None else None)

    def bfs_distances(self, source_ids: set[str], max_depth: int = 6) -> dict[str, int]:
        """BFS over the road graph starting from a set of source road IDs.

        Returns a dict of road_id -> hop distance from the nearest source.
        Roads not reachable within max_depth are omitted.
        """
        from collections import deque

        visited: dict[str, int] = {}
        queue: deque[tuple[str, int]] = deque()

        for road_id in source_ids:
            if road_id in self.roads:
                visited[road_id] = 0
                queue.append((road_id, 0))

        while queue:
            current_id, depth = queue.popleft()
            if depth >= max_depth:
                continue

            ref = self.get_road_ref(current_id)
            neighbor_road_ids: set[str] = set()

            if ref.u is not None:
                neighbor_road_ids.update(self.roads_by_node.get(ref.u, []))
            if ref.v is not None:
                neighbor_road_ids.update(self.roads_by_node.get(ref.v, []))

            for neighbor_id in neighbor_road_ids:
                if neighbor_id not in visited:
                    visited[neighbor_id] = depth + 1
                    queue.append((neighbor_id, depth + 1))

        return visited


def geometry_centroid_latlon(geometry: dict[str, Any] | None) -> tuple[float, float] | None:
    """Return centroid as (lat, lon) for LineString / MultiLineString."""

    if not geometry:
        return None

    coords: list[list[float]] = []
    gtype = geometry.get("type")

    if gtype == "LineString":
        coords = geometry.get("coordinates") or []
    elif gtype == "MultiLineString":
        lines = geometry.get("coordinates") or []
        for line in lines:
            coords.extend(line)
    else:
        return None

    if not coords:
        return None

    lon_sum = 0.0
    lat_sum = 0.0

    for lon, lat in coords:
        lon_sum += float(lon)
        lat_sum += float(lat)

    n = float(len(coords))
    return (lat_sum / n, lon_sum / n)
