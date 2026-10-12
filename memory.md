# gb-grid-margin — state

Repo for https://gridmargin.co.uk (Cloudflare Pages, deploys from `main`). Permanent clone: `~/AIOS/Projects/gb-grid-margin`. Never build in scratch: the 10 Oct Scotland work was lost there.

## Now (12 Oct 2026)
- **Scotland page live**: https://gridmargin.co.uk/scotland (`site/scotland.html`, engine `engine/scotland_wind.py`, data `site/data/scotland_wind.json`, tests `tests/test_scotland_wind.py`). Merged `c856276`; 430 tests pass. Home page links to it.
- Headline figures (data Mar 2019 to 5 Oct 2026): 1,471 calm hours in the past year (16.8%); longest calm 140 h (12–17 Oct 2025); three nine-day calm runs. 2025 metered 24.0 TWh vs official 30.9 TWh (22% shortfall, disclosed on the page).
- The daily GitHub Actions refresh now regenerates `scotland_wind.json`. First automatic run not yet verified: OPS-205.
- Uncommitted in the working tree: `site/post-mortem/24-june-2026-emergency.html` and its index link (generated 12 Oct 21:33 by another thread, unpublished). Richard reviews before commit.

## Used in
- Duncan Massey MSP and Liam Kerr MSP correspondence (12 Oct), alongside subsidyclock.co.uk/scotland.
