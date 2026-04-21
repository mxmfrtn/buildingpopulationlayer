## Data Sources and Attribution

This dataset incorporates data from multiple open sources, each licensed under their respective terms.

### Primary Sources

**Open Building Population Layer — Canada v3**
- Produced by: Maxim Fortin
- URL: https://maximfortin.com/project/obpl-ca-v3/
- License: Open Database License (ODbL) v1.0

### Building Footprints

**Canada Structures**
- Produced by: Public Safety Canada, Data Science and Engineering Team
- URL: https://open.canada.ca/data/en/dataset/3829eee9-f898-4643-9ad8-f48575b8873d
- Citation: Sandison J., Hayes S., Darlington C., Chastko K., & Ballard M. (2025). Canada Structures [Data set]. Emergency Management, Policy and Outreach, Resilience and Economic Integration, Data Science and Engineering Team, Ottawa, Ontario, Canada. https://doi.org/10.82126/z1bc-zd72
- License: Open Government License – Canada

Canada Structures derives from three open data sources:

1. **Open Database of Buildings (ODB)**
   - Produced by: Statistics Canada
   - License: Open Government License – Canada
   - Description: Collection of 65 structure datasets originating from various government sources across Canada; full attribution list is available at https://maximfortin.com/project/obpl-ca-v3/ODB_v3_data_providers.csv

2. **OpenStreetMap (OSM) Buildings**
   - Produced by: OpenStreetMap contributors
   - License: Open Database License (ODbL)
   - URL: https://www.openstreetmap.org/
   - Description: Open access building polygons from a decentralized community of contributors

3. **Microsoft Building Footprints (MSB)**
   - Produced by: Microsoft
   - License: Open Database License (ODbL)
   - URL: https://github.com/microsoft/CanadianBuildingFootprints
   - Description: Building footprints automatically extracted from satellite imagery

### Census Data

**Statistics Canada 2021 Census**
- Produced by: Statistics Canada
- License: Open Government License – Canada
- URL: https://www12.statcan.gc.ca/census-recensement/2021/dp-pd/prof/index.cfm?Lang=E

### Modifications

The original data has been:
- Reprojected to EPSG:3979
- Combined and processed to estimate population at the building level
- Enhanced with quality flags and derived attributes

Users must preserve all upstream attributions when sharing or adapting this data.
