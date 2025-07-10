from pyproj import Transformer, CRS
from shapely.geometry import Polygon
import pandas as pd
import ast

def get_utm_crs(lon, lat):
    utm_zone = int((lon + 180) / 6) + 1
    is_northern = lat >= 0
    return CRS.from_epsg(32600 + utm_zone) if is_northern else CRS.from_epsg(32700 + utm_zone)

def offsets_to_polygon(offsets, ref_point, spacing=100):
    """
    Converts a list of 100m-spaced offsets back into a Shapely Polygon in EPSG:4326.
    
    Parameters:
        offsets (List[List[int]]): List of [dx, dy] grid offsets from the reference point.
        ref_point (Tuple[float, float]): Reference point (longitude, latitude).
        spacing (int): Spacing in meters (default is 100m).

    Returns:
        Polygon: A Shapely polygon in lat/lon (EPSG:4326).
    """
    utm_crs = get_utm_crs(*ref_point)
    transformer_to_utm = Transformer.from_crs("epsg:4326", utm_crs, always_xy=True)
    transformer_from_utm = Transformer.from_crs(utm_crs, "epsg:4326", always_xy=True)

    ref_x, ref_y = transformer_to_utm.transform(*ref_point)
    coords = []
    for point in offsets:
        try:
            dx, dy = point[0], point[1]
            x = ref_x + dx * spacing
            y = ref_y + dy * spacing
            lon, lat = transformer_from_utm.transform(x, y)
            coords.append((lon, lat))
        except Exception as e:
            print(f"Error processing point {point}: {e}")
            continue

    # Ensure the polygon is closed
    if coords[0] != coords[-1]:
        coords.append(coords[0])

    return Polygon(coords)

if __name__ == "__main__":
    # open csv and read offsets_100m
    df = pd.read_csv('ndvi_results.csv')
    df['geometry'] = None
    for index, row in df.iterrows():
        offsets = ast.literal_eval(row['offsets_100m'])
        ref_point = ast.literal_eval(row['ref_point'])
        polygon = offsets_to_polygon(offsets, ref_point)
        # coordinates to polygon geojson
        geojson = {
            "type": "Polygon",
            "coordinates": [list(polygon.exterior.coords)]
        }
        df.at[index, 'geometry'] = geojson
    df = df.drop('offsets_100m', axis=1)
    # save to new csv
    df.to_csv('ndvi_polygons.csv', index=False)

