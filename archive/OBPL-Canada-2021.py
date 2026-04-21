"""
This script is part of the Open Building Population project.

Copyright 2024 Maxim Fortin

Maxim Fortin (2024): Code for processing building population estimates provided by Maxim Fortin under the Apache 2.0 License.

For more information about Maxim Fortin and the original works included in this distribution, please visit: https://www.maximfortin.com/project/obpl-ca-2021/

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

import geopandas as gpd
from pyogrio import read_dataframe, write_dataframe
import json
import time
import datetime

tstart = time.perf_counter()

# File path for census file

DA_fn = 'filepath'  # Enter file path for Dissemination Area geospatial dataset, including population
CSD_fn = 'filepath'  # Enter file path for Census Subdivision geospatial dataset, including population
CD_fn = 'filepath'  # Enter file path for Census Division geospatial dataset, including population
PT_fn = 'filepath'  # Enter file path for Province geospatial dataset, including population

# File path for building footprint file

footprints_fn = 'filepath'  # Enter file path for building footprints file

# Load census data, re-project CRS to EPSG:3978

DA_df = read_dataframe(DA_fn)
CSD_df = read_dataframe(CSD_fn)
CD_df = read_dataframe(CD_fn)
PT_df = read_dataframe(PT_fn)
DA_df['geometry'] = DA_df['geometry'].to_crs(epsg=3978)
CSD_df['geometry'] = CSD_df['geometry'].to_crs(epsg=3978)
CD_df['geometry'] = CD_df['geometry'].to_crs(epsg=3978)
PT_df['geometry'] = PT_df['geometry'].to_crs(epsg=3978)

print('Census data loaded...')

# Load building footprints, re-project CRS to EPSG:3978 and extract centroids

footprints_df = read_dataframe(footprints_fn)
footprints_df['geometry'] = footprints_df['geometry'].to_crs(epsg=3978)  # convert building footprints CRS to EPSG:3978
footprints_df['BLDG_ID'] = footprints_df.index + 1  # plus 1 to match FID in geopackage
points_df = footprints_df.copy()
points_df['geometry'] = points_df['geometry'].centroid  # assign centroid of each footprint to building points layer

print('Building footprints loaded...')

# Join building points and census polygons, count buildings, add column names and datatype

pip_DA = gpd.sjoin(points_df, DA_df, how='left')  # perform spatial join for building points in census polygons
list_bldg_DA = pip_DA.DAUID.value_counts()  # create list with count of buildings in each census polygon
list_DA_df = list_bldg_DA.to_frame(name='COUNT_DA')  # convert geoseries list to dataframe
list_DA_df['DAUID'] = list_DA_df.index  # assign index value to new column to make future merging easier
list_DA_df['COUNT_DA'] = list_DA_df['COUNT_DA'].astype('int64')  # change field type from object to int64
list_DA_df['DAUID'] = list_DA_df['DAUID'].astype('int64')  # change field type from object to int64
list_DA_df.reset_index(drop=True, inplace=True)  # reset index to remove ambiguity for later merge

pip_CSD = gpd.sjoin(points_df, CSD_df, how='left')  # perform spatial join for building points in census polygons
list_bldg_CSD = pip_CSD.CSDUID.value_counts()  # create list with count of buildings in each census polygon
list_CSD_df = list_bldg_CSD.to_frame(name='COUNT_CSD')  # convert geoseries list to dataframe
list_CSD_df['CSDUID'] = list_CSD_df.index  # assign index value to new column to make future merging easier
list_CSD_df['COUNT_CSD'] = list_CSD_df['COUNT_CSD'].astype('int64')  # change field type from object to int64
list_CSD_df['CSDUID'] = list_CSD_df['CSDUID'].astype('int64')  # change field type from object to int64
list_CSD_df.reset_index(drop=True, inplace=True)  # reset index to remove ambiguity for later merge

pip_CD = gpd.sjoin(points_df, CD_df, how='left')  # perform spatial join for building points in census polygons
list_bldg_CD = pip_CD.CDUID.value_counts()  # create list with count of buildings in each census polygon
list_CD_df = list_bldg_CD.to_frame(name='COUNT_CD')  # convert geoseries list to dataframe
list_CD_df['CDUID'] = list_CD_df.index  # assign index value to new column to make future merging easier
list_CD_df['COUNT_CD'] = list_CD_df['COUNT_CD'].astype('int64')  # change field type from object to int64
list_CD_df['CDUID'] = list_CD_df['CDUID'].astype('int64')  # change field type from object to int64
list_CD_df.reset_index(drop=True, inplace=True)  # reset index to remove ambiguity for later merge

pip_PT = gpd.sjoin(points_df, PT_df, how='left')  # perform spatial join for building points in census polygons
list_bldg_PT = pip_PT.PRUID.value_counts()  # create list with count of buildings in each census polygon
list_PT_df = list_bldg_PT.to_frame(name='COUNT_PT')  # convert geoseries list to dataframe
list_PT_df['PRUID'] = list_PT_df.index  # assign index value to new column to make future merging easier
list_PT_df['COUNT_PT'] = list_PT_df['COUNT_PT'].astype('int64')  # change field type from object to int64
list_PT_df['PRUID'] = list_PT_df['PRUID'].astype('int64')  # change field type from object to int64
list_PT_df.reset_index(drop=True, inplace=True)  # reset index to remove ambiguity for later merge

print('Points-in-Polygon analysis and building count completed...')

# Merge census polygons with building value count, calculate population ratio for each census unit

DA_df['DAUID'] = DA_df['DAUID'].astype('int64')
DA_df = DA_df.merge(list_DA_df, how='left', on='DAUID', suffixes=('_orig', '_count'))
DA_df['DA_RATIO'] = DA_df['DA_Population_2021_C1_COUNT_TOTAL'] / DA_df['COUNT_DA']

CSD_df['CSDUID'] = CSD_df['CSDUID'].astype('int64')
CSD_df = CSD_df.merge(list_CSD_df, how='left', on='CSDUID', suffixes=('_orig', '_count'))
CSD_df['CSD_RATIO'] = CSD_df['CSD_Population_2021_C1_COUNT_TOTAL'] / CSD_df['COUNT_CSD']

CD_df['CDUID'] = CD_df['CDUID'].astype('int64')
CD_df = CD_df.merge(list_CD_df, how='left', on='CDUID', suffixes=('_orig', '_count'))
CD_df['CD_RATIO'] = CD_df['CD_Population_2021_C1_COUNT_TOTAL'] / CD_df['COUNT_CD']

PT_df['PRUID'] = PT_df['PRUID'].astype('int64')
PT_df = PT_df.merge(list_PT_df, how='left', on='PRUID', suffixes=('_orig', '_count'))
PT_df['PT_RATIO'] = PT_df['PT_Population_2021_C1_COUNT_TOTAL'] / PT_df['COUNT_PT']

print('Ratios calculated for each census unit...')

# Add census ratios to building points and assign population value

points_df = gpd.sjoin(points_df, DA_df, how='left')
points_df = points_df[['BLDG_ID', 'geometry', 'properties', 'DAUID','DA_RATIO']]

points_df = gpd.sjoin(points_df, CSD_df, how='left')
points_df = points_df[['BLDG_ID', 'geometry', 'properties', 'DAUID', 'DA_RATIO', 'CSDUID', 'CSD_RATIO']]

points_df = gpd.sjoin(points_df, CD_df, how='left')
points_df = points_df[['BLDG_ID', 'geometry', 'properties', 'DAUID', 'DA_RATIO', 'CSDUID', 'CSD_RATIO', 'CDUID', 'CD_RATIO']]

points_df = gpd.sjoin(points_df, PT_df, how='left')
points_df = points_df[['BLDG_ID', 'geometry', 'properties', 'DAUID', 'DA_RATIO', 'CSDUID', 'CSD_RATIO', 'CDUID', 'CD_RATIO', 'PRUID', 'PT_RATIO']]

points_df['BLDG_POP'] = points_df['DA_RATIO'].fillna(points_df['CSD_RATIO'].fillna(points_df['CD_RATIO'])).astype('float').round(3)
points_df['POP_SOURCE'] = points_df.apply(lambda x: 'DA_RATIO' if not gpd.pd.isnull(x['DA_RATIO']) else ('CSD_RATIO' if not gpd.pd.isnull(x['CSD_RATIO']) else 'CD_RATIO'), axis=1)

# Adjust number of decimals for columns DA_RATIO, CSD_RATIO, and CD_RATIO in points_df

points_df['DA_RATIO'] = points_df['DA_RATIO'].fillna(points_df['CSD_RATIO'].fillna(points_df['CD_RATIO'])).astype('float').round(3)
points_df['CSD_RATIO'] = points_df['CSD_RATIO'].astype('float').round(3)
points_df['CD_RATIO'] = points_df['CD_RATIO'].astype('float').round(3)
points_df['PT_RATIO'] = points_df['PT_RATIO'].astype('float').round(3)

print('Building population calculated and added to buildings...')

# Format building height field in building data
def extract_height(json_str):
    try:
        json_data = json.loads(json_str)
        height = json_data.get('height', None)
        if height is not None:
            return round(height, 2)
    except:
        pass
    return None

points_df['HEIGHT'] = points_df['properties'].apply(extract_height)
points_df.drop(columns=['properties'], inplace=True)
points_df = points_df[['BLDG_ID', 'geometry', 'HEIGHT', 'DAUID', 'DA_RATIO', 'CSDUID','CSD_RATIO','CDUID', 'CD_RATIO', 'PRUID', 'PT_RATIO', 'BLDG_POP', 'POP_SOURCE']]

print('Point layer finalized...')

# Create footprint layer with population data

footprints_df = footprints_df.merge(points_df, how='left', on='BLDG_ID')
footprints_df.drop(columns=['type', 'properties', 'geometry_y'], inplace=True)
footprints_df = footprints_df.rename(columns={'geometry_x':'geometry'})
footprints_df = footprints_df[['BLDG_ID', 'geometry', 'HEIGHT', 'DAUID', 'DA_RATIO', 'CSDUID','CSD_RATIO','CDUID', 'CD_RATIO', 'PRUID', 'PT_RATIO', 'BLDG_POP', 'POP_SOURCE']]
footprints_df = gpd.GeoDataFrame(footprints_df, geometry='geometry')

print('Footprint layer finalized...')

# Save to file

current_time = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")  # create timestamp to include in saved files

write_dataframe(points_df, f'Points_{current_time}.gpkg', driver='GPKG')
write_dataframe(footprints_df, f'Footprints_{current_time}.gpkg', driver='GPKG')

tend = time.perf_counter()
elapsed_time = tend - tstart
hours, remainder = divmod(elapsed_time, 3600)
minutes, seconds = divmod(remainder, 60)

print(f"Script execution time: {int(hours)} hours, {int(minutes)} minutes, {int(seconds)} seconds...")
