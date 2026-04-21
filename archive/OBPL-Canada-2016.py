"""
This script is part of the Open Building Population project.

Copyright 2022 Maxim Fortin

Maxim Fortin (2022): Code for processing building population estimates in Canada provided by Maxim Fortin under the Apache 2.0 License.

For more information about Maxim Fortin and the original works included in this distribution, please visit: https://www.maximfortin.com/project/obpl-ca-2016/

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

from geopandas.tools import sjoin
from pyogrio import read_dataframe, write_dataframe
import time
import warnings
from shapely.errors import ShapelyDeprecationWarning
warnings.filterwarnings("ignore", category=ShapelyDeprecationWarning)

# INPUTS

# File path for census file
census_fn = 'DA/DA-Pop-2016.gpkg'

# List of provinces for batch process
# Options include: YK, NWT, NU, BC, AB, SK, MB, ON, QC, NB, NS, PEI, NFL
list_pr = ['YK', 'NWT']

# LOAD CENSUS DATA

census = read_dataframe(census_fn)
census['geometry'] = census['geometry'].to_crs(epsg=3978)  # convert census CRS to EPSG:3978

# PROCESSING

for prov in list_pr:

    tstart = time.perf_counter()

    # LOAD BUILDING FOOTPRINTS, RE-RPOJECT TO EPSG:3978 AND EXTRACT CENTROIDS

    bldg_poly = read_dataframe('Buildings/' + prov + '.geojson')
    bldg_poly['geometry'] = bldg_poly['geometry'].to_crs(epsg=3978)  # convert building footprints CRS to EPSG:3978
    bldg_points = bldg_poly.copy()
    bldg_points['geometry'] = bldg_points['geometry'].centroid  # assign centroid of each footprint to building points layer

    # SPATIAL JOIN FOR BUILDINGS AND CENSUS POLYGONS

    pip = sjoin(bldg_points,census,how='left')  # perform spatial join for building points in census polygons
    list_bldg_census = pip.DAUID.value_counts()  # create list with count of buildings in each census polygon

    # Convert geoseries to dataframe, add column names and change variable type
    list = list_bldg_census.to_frame()  # convert geoseries list to dataframe
    list = list.rename(columns={'DAUID':'BLDG_COUNT'})  # rename DAUID column to BLDG_COUNT
    list['DAUID'] = list.index  # create DAUID column and assign the value that is stored in the index for each feature
    list['DAUID'] = list['DAUID'].astype("int64")  # change field type from object to int64

    # Merge census polygons with building value count, calculate population ratio for each building
    census_temp = census.copy()
    census_temp['DAUID'] = census_temp['DAUID'].astype("int64")  # change field type from object to int64
    census_temp = census_temp.merge(list,on='DAUID')  # merge census polygons with list to specify building count for each polygon
    census_temp['BLDG_RATIO'] = census_temp['Population-2016'] / census_temp['BLDG_COUNT']  # for each census polygon, calculate population ratio per building

    # LEFT JOIN TO ADD POPULATION RATIO TO EACH BUILDING
    j_left = bldg_points.sjoin(census_temp, how='left')  # add calculated population ratio back to building geodataframe

    # WRITE RESULTS TO FILE

    output_fn = "Building-Pop-Layers/BPL_CA_beta_" + prov + ".gpkg"
    file = write_dataframe(j_left,path = output_fn, driver="GPKG")

    tend = time.perf_counter()
    print('Building population layer for ' + prov + f' completed in {tend - tstart:0.4f} seconds')

    # delete temporary dataframes
    del bldg_points
    del bldg_poly
    del j_left
    del list
    del list_bldg_census
    del pip

print('Completed')
