# Benches for Cobb

Every CobbLinc bus stop, scored by who has to permit a bench, whether there is already a sidewalk, and how long you wait.

A fork of [Benches for Gwinnett](https://github.com/matta174/benches-for-gwinnett), same method, pointed at Cobb. Read that README first; this one covers what is different.

CobbLinc runs 625 stops across 10 routes (R10 rapid, the Cumberland circulator and eight locals). The median stop sees 32 bus trips per weekday. Unlike Gwinnett, nearly every stop also has Sunday service.

The headline: **Cobb County DOT controls the right of way at 262 of 625 stops, and 152 of those already have a sidewalk.** That is 42% of the system on the easiest permit, 24% on the easiest permit with a walk to put a bench behind. The hard news is the other direction: **235 stops, 38% of the system, sit on state routes** (Cobb Pkwy, Austell Rd, South Cobb Dr, Powder Springs St, Marietta Pkwy, Mableton Pkwy), and those are the busy ones. Cobb's transit runs on GDOT roads to a degree Gwinnett's does not.

## What is here

```
index.html                   the map, single file, no build step (same UI as Gwinnett)
cobb_bus_stop_census.csv     all 625 stops, 21 columns
fetch_sources.py             downloads every input into sources/
build_census.py              builds the CSV from sources/
build_map.py                 builds index.html from the CSV + the Gwinnett index.html as a template
```

To rebuild: `pip install pandas shapely pyproj`, then `python3 fetch_sources.py && python3 build_census.py && python3 build_map.py path/to/gwinnett/index.html`.

## Where the data came from, and what Cobb does not publish

Everything is public. Nothing is scraped, licensed, or private.

| What | Source | Link |
|---|---|---|
| Stop names, coordinates, routes, service levels | **CobbLinc GTFS**. Feed version Oct 19 2026, valid through Mar 27 2027. 625 stops, 10 routes, 1,177 trips, 45,893 stop times. Same Avail InfoPoint platform Ride Gwinnett uses. | [gtfs-zip.ashx](https://cobb.rideralerts.com/InfoPoint/gtfs-zip.ashx) |
| Road names, functional class | **Cobb County GIS, Roads** (open data). 41,511 segments. `FUNCTIONALCLASS` is one of ARTERIAL, MAJOR, MINOR, LOCAL, INTERSTATE, RAMP, PRIVATE. **There is no maintainer field and no speed limit.** Cobb sells its DOT centerline file (the one with speed limits) for $500. | [MapServer/0](https://gis.cobbcounty.gov/gisserver/rest/services/openData/OpenDataCobbRoadsPublic/MapServer/0) |
| State routes | **GDOT State Route Network**, mainline routes (`FUNCTION_TYPE = 1`). Used because the Cobb layer cannot say which roads are state. | [MapServer/0](https://rnhp.dot.ga.gov/hosting/rest/services/GDOT_STATE_ROUTE_NETWORK/MapServer/0) |
| Sidewalk presence | **OpenStreetMap** via Overpass. Separate sidewalk ways (`highway=footway` + `footway=sidewalk`) and roads carrying `sidewalk=*` tags. Cobb's planimetric sidewalk layer is fee based and was not used. | [Overpass API](https://overpass-api.de/) |
| City limits, county boundary | **Cobb County GIS, Cobb Boundaries**, layers 3 (Cities) and 0 (County Boundary). | [MapServer](https://gis.cobbcounty.gov/gisserver/rest/services/cobbpublic/cobbboundarymapwm/MapServer) |

Portals: [Cobb County Open Data](https://geo-cobbcountyga.opendata.arcgis.com/) and [CobbLinc](https://www.cobbcounty.gov/transportation/cobblinc).

Data pulled **Oct 22 2026**. OSM snapshot in the Overpass mirror was July 28 2026.

## Columns

Same as Gwinnett, with these differences:

| Column | Change |
|---|---|
| `speed_limit` | Always blank. Cobb does not publish it. The map hides the speed slider. |
| `state_route` | Number for a mainline (3, 5, 120, 139, 280, 360), or number plus suffix for a spur or connector (`5CO`). |
| `trips_saturday`, `trips_sunday` | New. Cobb runs seven days. |
| `osm_sidewalk_ways_within_50ft` | Replaces `sidewalk_polygons_within_50ft`. Count of separate OSM sidewalk ways within 50 ft. |
| `osm_road_sidewalk_tag` | New. The `sidewalk` tag on the nearest OSM road within 60 ft, if any (`both`, `right`, `left=no;right=separate`, ...). |
| `jurisdiction` | New value `Cobb County DOT (Mableton, by IGA)`, see below. `City (likely)` instead of `City`, see below. |

## How each field was derived

**Service levels.** CobbLinc uses `calendar.txt` with one service per day type (weekday, Saturday, Sunday). Trips were counted over the first full Mon to Sun week in the feed window (Oct 26 to Nov 1, 2026), `calendar_dates` exceptions applied, then weekday trips divided by 5.

**Jurisdiction.** Each stop was projected to EPSG:2240 (Georgia West, feet) and matched to the nearest Cobb road centerline within 150 ft, and separately to the nearest GDOT mainline state route within 90 ft. Then, in order:

1. No Cobb centerline nearby and outside the county boundary → `Outside Cobb (Fulton / MARTA)`. The Arts Center and H.E. Holmes tails of routes 10, R10, 25 and 30.
2. No centerline but inside the county → `Unclear`. Three mall ring roads.
3. A GDOT mainline within 90 ft, or a Cobb segment classed INTERSTATE or RAMP → `GDOT (state route)`, hard.
4. Cobb segment classed PRIVATE → `Private`, out of scope.
5. Inside Mableton → `Cobb County DOT (Mableton, by IGA)`, easiest.
6. Inside Marietta, Smyrna or Austell → `City (likely)`, medium.
7. Otherwise → `Cobb County DOT`, easiest.

Two things to understand about this. Gwinnett's census had a `MAINTBY` field that said who maintains each road. Cobb's free layer does not, so **"city" here means "inside city limits and not a state route"**, which will mislabel county arterials that pass through Marietta and Smyrna. That is why it says `City (likely)`. And **Mableton** (incorporated 2023) is coded as county because it buys transportation services, including road work, from Cobb DOT under a one-year intergovernmental agreement while a ten-year deal is negotiated ([MDJ, via Yahoo](https://www.yahoo.com/news/mableton-agrees-pay-cobb-county-122740002.html)). Confirm with the city before asking.

**Sidewalk.** `has_sidewalk_15ft` is true if either (a) a separate OSM sidewalk way lies within 15 ft of the stop, or (b) the nearest tagged OSM road within 60 ft has a sidewalk on the side the stop is on, computed from the way's direction. 267 stops pass on (a), 162 more on (b). `sidewalk=left` or `right` on the far side does not count.

**Priority.** Same crude key as Gwinnett: `trips_per_weekday × difficulty_tier × has_sidewalk`, tier 3 county, 2 city, 1 GDOT, 0 out of scope. It encodes an opinion. Do not cite it; sort on the real columns.

## Read this before you trust it

- **Sidewalk means OpenStreetMap has one mapped there.** OSM coverage in Cobb is partial, especially outside the Cumberland and Marietta cores. "No sidewalk" can mean "nobody mapped it yet", and the inverse error (a sidewalk mapped on a road where the stop side has none) exists too. This is weaker evidence than Gwinnett's county planimetrics. The county's own sidewalk layer is on the data sales list; the open records route (O.C.G.A. 50-18-71) or a one-time purchase would replace this column with something solid.
- **No speed limits.** The 45 mph setback logic from the Gwinnett pilot plan has to be applied by eye, or from the purchased centerline file.
- **City vs county is a guess inside city limits.** See above. The maintainer question is the single most useful thing to ask Cobb DOT, and it is one email.
- **GTFS coordinates drift** 30 to 60 ft off the pole. Same as Gwinnett.
- **Trips per weekday is service, not ridership.** CobbLinc has automatic passenger counter data; open records request.
- **Nothing here has been ground truthed.** Not in Street View, not on foot. Every stop needs eyes on it before anything gets built.

## Who to ask

- **Cobb DOT**, utility and encroachment permitting: [permitting page](https://www.cobbcounty.gov/transportation/transportation-policies-permitting/transportation-permitting-approvals/utilities-permitting), cobbdot@cobbcounty.gov, 770.528.1600, 1890 County Services Pkwy, Marietta 30008. The county adopted GDOT's Utility Accommodation Policy for its own ROW ([ordinance PDF](https://assets.cobbcounty.gov/files/2021-02/Utility_accommodations_in_rights_of_way_02-2021_0.pdf)).
- **GDOT District 7** for the state routes: [permitting and GPAS portal](https://www.dot.ga.gov/GDOT/pages/utilitypermitting.aspx).
- **CobbLinc** for stop data and ridership: 770.427.4444.

## License

MIT for the code. The census is derived from public GTFS, county and state GIS, and OpenStreetMap (ODbL for the sidewalk column). Take it, fork it, do this in your county.
