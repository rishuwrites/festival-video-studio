# Panchang data provenance

The 44 rows in `panchang_2026_11_18_to_12_31.csv` were calculated by
`tools/compute_panchang.py` using `pyswisseph` 2.10.3.2 and Swiss Ephemeris
sidereal calculations with the Lahiri ayanamsa. `PANCHANG_LOCATION` is read from
`config/panchang.json`; the configured site is Lucknow, Uttar Pradesh
(26.8467 N, 80.9462 E, 126 m, `Asia/Kolkata`). The elevation comes from the
Drik Panchang geographic-details page for Lucknow:
https://www.drikpanchang.com/location/panchang-location-details.html?geoname-id=1264733

At the calculated sunrise, the tool uses the sidereal Sun-Moon longitude
difference in 12-degree intervals for tithi and paksha, the Moon's sidereal
longitude for nakshatra and rashi, and the sunrise-to-sunset eighths of the day
for Rahu Kaal. Sunrise and sunset are computed at the configured coordinates.

Each row's `source_url` points to the published Drik Panchang daily page. The
source pages use Drik's Lucknow city center coordinates (26.83928 N,
80.92313 E), while the computation uses the coordinates supplied for this
project. The separate `panchang_crosscheck_report.csv` compares tithi and
nakshatra at sunrise. A `needs_review` result must be resolved before those
fields are used in a video. Three fixed expected panchang values and their
published source URLs are also recorded in `tests/test_compute_panchang.py`.

Recompute and cross-check the configured window with:

```powershell
python tools\compute_panchang.py --from 2026-11-18 --to 2026-12-31
```

Use `--no-crosscheck` only for an offline calculation; an offline run does not
produce new source validation.
