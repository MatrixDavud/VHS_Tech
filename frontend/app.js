(() => {
  const statusEl = document.getElementById("status");
  const scoreEl = document.getElementById("score");
  const addBusLanesBtn = document.getElementById("addBusLanes");
  const modeCurrentBtn = document.getElementById("modeCurrent");
  const modeOptimizedBtn = document.getElementById("modeOptimized");
  const impactMetricsEl = document.getElementById("impactMetrics");
  const metricRoadsEl = document.getElementById("metricRoads");
  const metricTimeEl = document.getElementById("metricTime");
  const impactImprovementEl = document.getElementById("impactImprovement");
  const impactTimeSavedEl = document.getElementById("impactTimeSaved");
  const recommendationsListEl = document.getElementById("recommendationsList");
  const selectedRoadsListEl = document.getElementById("selectedRoadsList");

  // Traffic parameter controls
  const timeOfDaySelect = document.getElementById("timeOfDay");
  const populationDensitySlider = document.getElementById("populationDensity");
  const populationDensityValue = document.getElementById("populationDensityValue");
  const parkingAvailabilitySlider = document.getElementById("parkingAvailability");
  const parkingAvailabilityValue = document.getElementById("parkingAvailabilityValue");
  const weatherConditionSelect = document.getElementById("weatherCondition");

  const API_BASE = window.API_BASE_URL || "http://localhost:8000";

  let selectedRoadIds = [];

  function setStatus(message, type = "info") {
    statusEl.textContent = message;
    statusEl.className = "status";
    if (type === "error") statusEl.classList.add("error");
    if (type === "success") statusEl.classList.add("success");
    if (type === "warning") statusEl.classList.add("warning");
  }

  if (!window.maplibregl) {
    setStatus("MapLibre failed to load. Check your internet connection.", "error");
    return;
  }

  const map = new maplibregl.Map({
    container: "map",
    style: {
      version: 8,
      sources: {
        "osm-tiles": {
          type: "raster",
          tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
          tileSize: 256,
          minzoom: 0,
          maxzoom: 19,
          attribution: "&copy; OpenStreetMap contributors"
        }
      },
      layers: [
        {
          id: "osm-base",
          type: "raster",
          source: "osm-tiles",
          paint: { "raster-opacity": 1 }
        }
      ]
    },
    center: [49.8485, 40.3796],
    zoom: 14,
  });

  let mode = "current";
  let baselineGeojson = null;
  let scenarioGeojson = null;
  let optimizedGeojson = null;
  let lastSimulation = null;

  function setMode(nextMode) {
    mode = nextMode;
    modeCurrentBtn.classList.toggle("active", mode === "current");
    modeOptimizedBtn.classList.toggle("active", mode === "optimized");

    if (!map.getSource("roads") || !baselineGeojson) return;
    const currentData = scenarioGeojson || baselineGeojson;
    const data = mode === "current" ? currentData : optimizedGeojson || currentData;
    map.getSource("roads").setData(data);
    updateRoadStyles();
    updateScoreForMode();
  }

  function updateScoreForMode() {
    if (!lastSimulation?.metrics) return;
    const before = Number(lastSimulation.metrics.congestion_before ?? 0.8);
    const after = Number(lastSimulation.metrics.congestion_after ?? 0.65);
    const value = mode === "current" ? before : after;
    scoreEl.textContent = `${Math.round(value * 100)}%`;
  }

  function updateRoadStyles() {
    if (!map.getLayer("roads-layer")) return;
    map.setPaintProperty("roads-layer", "line-color", roadColorExpression());

    if (selectedRoadIds.length > 0) {
      map.setPaintProperty("roads-layer", "line-width", [
        "case",
        ["in", ["get", "edge_id"], ["literal", selectedRoadIds]],
        6,
        3,
      ]);
    } else {
      map.setPaintProperty("roads-layer", "line-width", 3);
    }
  }

  function updateHighlightFilter() {
    if (!map.getLayer("roads-highlight")) return;
    map.setFilter("roads-highlight", ["in", ["get", "edge_id"], ["literal", selectedRoadIds]]);
  }

  function updateSelectedRoadsList() {
    selectedRoadsListEl.innerHTML = "";
    if (selectedRoadIds.length === 0) {
      selectedRoadsListEl.innerHTML = "<div style='font-size: 12px; color: #94a3b8;'>No roads selected</div>";
      return;
    }

    selectedRoadIds.forEach((roadId) => {
      const item = document.createElement("div");
      item.className = "road-item";

      const feature = baselineGeojson.features.find((f) => f.properties?.edge_id === roadId);
      const info = feature ? formatRoadInfo(feature) : "—";

      item.innerHTML = `
        <span>${info}</span>
        <button type="button" onclick="window.removeRoad && window.removeRoad('${roadId}')">Remove</button>
      `;
      selectedRoadsListEl.appendChild(item);
    });
  }

  function updateSimulateButtonText() {
    addBusLanesBtn.textContent = `➕ Simulate Bus Lanes (${selectedRoadIds.length} road${selectedRoadIds.length !== 1 ? "s" : ""})`;
    addBusLanesBtn.disabled = selectedRoadIds.length === 0;
  }

  // Global function to remove a road from selection
  window.removeRoad = function (roadId) {
    selectedRoadIds = selectedRoadIds.filter((id) => id !== roadId);
    updateSelectedRoadsList();
    updateSimulateButtonText();
    updateRoadStyles();
    updateHighlightFilter();
  };

  function roadColorExpression() {
    return [
      "case",
      ["==", ["get", "status"], "bus_lane"],
      "#2563eb",
      [
        "step",
        ["coalesce", ["to-number", ["get", "congestion"]], 0.8],
        "#22c55e",
        0.5,
        "#f59e0b",
        0.75,
        "#ef4444",
      ],
    ];
  }

  function updateMetrics() {
    if (!baselineGeojson || !baselineGeojson.features) return;

    const features = baselineGeojson.features;
    metricRoadsEl.textContent = features.length;

    const totalTime = features.reduce((sum, f) => {
      return sum + (Number(f.properties?.travel_time_s) || 30);
    }, 0);
    const avgTimeMins = (totalTime / features.length / 60).toFixed(1);
    metricTimeEl.textContent = avgTimeMins + "m";
  }

  function formatRoadInfo(feature) {
    if (!feature || !feature.properties) return "No info";

    const props = feature.properties;
    const highway = props.highway || "Unknown";
    const length = props.length_m ? (props.length_m / 1000).toFixed(2) + " km" : "—";

    return `${highway} • ${length}`;
  }

  async function fetchJson(url, options) {
    const res = await fetch(url, options);
    if (!res.ok) {
      const text = await res.text();
      throw new Error(`${res.status} ${res.statusText}: ${text}`);
    }
    return res.json();
  }

  function deepClone(obj) {
    return JSON.parse(JSON.stringify(obj));
  }

  function clamp01(x) {
    return Math.max(0, Math.min(1, x));
  }

  function buildGeojsonFromRoadMaps(congestionByRoad, statusByRoad) {
    if (!baselineGeojson) return null;

    const next = deepClone(baselineGeojson);
    for (const f of next.features || []) {
      if (!f.properties) f.properties = {};
      const edgeId = String(f.properties.edge_id ?? "");

      delete f.properties.status;

      const cong = congestionByRoad ? congestionByRoad[edgeId] : undefined;
      if (cong !== undefined && cong !== null && cong !== "") {
        f.properties.congestion = clamp01(Number(cong));
      }

      const status = statusByRoad ? statusByRoad[edgeId] : undefined;
      if (status) {
        f.properties.status = status;
      }
    }

    return next;
  }

  map.on("load", async () => {
    try {
      setStatus("Loading road network from API…");
      baselineGeojson = await fetchJson(`${API_BASE}/network`);

      map.addSource("roads", {
        type: "geojson",
        data: baselineGeojson,
      });

      map.addLayer({
        id: "roads-layer",
        type: "line",
        source: "roads",
        paint: {
          "line-color": roadColorExpression(),
          "line-width": 3,
          "line-opacity": 0.9,
        },
      });

      map.addLayer({
        id: "roads-highlight",
        type: "line",
        source: "roads",
        filter: ["in", ["get", "edge_id"], ["literal", []]],
        paint: {
          "line-color": "#111827",
          "line-width": 7,
          "line-opacity": 1,
        },
      });

      map.on("mouseenter", "roads-layer", () => {
        map.getCanvas().style.cursor = "pointer";
      });
      map.on("mouseleave", "roads-layer", () => {
        map.getCanvas().style.cursor = "";
      });

      map.on("click", "roads-layer", (e) => {
        const f = (e.features || [])[0];
        if (!f || !f.properties) return;
        const roadId = String(f.properties.edge_id || "");

        if (selectedRoadIds.includes(roadId)) {
          selectedRoadIds = selectedRoadIds.filter((id) => id !== roadId);
        } else {
          selectedRoadIds.push(roadId);
        }

        updateSelectedRoadsList();
        updateSimulateButtonText();
        updateRoadStyles();
        updateHighlightFilter();
      });

      updateMetrics();
      updateSelectedRoadsList();
      updateSimulateButtonText();

      modeCurrentBtn.addEventListener("click", () => setMode("current"));
      modeOptimizedBtn.addEventListener("click", () => setMode("optimized"));

      // Update slider display values
      populationDensitySlider.addEventListener("input", (e) => {
        populationDensityValue.textContent = e.target.value + "%";
      });

      parkingAvailabilitySlider.addEventListener("input", (e) => {
        parkingAvailabilityValue.textContent = e.target.value + "%";
      });

      addBusLanesBtn.addEventListener("click", async () => {
        if (selectedRoadIds.length === 0) return;

        try {
          setStatus("Simulating bus lanes with traffic profile…", "info");

          const sim = await fetchJson(`${API_BASE}/simulate-advanced`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              road_ids: selectedRoadIds,
              hour_of_day: Number(timeOfDaySelect.value),
              day_of_week: 2,
              population_density: Number(populationDensitySlider.value) / 100,
              parking_availability: Number(parkingAvailabilitySlider.value) / 100,
              weather: weatherConditionSelect.value,
              cascade_radius: 3,
            }),
          });

          lastSimulation = sim;
          scenarioGeojson = buildGeojsonFromRoadMaps(sim.congestion_before_by_road || null, null);
          optimizedGeojson = buildGeojsonFromRoadMaps(sim.congestion_after_by_road || null, sim.road_status || null);

          const before = Number(sim.metrics?.congestion_before ?? 0.8);
          const after = Number(sim.metrics?.congestion_after ?? 0.65);
          const improvement = Number(sim.metrics?.improvement_percent ?? 15);

          scoreEl.textContent = `${Math.round(after * 100)}%`;
          impactImprovementEl.textContent = improvement + "%";
          impactTimeSavedEl.textContent = (sim.metrics?.time_saved_percent ?? 0) + "%";

          // Display recommendations
          recommendationsListEl.innerHTML = "";
          (sim.recommendations || []).forEach((rec) => {
            const div = document.createElement("div");
            div.className = "recommendation";
            div.textContent = rec;
            recommendationsListEl.appendChild(div);
          });

          impactMetricsEl.style.display = "block";
          setMode("optimized");
          updateScoreForMode();

          const timeOfDayLabel = timeOfDaySelect.options[timeOfDaySelect.selectedIndex].text;
          const lanePhrase = selectedRoadIds.length === 1 ? "bus lane reduces" : "bus lanes reduce";
          setStatus(
            `✓ Simulation complete! ${selectedRoadIds.length} ${lanePhrase} congestion by ${improvement}% at ${timeOfDayLabel.toLowerCase()}. ${sim.affected_roads?.heavily_impacted || 0} nearby roads affected.`,
            "success"
          );
        } catch (err) {
          setStatus(String(err.message || err), "error");
        }
      });

      setStatus("✓ Network loaded. Click roads to select, adjust traffic scenario, then simulate.", "success");
    } catch (err) {
      setStatus(String(err.message || err), "error");
    }
  });
})();
