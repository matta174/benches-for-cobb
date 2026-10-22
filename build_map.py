#!/usr/bin/env python3
"""
Port the Benches for Gwinnett map (index.html) to Cobb.

Takes the Gwinnett index.html as a template, swaps the embedded data line
(D, COUNTY, CITIES) for Cobb data built from cobb_bus_stop_census.csv and the
Cobb GIS boundary layers, and rewrites the Gwinnett-specific copy.

Run after build_census.py:  python3 build_map.py path/to/gwinnett/index.html
"""
import csv, json, math, os, re, sys
from shapely.geometry import shape, mapping, Polygon, MultiPolygon, LineString
from shapely.ops import polygonize, unary_union, transform
from pyproj import Transformer

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "sources")
to_wgs = Transformer.from_crs("EPSG:2240", "EPSG:4326", always_xy=True).transform

J = {"easiest": "EASIEST", "medium": "MEDIUM", "hard": "HARD", "out of scope": "OUT OF SCOPE", "unknown": "UNKNOWN"}

def num(v):
    try:
        f = float(v); return None if math.isnan(f) else f
    except Exception:
        return None

def rings_to_wgs(rings):
    polys = [Polygon(r) for r in rings if len(r) > 3]
    g = unary_union(polys)
    g = transform(to_wgs, g)
    return g.simplify(0.00005, preserve_topology=True)

def main(template):
    rows = list(csv.DictReader(open(os.path.join(HERE, "cobb_bus_stop_census.csv"))))
    D = []
    for r in rows:
        sr = r["state_route"]
        sr_out = num(sr) if sr and re.fullmatch(r"[\d.]+", sr) else (sr or None)
        D.append({"i": int(r["stop_id"]), "n": r["stop_name"], "c": r["city"], "j": J[r["permit_difficulty"]],
                  "jf": r["permit_path"], "r": r["road"] or "", "sr": sr_out, "sp": None,
                  "ro": r["routes"], "t": float(r["trips_per_weekday"]),
                  "sw": 1 if r["has_sidewalk_15ft"] == "True" else 0,
                  "p": num(r["priority"]) or 0.0, "la": float(r["lat"]), "lo": float(r["lon"])})
    D.sort(key=lambda d: d["i"])

    b = json.load(open(os.path.join(SRC, "cobb_boundary_2240.json")))
    lines = [LineString(p) for f in b["features"] for p in f["geometry"]["paths"] if len(p) > 1]
    county = max(polygonize(unary_union(lines)), key=lambda p: p.area)
    county = transform(to_wgs, county).simplify(0.00005, preserve_topology=True)
    COUNTY = {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": mapping(county), "properties": {}}]}

    c = json.load(open(os.path.join(SRC, "cobb_cities_2240.json")))
    feats = []
    for f in c["features"]:
        g = rings_to_wgs(f["geometry"]["rings"])
        feats.append({"type": "Feature", "geometry": mapping(g), "properties": {"n": f["attributes"]["NAME"]}})
    CITIES = {"type": "FeatureCollection", "features": feats}

    def jd(o): return json.dumps(o, separators=(",", ":"), ensure_ascii=False)
    def rnd(o):
        return re.sub(r"(\d+\.\d{7,})", lambda m: f"{float(m.group(1)):.6f}", o)
    data_line = "const D=" + jd(D) + ", COUNTY=" + rnd(jd(COUNTY)) + ", CITIES=" + rnd(jd(CITIES)) + ";"

    html = open(template, encoding="utf-8").read()
    lines_ = html.split("\n")
    idx = next(i for i, l in enumerate(lines_) if l.startswith("const D="))
    lines_[idx] = data_line
    html = "\n".join(lines_)

    counts = {}
    for d in D: counts[d["j"]] = counts.get(d["j"], 0) + 1
    n = len(D)
    easiest = sum(1 for d in D if d["j"] == "EASIEST")
    easiest_sw = sum(1 for d in D if d["j"] == "EASIEST" and d["sw"])
    cities_n = {}
    for d in D:
        if d["j"] == "MEDIUM": cities_n[d["c"]] = cities_n.get(d["c"], 0) + 1
    outside = sum(1 for d in D if d["jf"].startswith("Not a Cobb permit"))
    other_out = counts.get("OUT OF SCOPE", 0) - outside + counts.get("UNKNOWN", 0)

    rep = [
        ("<title>A better world is possible: Gwinnett bench siting</title>", "<title>A better world is possible: Cobb bench siting</title>"),
        ('content="Every Ride Gwinnett bus stop,', 'content="Every CobbLinc bus stop,'),
        ("872 Gwinnett bus stops. Most have nowhere to sit. Colour is who we have to ask.", f"{n} CobbLinc bus stops. Most have nowhere to sit. Colour is who we have to ask."),
        ("all 872 list", f"all {n} list"), ("872 inline SVGs", f"{n} inline SVGs"), ("All 872 stops", f"All {n} stops"),
    ]
    for a, b_ in rep:
        assert a in html, a
        html = html.replace(a, b_)

    # Sources-and-permits sheet: replace the whole body between the two markers.
    start = html.index('<div class="dsec">Who has to permit a bench</div>')
    end = html.index('</div>\n    </div>\n  </aside>')
    city_items = "\n".join(
        f"            <li>{name.title()}, {k} stops</li>" for name, k in sorted(cities_n.items(), key=lambda x: -x[1]))
    sheet = f'''<div class="dsec">Who has to permit a bench</div>

        <div class="auth"><div class="an"><i style="background:var(--jur-easiest)"></i>Cobb County DOT<em>{easiest} stops</em></div>
          <p>County maintained right of way, including Mableton, which buys its transportation services from Cobb DOT under an intergovernmental agreement. {easiest_sw} of these stops already have a sidewalk by the OpenStreetMap read. One conversation covers a large share of the network.</p>
          <ul>
            <li><a href="https://www.cobbcounty.gov/transportation/transportation-policies-permitting/transportation-permitting-approvals/utilities-permitting" target="_blank" rel="noopener">Utility and encroachment permitting page</a> &middot; 770.528.1600</li>
            <li><a href="mailto:cobbdot@cobbcounty.gov">cobbdot@cobbcounty.gov</a></li>
            <li><a href="https://assets.cobbcounty.gov/files/2021-02/Utility_accommodations_in_rights_of_way_02-2021_0.pdf" target="_blank" rel="noopener">Utility accommodation in ROW ordinance (PDF)</a></li>
            <li>1890 County Services Parkway, Marietta GA 30008</li>
          </ul>
          <p>Transit side, for stop locations and ridership: <a href="https://www.cobbcounty.gov/transportation/cobblinc" target="_blank" rel="noopener">CobbLinc</a> &middot; 770.427.4444</p>
        </div>

        <div class="auth"><div class="an"><i style="background:var(--jur-hard)"></i>Georgia DOT<em>{counts.get("HARD",0)} stops</em></div>
          <p>State routes. Cobb Pkwy (US 41 / SR 3), Austell Rd (SR 5), South Cobb Dr (SR 280), Powder Springs St (SR 360), Marietta Pkwy (SR 120), Mableton Pkwy (SR 139). Highest service, hardest permit. Cobb sits in GDOT District 7.</p>
          <ul>
            <li><a href="https://www.dot.ga.gov/GDOT/pages/utilitypermitting.aspx" target="_blank" rel="noopener">Permitting and GPAS portal</a></li>
            <li><a href="https://www.dot.ga.gov/PartnerSmart/permits/Encroachment/Chapter7.pdf" target="_blank" rel="noopener">Driveway and Encroachment Control, Ch. 7 (PDF)</a></li>
            <li><a href="https://www.dot.ga.gov/PartnerSmart/permits/Documents/areaofficecontacts.pdf" target="_blank" rel="noopener">Area office contacts (PDF)</a></li>
          </ul>
        </div>

        <div class="auth"><div class="an"><i style="background:var(--jur-medium)"></i>Cities<em>{counts.get("MEDIUM",0)} stops</em></div>
          <p>Stops inside Marietta, Smyrna and Austell on roads that are not state routes. Cobb does not publish who maintains each road, so "city" here means inside city limits and not a state route. Some of these are county arterials. Each city sets its own ROW rules; confirm before asking.</p>
          <ul>
{city_items}
            <li><a href="https://www.mariettaga.gov/" target="_blank" rel="noopener">mariettaga.gov</a> &middot; <a href="https://www.smyrnaga.gov/" target="_blank" rel="noopener">smyrnaga.gov</a> &middot; <a href="https://www.austellga.gov/" target="_blank" rel="noopener">austellga.gov</a></li>
          </ul>
        </div>

        <div class="auth"><div class="an"><i style="background:var(--jur-out)"></i>Out of scope<em>{counts.get("OUT OF SCOPE",0)+counts.get("UNKNOWN",0)} stops</em></div>
          <p>{outside} stops sit in Fulton County, the MARTA Arts Center and H.E. Holmes tails of routes 10, R10, 25 and 30. Another {other_out} are on private property or mall ring roads that could not be resolved. Different jurisdiction, different ask.</p>
        </div>

        <div class="dsec">Where the data came from</div>
        <ul class="src">
          <li><b>Service levels, stop names, coordinates</b>
            CobbLinc GTFS, feed version Oct 19 2026, valid to Mar 27 2027.
            <a href="https://cobb.rideralerts.com/InfoPoint/gtfs-zip.ashx" target="_blank" rel="noopener">gtfs-zip.ashx</a></li>
          <li><b>Road names and class</b>
            Cobb County GIS, Roads (open data). No maintainer or speed limit field, so speed is unknown for every stop.
            <a href="https://gis.cobbcounty.gov/gisserver/rest/services/openData/OpenDataCobbRoadsPublic/MapServer/0" target="_blank" rel="noopener">MapServer layer 0</a></li>
          <li><b>State routes</b>
            GDOT State Route Network, mainline routes within 90 ft of a stop.
            <a href="https://rnhp.dot.ga.gov/hosting/rest/services/GDOT_STATE_ROUTE_NETWORK/MapServer/0" target="_blank" rel="noopener">MapServer layer 0</a></li>
          <li><b>Sidewalk presence</b>
            OpenStreetMap: separate sidewalk ways within 15 ft of the stop, or a sidewalk tag on the road for the side the stop is on. Cobb sells its sidewalk layer rather than publishing it.
            <a href="https://overpass-api.de/" target="_blank" rel="noopener">Overpass API</a></li>
          <li><b>City limits and county boundary</b>
            <a href="https://gis.cobbcounty.gov/gisserver/rest/services/cobbpublic/cobbboundarymapwm/MapServer" target="_blank" rel="noopener">Cobb Boundaries MapServer</a></li>
          <li><b>Everything else</b>
            <a href="https://geo-cobbcountyga.opendata.arcgis.com/" target="_blank" rel="noopener">Cobb County Open Data</a> &middot;
            <a href="https://www.cobbcounty.gov/transportation/cobblinc" target="_blank" rel="noopener">CobbLinc</a></li>
        </ul>

        <p class="note"><b>Read this before you trust it.</b>
        Sidewalk means OpenStreetMap has a sidewalk mapped near the stop. OSM coverage in Cobb is incomplete, so "no sidewalk" can mean "nobody mapped it yet". It says nothing about width, condition, or whether there is room for a bench without blocking the pedestrian route. GTFS coordinates can sit 30 to 60 ft off the actual pole. Trips per weekday is service, not ridership: it tells you how long you wait, not how many people wait. Every stop needs eyes on it before anything gets built.
        Map data &copy; OpenStreetMap contributors, tiles &copy; CARTO.</p>
      '''
    html = html[:start] + sheet + html[end:]

    # Speed limit slider is meaningless without speed data; hide the group.
    html = html.replace('<span class="lab">Road speed limit <b id="spdLab"></b></span>',
                        '<span class="lab" hidden>Road speed limit <b id="spdLab"></b></span>')
    html = html.replace("DeKalb or private", "Fulton or private")
    html = re.sub(r'(<div class="group">\s*<span class="lab" hidden>Road speed limit)', r'<div class="group" hidden>\n        <span class="lab" hidden>Road speed limit', html)

    # Inline Leaflet's stylesheet so the page works where third-party CSS is blocked.
    css_path = os.path.join(SRC, "leaflet.min.css")
    if os.path.exists(css_path):
        css = open(css_path, encoding="utf-8").read().replace("</style", "<\\/style")
        html = html.replace('<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css">',
                            "<style>/* Leaflet 1.9.4, BSD-2-Clause, inlined */\n" + css + "</style>")

    out = os.path.join(HERE, "index.html")
    open(out, "w", encoding="utf-8").write(html)
    print(f"wrote {out}: {n} stops; counts {counts}; easiest with sidewalk {easiest_sw}")

if __name__ == "__main__":
    main(sys.argv[1])
