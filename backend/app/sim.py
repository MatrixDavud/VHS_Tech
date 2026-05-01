from __future__ import annotations

import math
from typing import Any

from .network_store import NetworkStore


def simulate_bus_lane_impact(store: NetworkStore, road_id: str) -> dict[str, Any]:
    """GNN-lite heuristic.

    Rules (hackathon demo):
    - Treat `road_id` as the bus-lane segment.
    - Find all roads connected by shared nodes (u/v), pick the 3 nearest by centroid distance.
    - In optimized mode, apply a global improvement scale (makes map greener),
      but increase traffic on the 3 nearest connected roads by 20%.
    """

    road_id = str(road_id)
    ref = store.get_road_ref(road_id)
    origin = store.centroids.get(road_id)

    connected: set[str] = set()
    if ref.u is not None:
        connected.update(store.roads_by_node.get(ref.u, []))
    if ref.v is not None:
        connected.update(store.roads_by_node.get(ref.v, []))

    connected.discard(road_id)

    if origin is None:
        nearest = sorted(connected)[:3]
    else:
        def dist_m(other_id: str) -> float:
            other = store.centroids.get(other_id)
            if other is None:
                return float("inf")
            return haversine_m(origin, other)

        nearest = sorted(connected, key=dist_m)[:3]

    return {
        "bus_lane_road_id": road_id,
        "increased_roads": nearest,
        "optimized_scale": 0.80,
        "neighbor_multiplier": 1.20,
        "bus_lane_congestion": 0.20,
        "congestion_score_before": 0.80,
        "congestion_score_after": 0.65,
    }


def haversine_m(a_latlon: tuple[float, float], b_latlon: tuple[float, float]) -> float:
    """Distance in meters between (lat, lon) pairs."""

    lat1, lon1 = a_latlon
    lat2, lon2 = b_latlon

    r = 6_371_000.0

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    h = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))
