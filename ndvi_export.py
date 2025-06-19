import ee
import json
import pandas as pd
import time
import geopandas as gpd
from shapely.geometry import shape

print("Starting NDVI export script...")
start_time = time.time()

# Constants for cloud masking
CLD_THRESH = 50  # max CLOUDY_PIXEL_PERCENTAGE allowed
CLD_PRB_THRESH = 60  # probability threshold for cloud detection
NIR_DRK_THRESH = 0.15  # dark pixels threshold (B8 < 0.15)
CLD_PRJ_DIST = 1  # km distance for shadow projection
BUFFER = 50  # distance in meters to dilate cloud/shadow mask
NUM_RESULTS = 10 # number of largest polygons to return

# Authenticate and initialize Earth Engine
KEY = 'my-secret-key.json'  # Replace with path to your GEE service account JSON
with open(KEY, 'r') as f:
    creds = json.load(f)

ee.Initialize(ee.ServiceAccountCredentials(creds['client_email'], KEY))

# Define AOI and time window
geom = ee.Geometry.BBox(36.2597202470, 4.19477694745, 36.3308408646, 4.26022461625)
time_start, time_end = '2025-06-01', '2025-06-14'
NDVI_THRESH = 0.3
AREA_MIN = 10000  # m²

# Cloud masking helpers
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

# Apply cloud/shadow masking
s2_sr_cld_col = get_s2_sr_cld_col(geom, time_start, time_end)
masked_col = s2_sr_cld_col.map(add_cld_shdw_mask).map(apply_cld_shdw_mask)

# Create cloud-free mosaic by most recent
image = masked_col.median().clip(geom)

# Calculate NDVI
ndvi = image.normalizedDifference(['B8', 'B4']).rename('NDVI')

# Threshold NDVI and extract vectors
ndvi_mask = ndvi.gt(NDVI_THRESH).toInt()

vectors = (ndvi_mask.reduceToVectors(
    geometry=geom,
    scale=50,
    geometryType='polygon',
    labelProperty='ndvi_zone',
    maxPixels=1e13
).map(lambda f: f.set('area', f.geometry().area(1))))

vectors = vectors.filter(ee.Filter.lt('area', 1e7))

vectors = vectors.sort('area', False).limit(NUM_RESULTS)  # Sort by area, largest first

# Calculate mean NDVI in each polygon
def add_mean_ndvi(feature):
    mean = ndvi.reduceRegion(
        reducer=ee.Reducer.mean(),
        geometry=feature.geometry(),
        scale=50,
        maxPixels=1e13
    ).get('NDVI')
    return feature.set('mean_ndvi', mean)

features_with_ndvi = vectors.map(add_mean_ndvi)

# Export GeoJSON FeatureCollection to Python
geojson = features_with_ndvi.getInfo()

# Convert to DataFrame
rows = []
for f in geojson['features']:
    props = f['properties']
    
    # Clean and round mean NDVI
    ndvi_val = props.get('mean_ndvi')
    props['mean_ndvi'] = round(float(ndvi_val), 2) if ndvi_val is not None else None

    # Round area (convert m² to ha or km² as needed)
    area_val = props.get('area')
    props['area'] = round(area_val / 10000, 2) if area_val is not None else None

    # Remove unnecessary keys
    props.pop('count', None)
    props.pop('ndvi_zone', None)

    geom = shape(f['geometry'])  # Convert to shapely geometry
    simplified_geom = geom.simplify(tolerance=0.0001, preserve_topology=True)
    props['geometry'] = json.dumps(gpd.GeoSeries([simplified_geom]).__geo_interface__['features'][0]['geometry'])
    rows.append(props)

# Create DataFrame and export
df = pd.DataFrame(rows)
df.to_csv('ndvi_polygons.csv', index=False)
print("Exported to ndvi_polygons.csv")
# Print execution time
end_time = time.time()
print(f"Script completed in {end_time - start_time:.2f} seconds.")
