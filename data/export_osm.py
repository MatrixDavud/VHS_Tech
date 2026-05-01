from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import networkx as nx
import osmnx as ox
from shapely.geometry import mapping

REPO_ROOT = Path(__file__).resolve().parents[1]


def download_drive_network(*, center_lat: float, center_lon: float, dist_m: int) -> Any:
    """Download a small drivable network (fast for hackathon demos)."""

    G = ox.graph_from_point(
        (center_lat, center_lon),
        dist=dist_m,
        network_type="drive",
        simplify=True,
    )
    G = ox.add_edge_speeds(G)
    G = ox.add_edge_travel_times(G)
    return G


def shortest_path_nodes(
    G: Any,
    *,
    origin_lat: float,
    origin_lon: float,
    dest_lat: float,
    dest_lon: float,
    weight: str = "travel_time",
) -> list[int]:
    """Shortest path between two lat/lon points."""

    origin_node = ox.nearest_nodes(G, X=origin_lon, Y=origin_lat)
    dest_node = ox.nearest_nodes(G, X=dest_lon, Y=dest_lat)

    return nx.shortest_path(G, origin_node, dest_node, weight=weight)


def simulate_bus_lane(
    G: Any,
    *,
    edge_id: str,
    factor: float = 1.5,
    weight_attr: str = "travel_time",
) -> Any:
    """Simulate a bus lane by increasing the travel weight on one edge."""

    u_str, v_str, key_str = edge_id.split("-", 2)
    u = int(u_str)
    v = int(v_str)
    key = int(key_str)

    G2 = G.copy()

    def bump(u_: int, v_: int) -> None:
        if not G2.has_edge(u_, v_, key):
            return
        data = G2[u_][v_][key]
        if weight_attr in data and data[weight_attr] is not None:
            data[weight_attr] = float(data[weight_attr]) * factor

    bump(u, v)
    bump(v, u)  # if the reverse exists

    return G2


def export_edges_geojson(G: Any, *, out_path: Path) -> None:
    nodes_gdf, edges_gdf = ox.graph_to_gdfs(G, nodes=True, edges=True, fill_edge_geometry=True)

    if "travel_time" not in edges_gdf.columns:
        G = ox.add_edge_travel_times(G)
        nodes_gdf, edges_gdf = ox.graph_to_gdfs(G, nodes=True, edges=True, fill_edge_geometry=True)

    tt = edges_gdf["travel_time"].astype(float)
    p75 = float(tt.quantile(0.75)) if len(tt) else 1.0
    if not p75 or p75 <= 0:
        p75 = max(float(tt.median()) if len(tt) else 1.0, 1.0)

    edges_gdf = edges_gdf.copy()
    edges_gdf["congestion"] = (tt / p75).clip(lower=0.0, upper=1.0)

    node_xy = nodes_gdf[["x", "y"]].to_dict(orient="index")

    features: list[dict[str, Any]] = []

    for (u, v, key), row in edges_gdf.iterrows():
        geom = row.geometry
        if geom is None:
            continue

        edge_id = f"{int(u)}-{int(v)}-{int(key)}"

        ux = node_xy.get(u, {}).get("x")
        uy = node_xy.get(u, {}).get("y")
        vx = node_xy.get(v, {}).get("x")
        vy = node_xy.get(v, {}).get("y")

        highway = row.get("highway")
        if isinstance(highway, list):
            highway = highway[0] if highway else None

        props: dict[str, Any] = {
            "edge_id": edge_id,
            "u": int(u),
            "v": int(v),
            "key": int(key),
            "name": row.get("name"),
            "highway": highway,
            "length_m": float(row.get("length", 0.0) or 0.0),
            "speed_kph": float(row.get("speed_kph")) if row.get("speed_kph") is not None else None,
            "travel_time_s": float(row.get("travel_time")) if row.get("travel_time") is not None else None,
            "congestion": float(row.get("congestion", 0.8)),
            "u_lon": float(ux) if ux is not None else None,
            "u_lat": float(uy) if uy is not None else None,
            "v_lon": float(vx) if vx is not None else None,
            "v_lat": float(vy) if vy is not None else None,
        }

        features.append(
            {
                "type": "Feature",
                "geometry": mapping(geom),
                "properties": props,
            }
        )

    out = {"type": "FeatureCollection", "features": features}
    out_path.write_text(json.dumps(out), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Export a small Baku drive network to GeoJSON for the demo UI")

    parser.add_argument("--center-lat", type=float, default=40.3796)
    parser.add_argument("--center-lon", type=float, default=49.8485)
    parser.add_argument("--dist", type=int, default=1800, help="Radius (meters)")
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "data" / "baku_edges.geojson")

    parser.add_argument("--origin-lat", type=float)
    parser.add_argument("--origin-lon", type=float)
    parser.add_argument("--dest-lat", type=float)
    parser.add_argument("--dest-lon", type=float)
    parser.add_argument("--bus-lane-edge-id", type=str, help="Edge id like 'u-v-key' to simulate")

    args = parser.parse_args()

    out_path: Path = args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"Downloading drive network near ({args.center_lat}, {args.center_lon})…")
    G = download_drive_network(center_lat=args.center_lat, center_lon=args.center_lon, dist_m=args.dist)

    print("Exporting edges GeoJSON…")
    export_edges_geojson(G, out_path=out_path)
    print(f"Wrote: {out_path}")

    if (
        args.origin_lat is not None
        and args.origin_lon is not None
        and args.dest_lat is not None
        and args.dest_lon is not None
    ):
        base_path = shortest_path_nodes(
            G,
            origin_lat=args.origin_lat,
            origin_lon=args.origin_lon,
            dest_lat=args.dest_lat,
            dest_lon=args.dest_lon,
        )
        print(f"Shortest path node-count (baseline): {len(base_path)}")

        if args.bus_lane_edge_id:
            G2 = simulate_bus_lane(G, edge_id=args.bus_lane_edge_id, factor=1.5)
            alt_path = shortest_path_nodes(
                G2,
                origin_lat=args.origin_lat,
                origin_lon=args.origin_lon,
                dest_lat=args.dest_lat,
                dest_lon=args.dest_lon,
            )
            print(f"Shortest path node-count (bus lane simulated): {len(alt_path)}")


if __name__ == "__main__":
    main()
