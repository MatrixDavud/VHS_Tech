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
    scenario_name: Optional[str] = None  # Human-readable label


class ScenarioEntry(BaseModel):
    """A single named scenario for comparison."""

    name: str
    road_ids: list[str]


class CompareRequest(BaseModel):
    """Compare multiple infrastructure scenarios under the same traffic conditions."""

    scenarios: list[ScenarioEntry]
    hour_of_day: Optional[int] = 18
    day_of_week: Optional[int] = 2
    population_density: Optional[float] = 0.7
    parking_availability: Optional[float] = 0.4
    weather: Optional[str] = "clear"
    cascade_radius: Optional[int] = 3


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

    simulator = TrafficSimulator(baseline_cong, network_store=store)
    result = simulator.simulate_bus_lanes(req.road_ids, profile, cascade_radius=cascade_radius)

    return result


@app.post("/compare-scenarios")
def compare_scenarios(req: CompareRequest) -> dict:
    """Run multiple infrastructure scenarios and return them ranked best-to-worst."""

    try:
        store.ensure_loaded()
    except FileNotFoundError as e:
        raise HTTPException(status_code=500, detail=str(e))

    if not req.scenarios:
        raise HTTPException(status_code=400, detail="scenarios list cannot be empty")

    if len(req.scenarios) > 10:
        raise HTTPException(status_code=400, detail="Maximum 10 scenarios per comparison")

    # Validate all road IDs up front
    for scenario in req.scenarios:
        for road_id in scenario.road_ids:
            if road_id not in store.roads:
                raise HTTPException(
                    status_code=404,
                    detail=f"Unknown road_id '{road_id}' in scenario '{scenario.name}'",
                )

    hour_of_day = req.hour_of_day if req.hour_of_day is not None else 18
    day_of_week = req.day_of_week if req.day_of_week is not None else 2
    population_density = req.population_density if req.population_density is not None else 0.7
    parking_availability = req.parking_availability if req.parking_availability is not None else 0.4
    weather = req.weather if req.weather is not None else "clear"
    cascade_radius = req.cascade_radius if req.cascade_radius is not None else 3

    profile = TrafficProfile(
        hour_of_day=hour_of_day,
        day_of_week=day_of_week,
        population_density=max(0.0, min(1.0, population_density)),
        parking_availability=max(0.0, min(1.0, parking_availability)),
        weather=weather,
    )

    # Shared baseline congestion across all scenarios
    baseline_cong = {
        road_id: store.get_road(road_id).get("properties", {}).get("congestion", 0.8)
        for road_id in store.roads
    }

    # Resolve road names for display
    def road_label(road_id: str) -> str:
        props = store.get_road(road_id).get("properties", {})
        name = props.get("name")
        highway = props.get("highway", "road")
        length = props.get("length_m", 0)
        length_str = f"{length / 1000:.2f} km" if length else ""
        if name:
            return f"{name} ({length_str})" if length_str else name
        return f"{highway} • {length_str}" if length_str else highway

    results = []
    for scenario in req.scenarios:
        simulator = TrafficSimulator(baseline_cong, network_store=store)
        sim_result = simulator.simulate_bus_lanes(
            scenario.road_ids, profile, cascade_radius=cascade_radius
        )

        road_labels = [road_label(rid) for rid in scenario.road_ids]

        results.append({
            "name": scenario.name,
            "road_ids": scenario.road_ids,
            "road_labels": road_labels,
            "metrics": sim_result["metrics"],
            "affected_roads": sim_result["affected_roads"],
            "recommendations": sim_result["recommendations"],
            "congestion_after_by_road": sim_result["congestion_after_by_road"],
            "road_status": sim_result["road_status"],
            "scenario_context": sim_result["scenario"],
        })

    # Rank by congestion improvement (highest improvement = best)
    results.sort(key=lambda r: r["metrics"]["improvement_percent"], reverse=True)
    for i, r in enumerate(results):
        r["rank"] = i + 1
        r["is_best"] = i == 0

    return {
        "ranked_scenarios": results,
        "comparison_context": {
            "hour_of_day": hour_of_day,
            "weather": weather,
            "is_peak_hour": profile.is_peak_hour,
            "total_scenarios": len(results),
        },
        "best_scenario": results[0]["name"] if results else None,
        "summary": _comparison_summary(results),
    }


def _comparison_summary(ranked: list[dict]) -> str:
    if not ranked:
        return "No scenarios to compare."
    best = ranked[0]
    worst = ranked[-1]
    improvement = best["metrics"]["improvement_percent"]
    if len(ranked) == 1:
        return f"Single scenario '{best['name']}' reduces congestion by {improvement}%."
    gap = improvement - worst["metrics"]["improvement_percent"]
    return (
        f"Best scenario: '{best['name']}' with {improvement}% congestion reduction. "
        f"Outperforms the weakest option by {round(gap, 1)} percentage points."
    )
