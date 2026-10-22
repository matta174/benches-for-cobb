#!/usr/bin/env python3
"""
Download every input for the Cobb census into ./sources/.
All public. Re-run to refresh; GTFS changes a few times a year, GIS continuously.

  python3 fetch_sources.py
"""
import json, os, sys, time, urllib.request, urllib.parse, zipfile, io

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "sources"); os.makedirs(os.path.join(SRC, "gtfs"), exist_ok=True)
UA = {"User-Agent": "benches-for-cobb census (civic project)"}

def get(url, data=None, timeout=300):
    req = urllib.request.Request(url, data=data, headers=UA)
    return urllib.request.urlopen(req, timeout=timeout).read()

def esri_all(layer_url, params):
    """Page through an ArcGIS REST layer query."""
    feats, off = [], 0
    while True:
        p = dict(params, resultOffset=off, resultRecordCount=2000, f="json")
        d = json.loads(get(layer_url + "/query?" + urllib.parse.urlencode(p)))
        if "error" in d: raise RuntimeError(d["error"])
        f = d.get("features", []); feats += f; off += len(f)
        if not d.get("exceededTransferLimit") or not f: break
    return {"features": feats}

# 1. CobbLinc GTFS (Avail InfoPoint, same platform Ride Gwinnett uses)
print("GTFS ...")
z = zipfile.ZipFile(io.BytesIO(get("https://cobb.rideralerts.com/InfoPoint/gtfs-zip.ashx")))
z.extractall(os.path.join(SRC, "gtfs"))

# 2. Cobb County GIS, Roads (open data). FULLNAME + FUNCTIONALCLASS only; no maintainer, no speed limit.
print("Cobb roads ...")
roads = esri_all("https://gis.cobbcounty.gov/gisserver/rest/services/openData/OpenDataCobbRoadsPublic/MapServer/0",
                 {"where": "1=1", "outFields": "OBJECTID,FULLNAME,FUNCTIONALCLASS", "returnGeometry": "true", "outSR": 2240})
json.dump(roads, open(os.path.join(SRC, "cobb_roads_2240.json"), "w"))

# 3. Cobb County GIS, Cities and County Boundary
print("Cobb boundaries ...")
B = "https://gis.cobbcounty.gov/gisserver/rest/services/cobbpublic/cobbboundarymapwm/MapServer"
json.dump(esri_all(B + "/3", {"where": "1=1", "outFields": "NAME,CityCode", "returnGeometry": "true", "outSR": 2240}),
          open(os.path.join(SRC, "cobb_cities_2240.json"), "w"))
json.dump(esri_all(B + "/0", {"where": "1=1", "outFields": "*", "returnGeometry": "true", "outSR": 2240}),
          open(os.path.join(SRC, "cobb_boundary_2240.json"), "w"))

# 4. GDOT State Route Network, mainline routes (FUNCTION_TYPE 1) that touch the Cobb bounding box
print("GDOT state routes ...")
bbox = json.dumps({"xmin": -84.76, "ymin": 33.73, "xmax": -84.36, "ymax": 34.10, "spatialReference": {"wkid": 4326}})
G = "https://rnhp.dot.ga.gov/hosting/rest/services/GDOT_STATE_ROUTE_NETWORK/MapServer/0"
p = {"where": "FUNCTION_TYPE='1'", "geometry": bbox, "geometryType": "esriGeometryEnvelope", "inSR": 4326,
     "spatialRel": "esriSpatialRelIntersects", "outFields": "ROUTE_CODE,DIRECTION,COUNTY,FUNCTION_TYPE",
     "returnGeometry": "true", "outSR": 2240, "maxAllowableOffset": 3, "f": "json"}
open(os.path.join(SRC, "gdot_state_routes_2240.json"), "wb").write(get(G + "/query?" + urllib.parse.urlencode(p)))

# 5. OpenStreetMap sidewalks via Overpass. Cobb sells its sidewalk layer, so OSM is the free source.
print("OSM sidewalks (Overpass, can take a few minutes) ...")
q = """[out:json][timeout:240];
(
  way["highway"="footway"]["footway"="sidewalk"](33.73,-84.76,34.10,-84.36);
  way["highway"]["sidewalk"](33.73,-84.76,34.10,-84.36);
  way["highway"]["sidewalk:left"](33.73,-84.76,34.10,-84.36);
  way["highway"]["sidewalk:right"](33.73,-84.76,34.10,-84.36);
  way["highway"]["sidewalk:both"](33.73,-84.76,34.10,-84.36);
);
out geom;"""
for host in ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter"]:
    try:
        raw = get(host, data=urllib.parse.urlencode({"data": q}).encode(), timeout=600)
        open(os.path.join(SRC, "osm_sidewalks.json"), "wb").write(raw); break
    except Exception as e:
        print("  ", host, "failed:", e)
else:
    print("  no Overpass mirror answered; build_census.py will run without sidewalk data")

# 6. Leaflet CSS, inlined into index.html by build_map.py
open(os.path.join(SRC, "leaflet.min.css"), "wb").write(get("https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css"))

print("done. Now: python3 build_census.py")
