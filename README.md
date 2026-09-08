# West Torrance XC 2026 — Live

The app is a mobile-friendly Streamlit dashboard. A GitHub Actions job checks Finished Results hourly, discovers 2026 meet result pages, downloads public result PDFs, extracts individual results, deduplicates them, and commits updated CSVs. Streamlit then reflects the updated repository.

Important: this importer is designed for public/permitted result pages and does not bypass authentication, paywalls, CAPTCHAs, or robots restrictions. It is a starting adapter and should be validated against each provider's terms.

Files:
- app.py — dashboard
- ingest_finished_results.py — Finished Results importer
- data/results.csv — normalized individual results
- data/meets.csv — meet registry
- .github/workflows/update-xc.yml — hourly updater

The current importer targets Finished Results first. Additional adapters can be added for other permitted timing providers.
