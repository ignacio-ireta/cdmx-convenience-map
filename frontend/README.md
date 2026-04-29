# Frontend

React + TypeScript + Leaflet app for the CDMX postal-code convenience map.

The app fetches `public/data/cdmx_postal_scores.geojson`, which is copied there by `scripts/build_scores.py`.

```bash
npm install
npm run dev -- --host 127.0.0.1 --port 5174
npm run build
npm run lint
```

