from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .network_store import NetworkStore
from .sim import simulate_bus_lane_impact
from .traffic_model import TrafficProfile, TrafficSimulator

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_NETWORK_PATH = REPO_ROOT / "data" / "baku_edges.geojson"

app = FastAPI(title="Baku Digital Twin Demo", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

store = NetworkStore(DEFAULT_NETWORK_PATH)


class SimulateRequest(BaseModel):
    road_id: str


class SimulateMultiRequest(BaseModel):
    """Advanced simulation with multiple roads and traffic context."""

    road_ids: list[str]  # Multiple roads to apply bus lanes to
    hour_of_day: Optional[int] = 18  # 0-23, default evening peak
    day_of_week: Optional[int] = 2  # 0=Mon, 6=Sun, default Wednesday
    population_density: Optional[float] = 0.7  # 0.0-1.0
    parking_availability: Optional[float] = 0.4  # 0.0-1.0 (1.0 = plenty)
    weather: Optional[str] = "clear"  # "clear", "rain", "snow"
    cascade_radius: Optional[int] = 3  # How far to simulate impact


@app.on_event("startup")
def _startup() -> None:
    # Don’t hard-fail at boot if the GeoJSON isn’t generated yet.
    store.try_load()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/network")
def network() -> dict:
    try:
        store.ensure_loaded()
    except FileNotFoundError as e:
        raise HTTPException(status_code=500, detail=str(e))

    assert store.geojson is not None
    return store.geojson


@app.post("/simulate")
def simulate(req: SimulateRequest) -> dict:
    try:
        store.ensure_loaded()
    except FileNotFoundError as e:
        raise HTTPException(status_code=500, detail=str(e))

    try:
        return simulate_bus_lane_impact(store, req.road_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown road_id: {req.road_id}")


@app.post("/simulate-advanced")
def simulate_advanced(req: SimulateMultiRequest) -> dict:
    """Advanced multi-road simulation with traffic profiles."""

    try:
        store.ensure_loaded()
    except FileNotFoundError as e:
        raise HTTPException(status_code=500, detail=str(e))

    if not req.road_ids:
        raise HTTPException(status_code=400, detail="road_ids list cannot be empty")

    for road_id in req.road_ids:
        if road_id not in store.roads:
            raise HTTPException(status_code=404, detail=f"Unknown road_id: {road_id}")

    # Build baseline congestion from all roads
    baseline_cong = {
        road_id: store.get_road(road_id).get("properties", {}).get("congestion", 0.8)
        for road_id in store.roads
    }

    hour_of_day = req.hour_of_day if req.hour_of_day is not None else 18
    day_of_week = req.day_of_week if req.day_of_week is not None else 2
    population_density = req.population_density if req.population_density is not None else 0.7
    parking_availability = req.parking_availability if req.parking_availability is not None else 0.4
    weather = req.weather if req.weather is not None else "clear"

    # Create traffic profile
    profile = TrafficProfile(
        hour_of_day=hour_of_day,
        day_of_week=day_of_week,
        population_density=max(0.0, min(1.0, population_density)),
        parking_availability=max(0.0, min(1.0, parking_availability)),
        weather=weather,
    )

    # Run simulation
    cascade_radius = req.cascade_radius if req.cascade_radius is not None else 3

    simulator = TrafficSimulator(baseline_cong)
    result = simulator.simulate_bus_lanes(req.road_ids, profile, cascade_radius=cascade_radius)

    return result
