(() => {
  const statusEl = document.getElementById("status");
  const scoreEl = document.getElementById("score");
  const addBusLanesBtn = document.getElementById("addBusLanes");
  const saveScenarioBtn = document.getElementById("saveScenario");
  const compareBtn = document.getElementById("compareScenarios");
  const clearScenariosBtn = document.getElementById("clearScenarios");
  const modeCurrentBtn = document.getElementById("modeCurrent");
  const modeOptimizedBtn = document.getElementById("modeOptimized");
  const impactMetricsEl = document.getElementById("impactMetrics");
  const metricRoadsEl = document.getElementById("metricRoads");
  const metricTimeEl = document.getElementById("metricTime");
  const impactImprovementEl = document.getElementById("impactImprovement");
  const impactTimeSavedEl = document.getElementById("impactTimeSaved");
  const recommendationsListEl = document.getElementById("recommendationsList");
  const selectedRoadsListEl = document.getElementById("selectedRoadsList");
  const savedScenariosListEl = document.getElementById("savedScenariosList");
  const scenarioCountEl = document.getElementById("scenarioCount");
  const comparisonPanelEl = document.getElementById("comparisonPanel");
  const comparisonResultsEl = document.getElementById("comparisonResults");

  // Traffic parameter controls
  const timeOfDaySelect = document.getElementById("timeOfDay");
  const populationDensitySlider = document.getElementById("populationDensity");
  const populationDensityValue = document.getElementById("populationDensityValue");
  const parkingAvailabilitySlider = document.getElementById("parkingAvailability");
  const parkingAvailabilityValue = document.getElementById("parkingAvailabilityValue");
  const weatherConditionSelect = document.getElementById("weatherCondition");

  const API_BASE = window.API_BASE_URL || "http://localhost:8000";

  let selectedRoadIds = [];
  let savedScenarios = []; // [{name, road_ids}]

  // ── Helpers ──────────────────────────────────────────────────────────────

  function setStatus(message, type = "info") {
    statusEl.textContent = message;
    statusEl.className = "status";
    if (type === "error") statusEl.classList.add("error");
    if (type === "success") statusEl.classList.add("success");
    if (type === "warning") statusEl.classList.add("warning");
  }

  function setLoading(loading) {
    addBusLanesBtn.disabled = loading || selectedRoadIds.length === 0;
    addBusLanesBtn.textContent = loading
      ? "⏳ Simulating…"
      : `➕ Simulate Bus Lanes (${selectedRoadIds.length} road${selectedRoadIds.length !== 1 ? "s" : ""})`;
    if (compareBtn) {
      compareBtn.disabled = loading || savedScenarios.length < 2;
      compareBtn.textContent = loading ? "⏳ Comparing…" : `⚖️ Compare Scenarios (${savedScenarios.length})`;
    }
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

  // ── Road name display ─────────────────────────────────────────────────────

  function formatRoadInfo(feature) {
    if (!feature || !feature.properties) return "Unknown road";
    const props = feature.properties;
    const name = props.name;
    const highway = props.highway || "road";
    const length = props.length_m ? (props.length_m / 1000).toFixed(2) + " km" : "";
    if (name) return length ? `${name} (${length})` : name;
    return length ? `${highway} • ${length}` : highway;
  }

  function getRoadLabel(roadId) {
    if (!baselineGeojson) return roadId;
    const feature = baselineGeojson.features.find((f) => String(f.properties?.edge_id) === String(roadId));
    return feature ? formatRoadInfo(feature) : roadId;
  }

  // ── Map state ─────────────────────────────────────────────────────────────

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
          attribution: "&copy; OpenStreetMap contributors",
        },
      },
      layers: [{ id: "osm-base", type: "raster", source: "osm-tiles", paint: { "raster-opacity": 1 } }],
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
    scoreEl.textContent = `${Math.round((mode === "current" ? before : after) * 100)}%`;
  }

  function roadColorExpression() {
    return [
      "case",
      ["==", ["get", "status"], "bus_lane"], "#2563eb",
      ["==", ["get", "status"], "best_scenario"], "#7c3aed",
      [
        "step",
        ["coalesce", ["to-number", ["get", "congestion"]], 0.8],
        "#22c55e", 0.5, "#f59e0b", 0.75, "#ef4444",
      ],
    ];
  }

  function updateRoadStyles() {
    if (!map.getLayer("roads-layer")) return;
    map.setPaintProperty("roads-layer", "line-color", roadColorExpression());
    map.setPaintProperty("roads-layer", "line-width",
      selectedRoadIds.length > 0
        ? ["case", ["in", ["get", "edge_id"], ["literal", selectedRoadIds]], 6, 3]
        : 3
    );
  }

  function updateHighlightFilter() {
    if (!map.getLayer("roads-highlight")) return;
    map.setFilter("roads-highlight", ["in", ["get", "edge_id"], ["literal", selectedRoadIds]]);
  }

  function buildGeojsonFromRoadMaps(congestionByRoad, statusByRoad) {
    if (!baselineGeojson) return null;
    const next = deepClone(baselineGeojson);
    for (const f of next.features || []) {
      if (!f.properties) f.properties = {};
      const edgeId = String(f.properties.edge_id ?? "");
      delete f.properties.status;
      const cong = congestionByRoad?.[edgeId];
      if (cong !== undefined && cong !== null) f.properties.congestion = clamp01(Number(cong));
      const status = statusByRoad?.[edgeId];
      if (status) f.properties.status = status;
    }
    return next;
  }

  // ── Selected roads panel ──────────────────────────────────────────────────

  function updateSelectedRoadsList() {
    selectedRoadsListEl.innerHTML = "";
    if (selectedRoadIds.length === 0) {
      selectedRoadsListEl.innerHTML = "<div style='font-size:12px;color:#94a3b8;'>No roads selected</div>";
      return;
    }
    selectedRoadIds.forEach((roadId) => {
      const item = document.createElement("div");
      item.className = "road-item";
      item.innerHTML = `
        <span>${getRoadLabel(roadId)}</span>
        <button type="button" onclick="window.removeRoad('${roadId}')">Remove</button>
      `;
      selectedRoadsListEl.appendChild(item);
    });
  }

  function updateSimulateButtonText() {
    if (!addBusLanesBtn.textContent.startsWith("⏳")) {
      addBusLanesBtn.textContent = `➕ Simulate Bus Lanes (${selectedRoadIds.length} road${selectedRoadIds.length !== 1 ? "s" : ""})`;
    }
    addBusLanesBtn.disabled = selectedRoadIds.length === 0;
    const saveBtn = document.getElementById("saveScenario");
    if (saveBtn) saveBtn.disabled = selectedRoadIds.length === 0;
  }

  window.removeRoad = function (roadId) {
    selectedRoadIds = selectedRoadIds.filter((id) => id !== roadId);
    updateSelectedRoadsList();
    updateSimulateButtonText();
    updateRoadStyles();
    updateHighlightFilter();
  };

  // ── Saved scenarios panel ─────────────────────────────────────────────────

  function updateSavedScenariosList() {
    if (!savedScenariosListEl) return;
    savedScenariosListEl.innerHTML = "";

    if (savedScenarios.length === 0) {
      savedScenariosListEl.innerHTML = "<div style='font-size:12px;color:#94a3b8;'>No saved scenarios yet</div>";
    } else {
      savedScenarios.forEach((sc, idx) => {
        const item = document.createElement("div");
        item.className = "road-item";
        item.style.flexDirection = "column";
        item.style.alignItems = "flex-start";
        item.style.gap = "4px";
        item.innerHTML = `
          <div style="display:flex;justify-content:space-between;width:100%;align-items:center;">
            <strong style="font-size:12px;">${sc.name}</strong>
            <button type="button" onclick="window.removeScenario(${idx})">Remove</button>
          </div>
          <div style="font-size:11px;color:#64748b;">${sc.road_ids.map(getRoadLabel).join(", ")}</div>
        `;
        savedScenariosListEl.appendChild(item);
      });
    }

    if (scenarioCountEl) scenarioCountEl.textContent = savedScenarios.length;
    if (compareBtn) {
      compareBtn.disabled = savedScenarios.length < 2;
      compareBtn.textContent = `⚖️ Compare Scenarios (${savedScenarios.length})`;
    }
    if (clearScenariosBtn) clearScenariosBtn.style.display = savedScenarios.length > 0 ? "block" : "none";
  }

  window.removeScenario = function (idx) {
    savedScenarios.splice(idx, 1);
    updateSavedScenariosList();
  };

  function getTrafficParams() {
    return {
      hour_of_day: Number(timeOfDaySelect.value),
      day_of_week: 2,
      population_density: Number(populationDensitySlider.value) / 100,
      parking_availability: Number(parkingAvailabilitySlider.value) / 100,
      weather: weatherConditionSelect.value,
      cascade_radius: 3,
    };
  }

  // ── Metrics display ───────────────────────────────────────────────────────

  function updateMetrics() {
    if (!baselineGeojson?.features) return;
    const features = baselineGeojson.features;
    metricRoadsEl.textContent = features.length;
    const totalTime = features.reduce((sum, f) => sum + (Number(f.properties?.travel_time_s) || 30), 0);
    metricTimeEl.textContent = (totalTime / features.length / 60).toFixed(1) + "m";
  }

  // ── Comparison results panel ──────────────────────────────────────────────

  function renderComparisonResults(data) {
    if (!comparisonPanelEl || !comparisonResultsEl) return;

    comparisonResultsEl.innerHTML = "";

    const summary = document.createElement("div");
    summary.className = "recommendation";
    summary.style.marginBottom = "12px";
    summary.style.background = "rgba(124,58,237,0.08)";
    summary.style.borderLeftColor = "#7c3aed";
    summary.style.color = "#4c1d95";
    summary.textContent = data.summary;
    comparisonResultsEl.appendChild(summary);

    data.ranked_scenarios.forEach((sc) => {
      const card = document.createElement("div");
      card.className = "scenario-card" + (sc.is_best ? " best" : "");
      card.innerHTML = `
        <div class="scenario-card-header">
          <span class="scenario-rank">#${sc.rank}</span>
          <span class="scenario-name">${sc.name}</span>
          ${sc.is_best ? '<span class="best-badge">✓ Best</span>' : ""}
        </div>
        <div class="scenario-roads">${sc.road_labels.join(" · ")}</div>
        <div class="scenario-metrics">
          <div class="scenario-metric">
            <div class="scenario-metric-value">${sc.metrics.improvement_percent}%</div>
            <div class="scenario-metric-label">Congestion ↓</div>
          </div>
          <div class="scenario-metric">
            <div class="scenario-metric-value">${sc.metrics.time_saved_percent}%</div>
            <div class="scenario-metric-label">Time saved</div>
          </div>
          <div class="scenario-metric">
            <div class="scenario-metric-value">${sc.affected_roads.heavily_impacted}</div>
            <div class="scenario-metric-label">Roads impacted</div>
          </div>
        </div>
        <button class="btn" style="width:100%;margin-top:8px;font-size:12px;" 
          onclick="window.showScenarioOnMap(${JSON.stringify(sc).replace(/"/g, "&quot;")})">
          🗺 Show on map
        </button>
      `;
      comparisonResultsEl.appendChild(card);
    });

    comparisonPanelEl.style.display = "block";
  }

  window.showScenarioOnMap = function (sc) {
    const geojson = buildGeojsonFromRoadMaps(sc.congestion_after_by_road, sc.road_status);
    if (geojson && map.getSource("roads")) {
      map.getSource("roads").setData(geojson);
      updateRoadStyles();
      setStatus(`Showing scenario: ${sc.name} (${sc.metrics.improvement_percent}% improvement)`, "success");
    }
  };

  // ── Main map load ─────────────────────────────────────────────────────────

  map.on("load", async () => {
    try {
      setStatus("Loading road network from API…");
      baselineGeojson = await fetchJson(`${API_BASE}/network`);

      map.addSource("roads", { type: "geojson", data: baselineGeojson });

      map.addLayer({
        id: "roads-layer",
        type: "line",
        source: "roads",
        paint: { "line-color": roadColorExpression(), "line-width": 3, "line-opacity": 0.9 },
      });

      map.addLayer({
        id: "roads-highlight",
        type: "line",
        source: "roads",
        filter: ["in", ["get", "edge_id"], ["literal", []]],
        paint: { "line-color": "#111827", "line-width": 7, "line-opacity": 1 },
      });

      map.on("mouseenter", "roads-layer", () => { map.getCanvas().style.cursor = "pointer"; });
      map.on("mouseleave", "roads-layer", () => { map.getCanvas().style.cursor = ""; });

      map.on("click", "roads-layer", (e) => {
        const f = (e.features || [])[0];
        if (!f?.properties) return;
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
      updateSavedScenariosList();
      updateSimulateButtonText();

      modeCurrentBtn.addEventListener("click", () => setMode("current"));
      modeOptimizedBtn.addEventListener("click", () => setMode("optimized"));

      populationDensitySlider.addEventListener("input", (e) => {
        populationDensityValue.textContent = e.target.value + "%";
      });
      parkingAvailabilitySlider.addEventListener("input", (e) => {
        parkingAvailabilityValue.textContent = e.target.value + "%";
      });

      // ── Simulate single scenario ────────────────────────────────────────
      addBusLanesBtn.addEventListener("click", async () => {
        if (selectedRoadIds.length === 0) return;
        try {
          setLoading(true);
          setStatus("Simulating bus lanes with traffic profile…", "info");

          const sim = await fetchJson(`${API_BASE}/simulate-advanced`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ road_ids: selectedRoadIds, ...getTrafficParams() }),
          });

          lastSimulation = sim;
          scenarioGeojson = buildGeojsonFromRoadMaps(sim.congestion_before_by_road || null, null);
          optimizedGeojson = buildGeojsonFromRoadMaps(sim.congestion_after_by_road || null, sim.road_status || null);

          const improvement = Number(sim.metrics?.improvement_percent ?? 0);
          impactImprovementEl.textContent = improvement + "%";
          impactTimeSavedEl.textContent = (sim.metrics?.time_saved_percent ?? 0) + "%";

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

          const timeLabel = timeOfDaySelect.options[timeOfDaySelect.selectedIndex].text;
          setStatus(
            `✓ Simulation complete! ${selectedRoadIds.length} road${selectedRoadIds.length !== 1 ? "s" : ""} reduce congestion by ${improvement}% at ${timeLabel.toLowerCase()}. ${sim.affected_roads?.heavily_impacted || 0} nearby roads affected.`,
            "success"
          );
        } catch (err) {
          setStatus(String(err.message || err), "error");
        } finally {
          setLoading(false);
        }
      });

      // ── Save scenario ───────────────────────────────────────────────────
      if (saveScenarioBtn) {
        saveScenarioBtn.addEventListener("click", () => {
          if (selectedRoadIds.length === 0) return;
          const name = `Scenario ${savedScenarios.length + 1}`;
          savedScenarios.push({ name, road_ids: [...selectedRoadIds] });
          updateSavedScenariosList();
          setStatus(`✓ Saved as "${name}". Select different roads to build another scenario.`, "success");
        });
      }

      // ── Compare scenarios ───────────────────────────────────────────────
      if (compareBtn) {
        compareBtn.addEventListener("click", async () => {
          if (savedScenarios.length < 2) return;
          try {
            setLoading(true);
            setStatus("Comparing scenarios…", "info");

            const result = await fetchJson(`${API_BASE}/compare-scenarios`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                scenarios: savedScenarios,
                ...getTrafficParams(),
              }),
            });

            renderComparisonResults(result);

            // Show best scenario on map automatically
            const best = result.ranked_scenarios[0];
            if (best) {
              const geojson = buildGeojsonFromRoadMaps(best.congestion_after_by_road, best.road_status);
              if (geojson && map.getSource("roads")) {
                map.getSource("roads").setData(geojson);
                updateRoadStyles();
              }
            }

            setStatus(`✓ Comparison complete. Best: "${result.best_scenario}"`, "success");
          } catch (err) {
            setStatus(String(err.message || err), "error");
          } finally {
            setLoading(false);
          }
        });
      }

      // ── Clear scenarios ─────────────────────────────────────────────────
      if (clearScenariosBtn) {
        clearScenariosBtn.addEventListener("click", () => {
          savedScenarios = [];
          updateSavedScenariosList();
          if (comparisonPanelEl) comparisonPanelEl.style.display = "none";
          setStatus("Scenarios cleared.", "info");
        });
      }

      setStatus("✓ Network loaded. Click roads to select, adjust traffic scenario, then simulate.", "success");
    } catch (err) {
      setStatus(String(err.message || err), "error");
    }
  });
})();
