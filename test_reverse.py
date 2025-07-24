import struct
import base64
import zlib
import json
from shapely.geometry import Polygon, mapping
from pyproj import Transformer, CRS
import pandas as pd

def decode_ndvi_data_advanced(encoded_str):
    compressed = base64.b85decode(encoded_str)
    data = zlib.decompress(compressed)

    pos = 0
    ref_point = struct.unpack('>2f', data[pos:pos+8])
    pos += 8
    count, = struct.unpack('>H', data[pos:pos+2])
    pos += 2

    features = []
    for _ in range(count):
        mean_int, area_int = struct.unpack('>HH', data[pos:pos+4])
        pos += 4
        mean_ndvi = mean_int / 1000.0
        area_ha = area_int / 10.0

        n_offsets, = struct.unpack('>H', data[pos:pos+2])
        pos += 2

        offsets = []
        if n_offsets > 0:
            dx, dy = struct.unpack('>2h', data[pos:pos+4])
            pos += 4
            offsets.append([dx, dy])

            prev_dx, prev_dy = dx, dy
            for __ in range(n_offsets - 1):
                zz_dx, zz_dy = struct.unpack('>HH', data[pos:pos+4])
                pos += 4
                delta_dx = (zz_dx >> 1) ^ (-(zz_dx & 1))
                delta_dy = (zz_dy >> 1) ^ (-(zz_dy & 1))
                dx = prev_dx + delta_dx
                dy = prev_dy + delta_dy
                offsets.append([dx, dy])
                prev_dx, prev_dy = dx, dy

        features.append({
            'mean_ndvi': mean_ndvi,
            'area_ha': area_ha,
            'offsets': offsets
        })

    return {'ref_point': ref_point, 'features': features}

def get_utm_crs(lon, lat):
    if 33 <= lon < 39:
        zone = 36
    else:
        zone = 37
    return CRS.from_epsg(32600 + zone)

def offsets_to_polygon(ref_point, offsets, spacing=100):
    if not offsets:
        return None

    utm_crs = get_utm_crs(*ref_point)
    transformer_to_utm = Transformer.from_crs("epsg:4326", utm_crs, always_xy=True)
    transformer_from_utm = Transformer.from_crs(utm_crs, "epsg:4326", always_xy=True)

    ref_x, ref_y = transformer_to_utm.transform(*ref_point)

    coords_utm = [(ref_x + dx * spacing, ref_y + dy * spacing) for dx, dy in offsets]
    coords_lonlat = [transformer_from_utm.transform(x, y) for x, y in coords_utm]

    if coords_lonlat[0] != coords_lonlat[-1]:
        coords_lonlat.append(coords_lonlat[0])

    return Polygon(coords_lonlat)

def decode_to_csv(encoded_str, output_csv_path='ndvi_results.csv'):
    data = decode_ndvi_data_advanced(encoded_str)
    ref_point = data['ref_point']
    features = data['features']

    rows = []
    for feat in features:
        polygon = offsets_to_polygon(ref_point, feat['offsets'])
        geom_json = json.dumps(mapping(polygon)) if polygon else None
        rows.append({
            'ref_point': json.dumps([round(ref_point[0],6), round(ref_point[1],6)]),
            'mean_ndvi': round(feat['mean_ndvi'], 3),
            'area_ha': round(feat['area_ha'], 3),
            'geometry': geom_json
        })

    df = pd.DataFrame(rows)
    df.to_csv(output_csv_path, index=False)
    print(f"Decoded data saved to {output_csv_path}")

if __name__ == "__main__":
    with open("ndvi.txt", 'r') as f:
        encoded_str = f.read().strip()
    decode_to_csv(encoded_str)
