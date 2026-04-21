"""
This script is part of the Open Building Population project.

Copyright 2022 Maxim Fortin

Maxim Fortin (2022): Code for processing building population estimates in the US provided by Maxim Fortin under the Apache 2.0 License.

For more information about Maxim Fortin and the original works included in this distribution, please visit: https://www.maximfortin.com/project/obpl-us-2018/

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
import pandas as pd
warnings.filterwarnings("ignore", category=ShapelyDeprecationWarning)

# INPUTS

# File path for census file
census_fn = 'Census/SVI2018_US_tract.shp' # polygon file for census tracts and population
state_fn = 'Census/states.gpkg' # polygon file for state boundaries

# List of states for batch process
list_pr = []

# FULL LIST =
# ['Alabama','Alaska','Arizona','Arkansas','California','Colorado','Connecticut','Delaware','DistrictofColumbia',
# 'Florida','Georgia','Hawaii','Idaho','Illinois','Indiana','Iowa','Kansas','Kentucky','Louisiana','Maine',
# 'Maryland', 'Massachusetts','Michigan','Minnesota','Missouri','Montana','Nebraska','Nevada','NewHampshire',
# 'NewJersey','NewMexico','NewYork','NorthCarolina','NorthDakota','Ohio','Oklahoma','Oregon','Pennsylvania',
# 'RhodeIsland','SouthCarolina','SouthDakota','Tennessee','Texas','Utah','Vermont','Virgina','Washington',
# 'WestVirginia','Wisconsin','Wyoming']

# Dictionary used for relationship between state boundaries (state code) and file name for building footprints
dict = {'Alabama':'01','Alaska':'02','Arizona':'04','Arkansas':'05','California':'06','Colorado':'08','Connecticut':'09',
        'Delaware':'10','DistrictofColumbia':'11','Florida':'12','Georgia':'13','Hawaii':'15','Idaho':'16','Illinois':'17',
        'Indiana':'18','Iowa':'19','Kansas':'20','Kentucky':'21','Louisiana':'22','Maine':'23','Maryland':'24',
        'Massachusetts':'25','Michigan':'26','Minnesota':'27','Mississippi':'28','Missouri':'29','Montana':'30','Nebraska':'31','Nevada':'32',
        'NewHampshire':'33','NewJersey':'34','NewMexico':'35','NewYork':'36','NorthCarolina':'37','NorthDakota':'38',
        'Ohio':'39','Oklahoma':'40','Oregon':'41','Pennsylvania':'42','RhodeIsland':'44','SouthCarolina':'45',
        'SouthDakota':'46','Tennessee':'47','Texas':'48','Utah':'49','Vermont':'50','Virginia':'51','Washington':'53',
        'WestVirginia':'54','Wisconsin':'55','Wyoming':'56'}

# LOAD CENSUS DATA
census = read_dataframe(census_fn)
census['geometry'] = census['geometry'].to_crs(epsg=5070)  # convert census CRS to EPSG:5070
state = read_dataframe(state_fn)
state['geometry'] = state['geometry'].to_crs(epsg=5070)  # convert states CRS to EPSG:5070

# PROCESSING
for prov in list_pr:

    tstart = time.perf_counter()

    # LOAD BUILDING FOOTPRINTS AND EXTRACT CENTROIDS
    state_code = dict[prov]
    state_clip = state[state['code'] == state_code]
    bldg_poly = read_dataframe('Footprints/' + prov + '.geojson')
    bldg_poly['geometry'] = bldg_poly['geometry'].to_crs(epsg=5070)  # convert building footprints CRS to EPSG:5070
    bldg_points = bldg_poly.copy()
    bldg_points['geometry'] = bldg_points['geometry'].centroid  # assign centroid of each footprint to building points layer
    bldg_points = bldg_points.clip(state_clip)

    # SPATIAL JOIN FOR BUILDINGS AND CENSUS POLYGONS
    pip = sjoin(bldg_points, census, how='left')  # perform spatial join for building points in census polygons
    list_bldg_census = pip.FIPS.value_counts()  # create list with count of buildings in each census polygon

    # Convert geoseries to dataframe, add column names and change variable type
    list = list_bldg_census.to_frame()  # convert geoseries list to dataframe
    list = list.rename(columns={'FIPS':'BLDG_COUNT'})  # rename DAUID column to BLDG_COUNT
    list['FIPS'] = list.index  # create DAUID column and assign the value that is stored in the index for each feature
    list['FIPS'] = list['FIPS'].astype("int64")  # change field type from object to int64

    # Merge census polygons with building value count, calculate population ratio for each building
    census_temp = census.copy()
    census_temp['FIPS'] = census_temp['FIPS'].astype("int64")  # change field type from object to int64
    census_temp = census_temp.merge(list,on='FIPS')  # merge census polygons with list to specify building count for each polygon
    census_temp['BLDG_POP'] = census_temp['E_TOTPOP'] / census_temp['BLDG_COUNT']  # for each census polygon, calculate population ratio per building

    # LEFT JOIN TO ADD POPULATION RATIO TO EACH BUILDING
    j_left = bldg_points.sjoin(census_temp, how='left')  # add calculated population ratio back to building geodataframe

    # WRITE RESULTS TO FILE
    j_left = j_left.drop(['release', 'capture_dates_range', 'index_right', 'ST', 'STATE', 'ST_ABBR', 'STCNTY', 'COUNTY', 'LOCATION', 'AREA_SQMI', 'E_TOTPOP', 'M_TOTPOP', 'E_HU', 'M_HU', 'E_HH', 'M_HH', 'E_POV', 'M_POV', 'E_UNEMP', 'M_UNEMP', 'E_PCI', 'M_PCI', 'E_NOHSDP', 'M_NOHSDP', 'E_AGE65', 'M_AGE65', 'E_AGE17', 'M_AGE17', 'E_DISABL', 'M_DISABL', 'E_SNGPNT', 'M_SNGPNT', 'E_MINRTY', 'M_MINRTY', 'E_LIMENG', 'M_LIMENG', 'E_MUNIT', 'M_MUNIT', 'E_MOBILE', 'M_MOBILE', 'E_CROWD', 'M_CROWD', 'E_NOVEH', 'M_NOVEH', 'E_GROUPQ', 'M_GROUPQ', 'EP_POV', 'MP_POV', 'EP_UNEMP', 'MP_UNEMP', 'EP_PCI', 'MP_PCI', 'EP_NOHSDP', 'MP_NOHSDP', 'EP_AGE65', 'MP_AGE65', 'EP_AGE17', 'MP_AGE17', 'EP_DISABL', 'MP_DISABL', 'EP_SNGPNT', 'MP_SNGPNT', 'EP_MINRTY', 'MP_MINRTY', 'EP_LIMENG', 'MP_LIMENG', 'EP_MUNIT', 'MP_MUNIT', 'EP_MOBILE', 'MP_MOBILE', 'EP_CROWD', 'MP_CROWD', 'EP_NOVEH', 'MP_NOVEH', 'EP_GROUPQ', 'MP_GROUPQ', 'EPL_POV', 'EPL_UNEMP', 'EPL_PCI', 'EPL_NOHSDP', 'SPL_THEME1', 'RPL_THEME1', 'EPL_AGE65', 'EPL_AGE17', 'EPL_DISABL', 'EPL_SNGPNT', 'SPL_THEME2', 'RPL_THEME2', 'EPL_MINRTY', 'EPL_LIMENG', 'SPL_THEME3', 'RPL_THEME3', 'EPL_MUNIT', 'EPL_MOBILE', 'EPL_CROWD', 'EPL_NOVEH', 'EPL_GROUPQ', 'SPL_THEME4', 'RPL_THEME4', 'SPL_THEMES', 'RPL_THEMES', 'F_POV', 'F_UNEMP', 'F_PCI', 'F_NOHSDP', 'F_THEME1', 'F_AGE65', 'F_AGE17', 'F_DISABL', 'F_SNGPNT', 'F_THEME2', 'F_MINRTY', 'F_LIMENG', 'F_THEME3', 'F_MUNIT', 'F_MOBILE', 'F_CROWD', 'F_NOVEH', 'F_GROUPQ', 'F_THEME4', 'F_TOTAL', 'E_UNINSUR', 'M_UNINSUR', 'EP_UNINSUR', 'MP_UNINSUR', 'E_DAYPOP', 'Shape_STAr', 'Shape_STLe', 'BLDG_COUNT'], axis=1)
    j_left['BLDG_POP'] = j_left['BLDG_POP'].fillna(0)
    output_fn = "Outputs/BPL_US_beta_" + prov + ".gpkg"
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
