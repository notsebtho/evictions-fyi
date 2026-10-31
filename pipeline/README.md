# /age data pipeline

The page at `/age/` is fully static. It loads `age/data.json` and estimates in the browser.
The GitHub Action in `.github/workflows/age-data.yml` rebuilds that file from EVE Ref's structure
history every day and commits it to `main`. Run it by hand from the Actions tab ("Run workflow").

Locally:

    pip install orjson
    for y in 2023 2024 2025 2026; do STATE=state-$y.json python3 extract_first_seen.py $y; done
    python3 build_curve.py                              # -> knots.json, curve.csv
    python3 export_web.py knots.json ../age/data.json   # -> compact page data
    python3 estimate.py 1045000000000                   # CLI check, same maths as the page

The extractor saves `state-*.json` and resumes from them. The Action keeps them in its cache, so only
the first run downloads the full archives (about 2.5 GB, 15 minutes).
