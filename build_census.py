#!/usr/bin/env python3
"""
Build cobb_bus_stop_census.csv.

A port of the Benches for Gwinnett census method to Cobb County / CobbLinc.
Same columns, same spirit, different inputs where Cobb publishes less.

Inputs (all public, all fetched by fetch_sources.py into ./sources/):
  sources/gtfs/*.txt                       CobbLinc GTFS static feed
  sources/cobb_roads_2240.json             Cobb GIS Roads (open data), GA West ft
  sources/cobb_cities_2240.json            Cobb GIS Cities, GA West ft
  sources/cobb_boundary_2240.json          Cobb GIS County Boundary (polyline), GA West ft
  sources/gdot_state_routes_2240.json      GDOT State Route Network, mainlines near Cobb, GA West ft
  sources/osm_sidewalks.json               OpenStreetMap sidewalk ways + roads with sidewalk tags (Overpass)

Run:  python3 build_census.py
"""
import csv, json, re, os, sys
from collections import defaultdict
from datetime import date, timedelta

import pandas as pd
from shapely.geometry import Point, LineString, Polygon, MultiLineString, shape
from shapely.ops import polygonize, unary_union
from shapely.strtree import STRtree
from pyproj import Transformer

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sources")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cobb_bus_stop_census.csv")

# WGS84 -> Georgia West (feet). Same projection the Gwinnett census used.
to_ft = Transformer.from_crs("EPSG:4326", "EPSG:2240", always_xy=True)

ROAD_MATCH_FT = 150      # nearest Cobb centerline must be within this, else "outside Cobb"
STATE_ROUTE_FT = 90      # a GDOT mainline within this makes the stop a state route stop
                         # (divided arterials put the LRS line up to ~80 ft from the far curb)
SIDEWALK_NEAR_FT = 15    # separate OSM sidewalk way within this = sidewalk at the stop
SIDEWALK_COUNT_FT = 50   # count of sidewalk features within this

# ---------------------------------------------------------------- GTFS
def load_gtfs():
    g = {}
    for f in ["stops", "trips", "stop_times", "calendar", "calendar_dates", "routes"]:
        p = os.path.join(SRC, "gtfs", f + ".txt")
        g[f] = pd.read_csv(p, dtype=str) if os.path.exists(p) else pd.DataFrame()
    return g

def service_days(g):
    """Map service_id -> set of weekday indexes (0=Mon) it runs on, using calendar.txt
    plus calendar_dates.txt exceptions, evaluated over one representative Mon-Sun week
    (the first full week inside the feed window). This mirrors the Gwinnett method."""
    cal = g["calendar"]
    cd = g["calendar_dates"]
    start = pd.to_datetime(cal["start_date"].min())
    # first Monday on/after start
    mon = start + pd.Timedelta(days=(7 - start.weekday()) % 7)
    week = [mon + pd.Timedelta(days=i) for i in range(7)]
    days = defaultdict(set)
    cols = ["monday","tuesday","wednesday","thursday","friday","saturday","sunday"]
    for _, r in cal.iterrows():
        s, e = pd.to_datetime(r["start_date"]), pd.to_datetime(r["end_date"])
        for i, d in enumerate(week):
            if s <= d <= e and r[cols[i]] == "1":
                days[r["service_id"]].add(i)
    if len(cd):
        for _, r in cd.iterrows():
            d = pd.to_datetime(r["date"])
            if d in week:
                i = week.index(d)
                if r["exception_type"] == "1": days[r["service_id"]].add(i)
                else: days[r["service_id"]].discard(i)
    return days, week

def service_levels(g):
    days, week = service_days(g)
    trips = g["trips"][["trip_id","service_id","route_id"]]
    st = g["stop_times"][["trip_id","stop_id"]].drop_duplicates()
    st = st.merge(trips, on="trip_id", how="left")
    routes = g["routes"].set_index("route_id")["route_short_name"].to_dict()
    weekday = defaultdict(float); sat = defaultdict(float); sun = defaultdict(float)
    served_routes = defaultdict(set)
    for stop_id, grp in st.groupby("stop_id"):
        for _, r in grp.iterrows():
            d = days.get(r["service_id"], set())
            weekday[stop_id] += len([x for x in d if x < 5])
            sat[stop_id] += 1 if 5 in d else 0
            sun[stop_id] += 1 if 6 in d else 0
            served_routes[stop_id].add(routes.get(r["route_id"], r["route_id"]))
    out = {}
    for s in set(list(weekday) + list(sat) + list(sun)):
        out[s] = dict(trips_per_weekday=round(weekday[s] / 5, 1),
                      trips_saturday=sat[s], trips_sunday=sun[s],
                      routes=",".join(sorted(served_routes[s], key=lambda x: (len(x), x))))
    return out, week

# ---------------------------------------------------------------- GIS helpers
def esri_lines(path, attr_keys):
    d = json.load(open(path))
    geoms, attrs = [], []
    for f in d["features"]:
        g = f.get("geometry") or {}
        paths = g.get("paths") or []
        if not paths: continue
        ls = [LineString(p) for p in paths if len(p) > 1]
        if not ls: continue
        geoms.append(ls[0] if len(ls) == 1 else MultiLineString(ls))
        attrs.append({k: f["attributes"].get(k) for k in attr_keys})
    return geoms, attrs

def esri_polys(path, attr_keys):
    d = json.load(open(path))
    geoms, attrs = [], []
    for f in d["features"]:
        rings = (f.get("geometry") or {}).get("rings") or []
        if not rings: continue
        polys = [Polygon(r) for r in rings if len(r) > 3]
        geoms.append(unary_union(polys))
        attrs.append({k: f["attributes"].get(k) for k in attr_keys})
    return geoms, attrs

def county_polygon():
    """The county boundary layer is a polyline; polygonize it."""
    lines, _ = esri_lines(os.path.join(SRC, "cobb_boundary_2240.json"), [])
    merged = unary_union(lines)
    polys = list(polygonize(merged))
    if not polys:
        return None
    return max(polys, key=lambda p: p.area)

def osm_sidewalks(path):
    """Returns (separate_sidewalk_lines, road_lines_with_tag) in GA West feet."""
    if not os.path.exists(path):
        return [], [], []
    d = json.load(open(path))
    sep, roads, road_tags = [], [], []
    for e in d.get("elements", []):
        if e.get("type") != "way" or "geometry" not in e: continue
        pts = [to_ft.transform(p["lon"], p["lat"]) for p in e["geometry"]]
        if len(pts) < 2: continue
        t = e.get("tags", {})
        if t.get("highway") == "footway" and t.get("footway") == "sidewalk":
            sep.append(LineString(pts))
        else:
            tag = t.get("sidewalk") or t.get("sidewalk:both")
            if not tag:
                l, r = t.get("sidewalk:left"), t.get("sidewalk:right")
                if l or r: tag = f"left={l or 'no'};right={r or 'no'}"
            roads.append(LineString(pts)); road_tags.append(tag or "")
    return sep, roads, road_tags

def sidewalk_sides(tag):
    """Which sides of the way have a sidewalk, from an OSM tag. Returns set of {'left','right'}."""
    if not tag: return set()
    t = tag.lower()
    if t.startswith("left=") or t.startswith("right="):
        out = set()
        for side, val in re.findall(r"(left|right)=(\w+)", t):
            if val not in ("no", "none", ""): out.add(side)
        return out
    if t in ("no", "none"): return set()
    if t == "left": return {"left"}
    if t == "right": return {"right"}
    return {"left", "right"}   # both, yes, separate

def side_of_way(line, pt):
    """'left' or 'right' of the way's digitised direction, at the nearest segment."""
    coords = list(line.coords)
    best, bi = None, 0
    for i in range(len(coords) - 1):
        seg = LineString([coords[i], coords[i + 1]])
        d = seg.distance(pt)
        if best is None or d < best: best, bi = d, i
    (x1, y1), (x2, y2) = coords[bi], coords[bi + 1]
    cross = (x2 - x1) * (pt.y - y1) - (y2 - y1) * (pt.x - x1)
    return "left" if cross > 0 else "right"

# ---------------------------------------------------------------- main
def main():
    g = GTFS = load_gtfs()
    stops = g["stops"].copy()
    stops = stops[stops.get("location_type", "0").fillna("0").isin(["0", ""])]
    stops["lat"] = stops["stop_lat"].astype(float); stops["lon"] = stops["stop_lon"].astype(float)
    svc, week = service_levels(g)
    print(f"GTFS: {len(stops)} stops, {len(g['routes'])} routes, {len(g['trips'])} trips, "
          f"{len(g['stop_times'])} stop_times. Representative week starts {week[0].date()}.")

    roads, road_attrs = esri_lines(os.path.join(SRC, "cobb_roads_2240.json"), ["FULLNAME","FUNCTIONALCLASS"])
    road_tree = STRtree(roads)
    cities, city_attrs = esri_polys(os.path.join(SRC, "cobb_cities_2240.json"), ["NAME"])
    county = county_polygon()
    srs, sr_attrs = esri_lines(os.path.join(SRC, "gdot_state_routes_2240.json"), ["ROUTE_CODE","DIRECTION"])
    sr_tree = STRtree(srs)
    sw_sep, sw_roads, sw_tags = osm_sidewalks(os.path.join(SRC, "osm_sidewalks.json"))
    sw_sep_tree = STRtree(sw_sep) if sw_sep else None
    sw_road_tree = STRtree(sw_roads) if sw_roads else None
    have_sidewalk_data = bool(sw_sep or sw_roads)
    print(f"GIS: {len(roads)} Cobb road segments, {len(cities)} cities, {len(srs)} GDOT mainline features, "
          f"{len(sw_sep)} OSM sidewalk ways, {len(sw_roads)} OSM roads with sidewalk tags.")

    rows = []
    for _, s in stops.iterrows():
        x, y = to_ft.transform(s["lon"], s["lat"])
        pt = Point(x, y)

        # city
        city = "UNINCORPORATED"
        for poly, a in zip(cities, city_attrs):
            if poly.contains(pt):
                city = a["NAME"].upper(); break
        in_county = county.contains(pt) if county is not None else True

        # nearest Cobb centerline
        road, fclass, road_dist = None, None, None
        i = road_tree.nearest(pt)
        if i is not None:
            d = roads[i].distance(pt)
            if d <= ROAD_MATCH_FT:
                road, fclass, road_dist = road_attrs[i]["FULLNAME"], road_attrs[i]["FUNCTIONALCLASS"], d

        # state route
        state_route, sr_dist = None, None
        j = sr_tree.nearest(pt)
        if j is not None:
            d = srs[j].distance(pt)
            if d <= STATE_ROUTE_FT:
                code = sr_attrs[j]["ROUTE_CODE"]            # e.g. 00028000 -> SR 280, 000003CO -> SR 3 connector
                num = int(code[:6]); suffix = code[6:8]
                state_route = float(num) if suffix == "00" else f"{num}{suffix}"
                sr_dist = d

        # jurisdiction
        if not in_county and road is None:
            jur, path, diff = "Outside Cobb (Fulton / MARTA)", "Not a Cobb permit", "out of scope"
        elif road is None:
            jur, path, diff = "Unclear", "Verify jurisdiction", "unknown"
        elif state_route is not None or (fclass in ("INTERSTATE", "RAMP")):
            jur, path, diff = "GDOT (state route)", "GDOT encroachment permit (hard)", "hard"
        elif fclass == "PRIVATE":
            jur, path, diff = "Private", "Private property owner", "out of scope"
        elif city == "MABLETON":
            # Mableton (incorporated 2023) buys transportation services from Cobb DOT under a
            # one-year intergovernmental agreement while a 10-year deal is negotiated.
            jur, path, diff = "Cobb County DOT (Mableton, by IGA)", "County ROW (easiest), confirm with Mableton", "easiest"
        elif city != "UNINCORPORATED":
            jur, path, diff = "City (likely)", "City ROW permit (medium)", "medium"
        else:
            jur, path, diff = "Cobb County DOT", "County ROW (easiest)", "easiest"

        # sidewalk (OSM)
        sw_near, sw_count, road_sw_tag = None, None, ""
        if have_sidewalk_data:
            near = sw_sep_tree.query(pt.buffer(SIDEWALK_NEAR_FT)) if sw_sep_tree else []
            cnt = sw_sep_tree.query(pt.buffer(SIDEWALK_COUNT_FT)) if sw_sep_tree else []
            sw_near = any(sw_sep[k].distance(pt) <= SIDEWALK_NEAR_FT for k in near)
            sw_count = sum(1 for k in cnt if sw_sep[k].distance(pt) <= SIDEWALK_COUNT_FT)
            if sw_road_tree:
                kk = sw_road_tree.nearest(pt)
                if kk is not None and sw_roads[kk].distance(pt) <= 60:
                    road_sw_tag = sw_tags[kk]
                    sides = sidewalk_sides(road_sw_tag)
                    if sides and side_of_way(sw_roads[kk], pt) in sides:
                        sw_near = True

        lv = svc.get(s["stop_id"], dict(trips_per_weekday=0, trips_saturday=0, trips_sunday=0, routes=""))
        tier = {"easiest": 3, "medium": 2, "hard": 1}.get(diff, 0)
        priority = round(lv["trips_per_weekday"] * tier * (1 if sw_near else 0), 1) if sw_near is not None else None

        rows.append(dict(
            stop_id=s["stop_id"], stop_name=s["stop_name"], city=city, jurisdiction=jur, permit_path=path,
            permit_difficulty=diff, road=road, state_route=state_route, speed_limit=None,
            routes=lv["routes"], trips_per_weekday=lv["trips_per_weekday"],
            trips_saturday=lv["trips_saturday"], trips_sunday=lv["trips_sunday"],
            has_sidewalk_15ft=sw_near, osm_sidewalk_ways_within_50ft=sw_count, osm_road_sidewalk_tag=road_sw_tag,
            priority=priority, lat=s["lat"], lon=s["lon"],
            streetview=f"https://www.google.com/maps/@?api=1&map_action=pano&viewpoint={s['lat']},{s['lon']}",
            gmaps=f"https://www.google.com/maps/search/?api=1&query={s['lat']},{s['lon']}",
        ))

    df = pd.DataFrame(rows)
    df = df.sort_values(["priority", "trips_per_weekday"], ascending=[False, False], na_position="last")
    df.to_csv(OUT, index=False)
    print(f"\nWrote {OUT}: {len(df)} stops")
    print(df["jurisdiction"].value_counts().to_string())
    print("\ncity:\n" + df["city"].value_counts().to_string())
    if have_sidewalk_data:
        print("\nhas_sidewalk_15ft:\n" + df["has_sidewalk_15ft"].value_counts(dropna=False).to_string())
    print(f"\nmedian trips/weekday: {df['trips_per_weekday'].median()}")

if __name__ == "__main__":
    main()
