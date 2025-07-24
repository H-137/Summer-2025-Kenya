import ee
import json
import geopandas as gpd
from shapely.geometry import shape, Polygon
import pandas as pd
import time
import os
from pyproj import Transformer, CRS

def run_ndvi_export(minLon, minLat, maxLon, maxLat, start_date, end_date, min_area, key_path=None):
    start_time = time.time()

    # Initialize Earth Engine
    if key_path is None:
        key_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "ee-key.json")
    with open(key_path, 'r') as f:
        creds = json.load(f)
    ee.Initialize(ee.ServiceAccountCredentials(creds['client_email'], key_path))

    # Constants
    CLD_THRESH = 50
    CLD_PRB_THRESH = 60
    NIR_DRK_THRESH = 0.15
    CLD_PRJ_DIST = 1
    BUFFER = 50
    NUM_RESULTS = 10
    NDVI_THRESH = 0.3

    bbox = [float(minLon), float(minLat), float(maxLon), float(maxLat)]
    geom = ee.Geometry.BBox(*bbox)
    AREA_MIN = float(min_area)
    
    center_lon = (float(minLon) + float(maxLon)) / 2
    center_lat = (float(minLat) + float(maxLat)) / 2
    ref_point = (center_lon, center_lat)

    # Cloud and shadow filtering
    def get_s2_sr_cld_col(aoi, start_date, end_date):
        s2_sr = (ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
                 .filterBounds(aoi)
                 .filterDate(start_date, end_date)
                 .filter(ee.Filter.lte('CLOUDY_PIXEL_PERCENTAGE', CLD_THRESH)))
        s2_cld = (ee.ImageCollection('COPERNICUS/S2_CLOUD_PROBABILITY')
                  .filterBounds(aoi)
                  .filterDate(start_date, end_date))
        return ee.ImageCollection(ee.Join.saveFirst('s2cloudless').apply(**{
            'primary': s2_sr,
            'secondary': s2_cld,
            'condition': ee.Filter.equals(leftField='system:index', rightField='system:index')
        }))

    def add_cloud_bands(img):
        cld_prb = ee.Image(img.get('s2cloudless')).select('probability')
        is_cloud = cld_prb.gt(CLD_PRB_THRESH).rename('clouds')
        return img.addBands([cld_prb, is_cloud])

    def add_shadow_bands(img):
        not_water = img.select('SCL').neq(6)
        dark_pixels = img.select('B8').lt(NIR_DRK_THRESH * 1e4).multiply(not_water).rename('dark_pixels')
        azimuth = ee.Number(90).subtract(ee.Number(img.get('MEAN_SOLAR_AZIMUTH_ANGLE')))
        cld_proj = (img.select('clouds')
                    .directionalDistanceTransform(azimuth, CLD_PRJ_DIST * 10)
                    .reproject(crs=img.select(0).projection(), scale=100)
                    .select('distance').mask().rename('cloud_transform'))
        shadows = cld_proj.multiply(dark_pixels).rename('shadows')
        return img.addBands([dark_pixels, cld_proj, shadows])

    def add_cld_shdw_mask(img):
        img_cloud = add_cloud_bands(img)
        img_cloud_shadow = add_shadow_bands(img_cloud)
        is_cld_shdw = img_cloud_shadow.select('clouds').add(img_cloud_shadow.select('shadows')).gt(0)
        is_cld_shdw = (is_cld_shdw.focalMin(2).focalMax(BUFFER * 2 / 20)
                       .reproject(crs=img.select([0]).projection(), scale=20)
                       .rename('cloudmask'))
        return img_cloud_shadow.addBands(is_cld_shdw)

    def apply_cld_shdw_mask(img):
        return img.updateMask(img.select('cloudmask').Not())

    def get_utm_crs(lon, lat):
            # Kenya mostly lies in zone 37N (EPSG:32637)
            # Optionally support zone 36N for far western Kenya
            if 33 <= lon < 39:
                zone = 36
            else:
                zone = 37
            return CRS.from_epsg(32600 + zone)

    def snap_geometry_to_grid(geom, ref_point, spacing=100):
        utm_crs = get_utm_crs(*ref_point)
        transformer_to_utm = Transformer.from_crs("epsg:4326", utm_crs, always_xy=True)
        transformer_from_utm = Transformer.from_crs(utm_crs, "epsg:4326", always_xy=True)

        def snap_coords(coords):
            snapped = []
            for x, y in coords:
                xm, ym = transformer_to_utm.transform(x, y)
                x_refm, y_refm = transformer_to_utm.transform(*ref_point)
                dx = round((xm - x_refm) / spacing) * spacing
                dy = round((ym - y_refm) / spacing) * spacing
                snapped_x, snapped_y = transformer_from_utm.transform(x_refm + dx, y_refm + dy)
                snapped.append((snapped_x, snapped_y))
            return snapped

        if isinstance(geom, Polygon):
            return Polygon(snap_coords(geom.exterior.coords))

        return geom

    def polygon_to_offsets(polygon: Polygon, ref_point, spacing=100):
        utm_crs = get_utm_crs(*ref_point)
        transformer_to_utm = Transformer.from_crs("epsg:4326", utm_crs, always_xy=True)
        ref_x, ref_y = transformer_to_utm.transform(*ref_point)

        offsets = []
        for x, y in polygon.exterior.coords:
            xm, ym = transformer_to_utm.transform(x, y)
            dx = round((xm - ref_x) / spacing)
            dy = round((ym - ref_y) / spacing)
            offsets.append([dx, dy])
        return offsets

    # Processing
    s2_sr_cld_col = get_s2_sr_cld_col(geom, start_date, end_date)
    masked_col = s2_sr_cld_col.map(add_cld_shdw_mask).map(apply_cld_shdw_mask)
    image = masked_col.median().clip(geom)
    ndvi = image.normalizedDifference(['B8', 'B4']).rename('NDVI')
    ndvi_mask = ndvi.gt(NDVI_THRESH).toInt()

    vectors = (ndvi_mask.reduceToVectors(
        geometry=geom,
        scale=100,
        geometryType='polygon',
        labelProperty='ndvi_zone',
        maxPixels=1e13
    ).map(lambda f: f.set('area', f.geometry().area(1))))

    vectors = vectors.filter(ee.Filter.gte('area', AREA_MIN))
    vectors = vectors.filter(ee.Filter.lt('area', 1e7))
    vectors = vectors.sort('area', False).limit(NUM_RESULTS)

    def add_mean_ndvi(feature):
        mean = ndvi.reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=feature.geometry(),
            scale=100,
            maxPixels=1e13
        ).get('NDVI')
        return feature.set('mean_ndvi', mean)

    features_with_ndvi = vectors.map(add_mean_ndvi)
    geojson = features_with_ndvi.getInfo()

    results = []
    for f in geojson['features']:
        props = f['properties']
        mean_ndvi = props.get('mean_ndvi')
        area = props.get('area')

        geom_shape = shape(f['geometry']).simplify(tolerance=0.0001, preserve_topology=True)
        snapped_geom = snap_geometry_to_grid(geom_shape, ref_point)

        results.append({
            'ref_point': [ref_point[0], ref_point[1]],
            'mean_ndvi': round(float(mean_ndvi), 2) if mean_ndvi is not None else None,
            'area_ha': round(area / 10000, 2) if area is not None else None,
            'offsets_100m': polygon_to_offsets(snapped_geom, ref_point)
        })   

    duration = time.time() - start_time
    return {
        'count': len(results),
        'results': results,
        'duration_seconds': duration
    }

# For debugging: allow running standalone
if __name__ == "__main__":
    import sys
    if len(sys.argv) != 9:
        print("Usage: python export_ndvi.py minLon minLat maxLon maxLat start_date end_date min_area key_path")
        sys.exit(1)

    output = run_ndvi_export(*sys.argv[1:])
    pd.DataFrame(output['results']).to_csv('ndvi_results.csv', index=False)
    print(f"Exported {output['count']} results to ndvi_results.csv in {output['duration_seconds']} seconds.")


