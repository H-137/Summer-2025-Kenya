import ee
import json
import geopandas as gpd
from shapely.geometry import shape
import pandas as pd
import time
import os

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

    # Helper functions (same as before, omitted here for brevity)
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

    # Processing
    s2_sr_cld_col = get_s2_sr_cld_col(geom, start_date, end_date)
    masked_col = s2_sr_cld_col.map(add_cld_shdw_mask).map(apply_cld_shdw_mask)
    image = masked_col.median().clip(geom)
    ndvi = image.normalizedDifference(['B8', 'B4']).rename('NDVI')
    ndvi_mask = ndvi.gt(NDVI_THRESH).toInt()

    vectors = (ndvi_mask.reduceToVectors(
        geometry=geom,
        scale=50,
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
            scale=50,
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

        # Simplify geometry
        geom_shape = shape(f['geometry'])
        simplified_geom = geom_shape.simplify(tolerance=0.0001, preserve_topology=True)

        results.append({
            'mean_ndvi': round(float(mean_ndvi), 2) if mean_ndvi is not None else None,
            'area_ha': round(area / 10000, 2) if area is not None else None,
            'geometry': json.loads(gpd.GeoSeries([simplified_geom]).to_json())['features'][0]['geometry']
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
    print(json.dumps(output, indent=2))
    pd.DataFrame(output['results']).to_csv('ndvi_results.csv', index=False)