# Baku Bus-Lane Digital Twin (Minimum Viable Demo)

A hackathon-ready “digital twin” demo for Baku: click a road, add a bus lane, and instantly see **Current** vs **Optimized** congestion on a map.

## What you get
- **Backend (FastAPI):** serves the road network and a `/simulate` endpoint (GNN-lite heuristic)
- **Data (OSMnx):** one script to export a small Baku road network to GeoJSON
- **Frontend (static + MapLibre GL JS):** no Node required; no map token required; open in browser via a simple HTTP server

---

## 1) Install Python deps
This repo expects a Python venv (already configured in this workspace).

```bash
/home/admin123/Project/.venv/bin/python -m pip install -r backend/requirements.txt
```

## 2) Export a small road network (28 May / Railway Station area)
```bash
/home/admin123/Project/.venv/bin/python data/export_osm.py \
  --center-lat 40.3796 --center-lon 49.8485 \
  --dist 1800 \
  --out data/baku_edges.geojson
```

## 3) Run the API
From the repo root:

```bash
/home/admin123/Project/.venv/bin/python -m uvicorn backend.app.main:app --reload --port 8000
```

- `GET http://localhost:8000/network` returns GeoJSON
- `POST http://localhost:8000/simulate` simulates “bus lane impact”

## 4) Configure Mapbox token
Not required (the demo uses MapLibre’s public demo tiles/style).

## 5) Run the frontend
In a second terminal:

```bash
cd frontend
/home/admin123/Project/.venv/bin/python -m http.server 3000
```

Open: http://localhost:3000

## Demo flow (what to show judges)
1. **Current State:** red/yellow roads (baseline congestion)
2. Click a road segment
3. Click **Add Bus Lane**
4. Switch to **Optimized State:** mostly greener network + the bus lane in blue

---

### Notes
- If `data/baku_edges.geojson` doesn’t exist, run the exporter (step 2).
- If you want a different area, change `--center-lat/--center-lon` and `--dist`.
