"""Advanced traffic modeling with time, population, and parking factors."""

from __future__ import annotations

import math
import zlib
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TrafficProfile:
    """Time-based traffic multiplier and context."""

    hour_of_day: int  # 0-23
    day_of_week: int  # 0=Monday, 6=Sunday
    population_density: float  # 0.0-1.0 (ratio)
    parking_availability: float  # 0.0-1.0 (1.0 = plenty, 0.0 = full)
    weather: str  # "clear", "rain", "snow"

    @property
    def is_peak_hour(self) -> bool:
        """Detect peak traffic hours."""
        return self.hour_of_day in (7, 8, 9, 17, 18, 19)

    @property
    def is_weekend(self) -> bool:
        return self.day_of_week >= 5

    @property
    def time_multiplier(self) -> float:
        """0.4x (off-peak) to 1.8x (peak rush hour)."""
        base = 1.0

        if self.is_peak_hour:
            base = 1.8
        elif self.hour_of_day in (6, 10, 11, 12, 16, 20):
            base = 1.2
        elif self.hour_of_day in (0, 1, 2, 3, 4, 5):
            base = 0.3
        elif self.hour_of_day in (13, 14, 15):
            base = 0.9

        if self.is_weekend and not self.is_peak_hour:
            base *= 0.7

        return base

    @property
    def weather_multiplier(self) -> float:
        """Impact of weather on traffic."""
        if self.weather == "snow":
            return 1.5
        elif self.weather == "rain":
            return 1.2
        return 1.0

    @property
    def parking_multiplier(self) -> float:
        """Low parking availability = more circulating vehicles."""
        return 0.8 + (1.0 - self.parking_availability) * 0.6

    @property
    def density_multiplier(self) -> float:
        """High population = more baseline traffic."""
        return 0.7 + self.population_density * 0.8


class TrafficSimulator:
    """Simulate complex traffic impact of infrastructure changes."""

    def __init__(self, baseline_congestion: dict[str, float]) -> None:
        """
        Args:
            baseline_congestion: Map of road_id -> congestion (0.0-1.0)
        """
        self.baseline = baseline_congestion.copy()

    def simulate_bus_lanes(
        self,
        bus_lane_road_ids: list[str],
        profile: TrafficProfile,
        cascade_radius: int = 3,
    ) -> dict[str, Any]:
        """
        Simulate impact of adding bus lanes to multiple roads.

        Returns:
            Detailed impact analysis with before/after metrics.
        """

        # Calculate contextual baseline (keep it moderate; base congestion already encodes real-world variability)
        context_multiplier = (
            1.0
            + 0.2 * (profile.time_multiplier - 1.0)
            + 0.1 * (profile.weather_multiplier - 1.0)
            + 0.1 * (profile.parking_multiplier - 1.0)
            + 0.1 * (profile.density_multiplier - 1.0)
        )

        # Adjust baseline by context
        adjusted_baseline = {road_id: min(1.0, cong * context_multiplier) for road_id, cong in self.baseline.items()}

        # Calculate network-wide baseline
        avg_congestion_before = sum(adjusted_baseline.values()) / max(len(adjusted_baseline), 1)

        # Apply bus lane effects (and produce per-road outputs for the frontend)
        bus_lane_ids_set = set(bus_lane_road_ids)

        # Network-wide relief: more bus lanes generally means fewer cars (mode shift) and smoother flow.
        peak_factor = 1.0 if profile.is_peak_hour else 0.7
        global_relief = min(0.18, 0.02 * len(bus_lane_ids_set) * peak_factor)

        congestion_after_by_road: dict[str, float] = {}
        road_status: dict[str, str] = {}
        delta_by_road: dict[str, float] = {}

        for road_id, base_cong in adjusted_baseline.items():
            if road_id in bus_lane_ids_set:
                # Bus lane itself: reduced to 20% congestion
                new_cong = 0.20
                status = "bus_lane"
            else:
                # Check distance to nearest bus lane
                distance = self._distance_to_bus_lanes(road_id, bus_lane_ids_set)

                if distance <= cascade_radius:
                    # Nearby roads: traffic redistributes (some congestion increase near the lanes)
                    effect = self._cascade_effect(distance, cascade_radius)
                    new_cong = min(1.0, max(0.1, base_cong * (1.0 + effect) - global_relief))
                else:
                    # Far roads: slight network-wide relief
                    relief = 0.02
                    new_cong = max(0.1, base_cong - relief - global_relief)

                delta = new_cong - base_cong
                if delta > 0.02:
                    status = "increased"
                elif delta < -0.02:
                    status = "decreased"
                else:
                    status = "unchanged"

            congestion_after_by_road[road_id] = new_cong
            delta_by_road[road_id] = new_cong - base_cong
            road_status[road_id] = status

        avg_congestion_after = sum(congestion_after_by_road.values()) / max(len(congestion_after_by_road), 1)

        # Calculate travel time impact (congestion to minutes)
        baseline_time = self._congestion_to_travel_time(avg_congestion_before, 1.0)  # avg 1km road
        optimized_time = self._congestion_to_travel_time(avg_congestion_after, 1.0)
        time_saved_per_km = baseline_time - optimized_time

        # Impact classification
        heavily_affected = [
            road_id
            for road_id, delta in delta_by_road.items()
            if road_id not in bus_lane_ids_set and delta > 0.02
        ]
        benefited = [
            road_id
            for road_id, delta in delta_by_road.items()
            if road_id not in bus_lane_ids_set and delta < -0.02
        ]

        return {
            "scenario": {
                "time_of_day": profile.hour_of_day,
                "day_of_week": profile.day_of_week,
                "weather": profile.weather,
                "is_peak_hour": profile.is_peak_hour,
                "population_density": profile.population_density,
                "parking_availability": profile.parking_availability,
                "context_multiplier": round(context_multiplier, 2),
            },
            "congestion_before_by_road": {road_id: round(cong, 3) for road_id, cong in adjusted_baseline.items()},
            "congestion_after_by_road": {road_id: round(cong, 3) for road_id, cong in congestion_after_by_road.items()},
            "road_status": road_status,
            "metrics": {
                "congestion_before": round(avg_congestion_before, 3),
                "congestion_after": round(avg_congestion_after, 3),
                "improvement_percent": round((avg_congestion_before - avg_congestion_after) / avg_congestion_before * 100, 1)
                if avg_congestion_before > 0
                else 0,
                "travel_time_before_per_km": round(baseline_time, 1),
                "travel_time_after_per_km": round(optimized_time, 1),
                "time_saved_percent": round((baseline_time - optimized_time) / baseline_time * 100, 1) if baseline_time > 0 else 0,
            },
            "affected_roads": {
                "bus_lane_count": len(bus_lane_ids_set),
                "heavily_impacted": len(heavily_affected),
                "benefited": len(benefited),
                "cascade_radius": cascade_radius,
            },
            "recommendations": self._generate_recommendations(
                avg_congestion_after, profile, time_saved_per_km, heavily_affected
            ),
        }

    def _cascade_effect(self, distance: int, radius: int) -> float:
        """
        Traffic redistribution effect based on distance.
        Closer roads see more redistribution (initial increase),
        farther roads see gradual relief.
        """
        normalized_dist = distance / max(radius, 1)
        # Quadratic: meaningful increase near, mild relief further out.
        return 0.5 * (1 - normalized_dist) ** 2 - 0.05

    def _distance_to_bus_lanes(self, road_id: str, bus_lane_ids: set[str]) -> int:
        """Simplified distance (in "hops" of connected roads)."""
        if road_id in bus_lane_ids:
            return 0

        # Deterministic pseudo-distance based on (road_id, bus_lane_id) pairs.
        best = 99
        for lane_id in bus_lane_ids:
            h = zlib.adler32(f"{road_id}|{lane_id}".encode("utf-8")) % 100
            if h < 12:
                dist = 1
            elif h < 30:
                dist = 2
            elif h < 55:
                dist = 3
            elif h < 80:
                dist = 4
            else:
                dist = 5
            if dist < best:
                best = dist
                if best == 1:
                    break

        return best if best != 99 else 5

    def _congestion_to_travel_time(self, congestion: float, road_length_km: float) -> float:
        """Convert congestion (0-1) to travel time in minutes for a road segment."""
        # Baseline: 60 km/h = 1 minute per km at 0 congestion
        # At 1.0 congestion: 15 km/h = 4 minutes per km
        speed_kph = 60 * (1 - congestion * 0.75)
        minutes = (road_length_km / max(speed_kph, 5)) * 60
        return minutes

    def _generate_recommendations(
        self, avg_congestion_after: float, profile: TrafficProfile, time_saved_per_km: float, heavily_affected: list[str]
    ) -> list[str]:
        """Smart recommendations based on simulation results."""
        recommendations = []

        if avg_congestion_after < 0.65:
            recommendations.append("Excellent improvement. Recommended for deployment.")
        elif avg_congestion_after < 0.75:
            recommendations.append("Good improvement with acceptable trade-offs.")
        else:
            recommendations.append("Modest improvement. Consider adjusting bus lane routes.")

        if profile.is_peak_hour:
            recommendations.append("This strategy is especially effective during peak hours.")

        if len(heavily_affected) > 5:
            recommendations.append(
                f"Caution: {len(heavily_affected)} nearby roads will experience increased congestion. Consider mitigation measures."
            )

        if profile.parking_availability < 0.3:
            recommendations.append("Low parking availability is worsening congestion. Consider parking solutions first.")

        if time_saved_per_km > 0.5:
            recommendations.append(f"Average commute time saved: {round(time_saved_per_km, 1)} min/km network-wide.")

        return recommendations
