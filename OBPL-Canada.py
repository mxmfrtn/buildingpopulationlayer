"""
This script is part of the Open Building Population project.

Copyright 2026 Maxim Fortin

Maxim Fortin (2026): Code for processing building population estimates provided by Maxim Fortin under the Apache 2.0 License.

For more information about Maxim Fortin and the original works included in this distribution, please visit: https://www.maximfortin.com/project/obpl-ca-v3/

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

import os
import sqlite3
import zipfile
import shutil
import tempfile
import json
import numpy as np
import pandas as pd
import geopandas as gpd
from pyogrio import read_dataframe, write_dataframe, read_info
import pyarrow.parquet as pq
from shapely.geometry import MultiPolygon
from tqdm import tqdm
import time
import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent

tstart = time.perf_counter()

PROVINCE = None

PROVINCES = {
    'NL': ('10', 'nl_structures_en.gpkg'),
    'PE': ('11', 'pe_structures_en.gpkg'),
    'NS': ('12', 'ns_structures_en.gpkg'),
    'NB': ('13', 'nb_structures_en.gpkg'),
    'QC': ('24', 'qc_structures_en.gpkg'),
    'ON': ('35', 'on_structures_en.gpkg'),
    'MB': ('46', 'mb_structures_en.gpkg'),
    'SK': ('47', 'sk_structures_en.gpkg'),
    'AB': ('48', 'ab_structures_en.gpkg'),
    'BC': ('59', 'bc_structures_en.gpkg'),
    'YT': ('60', 'yk_structures_en.gpkg'),
    'NT': ('61', 'nt_structures_en.gpkg'),
    'NU': ('62', 'nu_structures_en.gpkg'),
}

NATIONAL_POINTS_LAYER = 'OBPL_CA_v3_Points_Canada'
NATIONAL_FOOTPRINTS_LAYER = 'OBPL_CA_v3_Footprints_Canada'

DB_fn = str(PROJECT_ROOT / 'data/census/db_population_2021.gpkg')
DA_fn = str(PROJECT_ROOT / 'data/census/DA_Population_2021.gpkg')
CSD_fn = str(PROJECT_ROOT / 'data/census/CSD_Population_2021.gpkg')
CD_fn = str(PROJECT_ROOT / 'data/census/CD_Population_2021.gpkg')
FP_DIR = str(PROJECT_ROOT / 'data/footprints')
OUT_DIR = str(PROJECT_ROOT / 'output')
FINAL_DIR = str(PROJECT_ROOT / 'output/final')
GEOPARQUET_DIR = str(PROJECT_ROOT / 'output/geoparquet')
LICENSE_DIR = str(PROJECT_ROOT / 'licenses')
VERSION_TAG = 'OBPL_CA_v3'

LICENSE_FILES = [
    os.path.join(LICENSE_DIR, 'LICENSE-DATA.MD'),
    os.path.join(LICENSE_DIR, 'ATTRIBUTION.MD'),
]

PARQUET_METADATA = {
    "license": "ODbL v1.0",
    "license_url": "https://opendatacommons.org/licenses/odbl/1.0/",
    "attribution": "Fortin, Maxim (2026). Open Building Population Layer — Canada v3.",
    "source_url": "https://maximfortin.com/project/obpl-ca-v3/",
    "derived_from": [
        "Canada Structures (Public Safety Canada)",
        "Statistics Canada Census 2021"
    ],
    "upstream_sources": [
        {
            "name": "Open Database of Buildings (ODB)",
            "producer": "Statistics Canada",
            "license": "Open Government License – Canada"
        },
        {
            "name": "OpenStreetMap (OSM) Buildings",
            "producer": "OpenStreetMap contributors",
            "license": "ODbL"
        },
        {
            "name": "Microsoft Building Footprints (MSB)",
            "producer": "Microsoft",
            "license": "ODbL"
        }
    ]
}

GPKG_METADATA_STANDARD_URI = 'https://www.geopackage.org/spec/'
GPKG_METADATA_MIME_TYPE = 'text/plain'
GPKG_CONTENTS_DESCRIPTION = 'OBPL-CA v3 | License: ODbL v1.0 | Fortin, Maxim (2026)'

GEOPARQUET_BATCH_SIZE = 500_000
GEOPARQUET_COMPRESSION = 'zstd'

validation_log = []


def log(msg):
    print(msg)
    validation_log.append(msg)


def validate_geom(gdf, name):
    invalid = ~gdf.geometry.is_valid
    n_invalid = invalid.sum()
    if n_invalid > 0:
        log(f'  {name}: {n_invalid} invalid geometries — fixed with make_valid()')
        gdf.loc[invalid, 'geometry'] = gdf.loc[invalid, 'geometry'].make_valid()
        still_invalid = (~gdf.geometry.is_valid).sum()
        if still_invalid > 0:
            log(f'  {name}: WARNING {still_invalid} still invalid after make_valid()')
    empty = gdf.geometry.is_empty.sum()
    null = gdf.geometry.isna().sum()
    if empty > 0 or null > 0:
        log(f'  {name}: {null} null, {empty} empty geometries')
    return gdf


def to_multipolygon(geom):
    if geom is None:
        return geom
    if geom.geom_type == 'Polygon':
        return MultiPolygon([geom])
    return geom


def sjoin_count(points, census_gdf, uid_col, pop_col, level_name):
    pip = gpd.sjoin(points, census_gdf[[uid_col, 'geometry']], how='left', predicate='intersects')
    n_dup = len(pip) - len(points)
    pip = pip.drop_duplicates(subset='BLDG_ID', keep='first')
    if n_dup > 0:
        log(f'    {level_name} sjoin: {n_dup} duplicate building matches dropped')
    n_null = pip[uid_col].isna().sum()
    log(f'    {level_name} sjoin: {n_null} buildings did not match any {level_name} polygon')
    count_df = pip[pip[uid_col].notna()].groupby(uid_col).size().reset_index(name=f'COUNT_{level_name}')
    census_gdf = census_gdf.merge(count_df, on=uid_col, how='left')
    census_gdf[f'COUNT_{level_name}'] = census_gdf[f'COUNT_{level_name}'].fillna(0).astype('int64')
    census_gdf[f'{level_name}_RATIO'] = census_gdf[pop_col] / census_gdf[f'COUNT_{level_name}']
    n_inf = np.isinf(census_gdf[f'{level_name}_RATIO']).sum()
    census_gdf[f'{level_name}_RATIO'] = census_gdf[f'{level_name}_RATIO'].replace([np.inf, -np.inf], np.nan)
    n_nan = census_gdf[f'{level_name}_RATIO'].isna().sum()
    log(f'    {level_name}_RATIO: {n_inf} inf→NaN, {n_nan} total NaN')
    return pip, census_gdf


def zip_with_licenses(gpkg_path, zip_path):
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        zf.write(gpkg_path, os.path.basename(gpkg_path))
        for lf in LICENSE_FILES:
            if os.path.exists(lf):
                zf.write(lf, os.path.basename(lf))
            else:
                log(f'  WARNING: License file not found: {lf}')
    log(f'  Created {zip_path} ({os.path.getsize(zip_path) / (1024*1024):.1f} MB)')


def build_gpkg_metadata_text():
    """Render the canonical metadata payload as plain text for GeoPackage."""
    lines = [
        "Open Building Population Layer — Canada v3",
        "",
        f"License: {PARQUET_METADATA['license']}",
        f"License URL: {PARQUET_METADATA['license_url']}",
        "",
        f"Attribution: {PARQUET_METADATA['attribution']}",
        f"Project URL: {PARQUET_METADATA['source_url']}",
        "",
        "Derived from:",
    ]
    lines.extend(f"- {source}" for source in PARQUET_METADATA['derived_from'])
    lines.append("")
    lines.append("Upstream sources:")
    for source in PARQUET_METADATA['upstream_sources']:
        lines.append(
            f"- {source['name']} | Producer: {source['producer']} | License: {source['license']}"
        )
    return "\n".join(lines)


def add_gpkg_metadata(gpkg_path):
    """Embed standards-compatible GeoPackage metadata for GDAL/QGIS interoperability."""
    timestamp = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')
    conn = sqlite3.connect(gpkg_path)
    cursor = conn.cursor()
    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS gpkg_metadata (
                id INTEGER CONSTRAINT m_pk PRIMARY KEY ASC NOT NULL,
                md_scope TEXT NOT NULL DEFAULT 'dataset',
                md_standard_uri TEXT NOT NULL,
                mime_type TEXT NOT NULL DEFAULT 'text/xml',
                metadata TEXT NOT NULL DEFAULT ''
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS gpkg_metadata_reference (
                reference_scope TEXT NOT NULL,
                table_name TEXT,
                column_name TEXT,
                row_id_value INTEGER,
                timestamp DATETIME NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                md_file_id INTEGER NOT NULL,
                md_parent_id INTEGER,
                CONSTRAINT crmr_mfi_fk FOREIGN KEY (md_file_id) REFERENCES gpkg_metadata(id),
                CONSTRAINT crmr_mpi_fk FOREIGN KEY (md_parent_id) REFERENCES gpkg_metadata(id)
            )
        """)

        # Keep reruns idempotent.
        cursor.execute("DELETE FROM gpkg_metadata_reference")
        cursor.execute("DELETE FROM gpkg_metadata")
        cursor.execute("""
            INSERT INTO gpkg_metadata (id, md_scope, md_standard_uri, mime_type, metadata)
            VALUES (1, 'dataset', ?, ?, ?)
        """, (GPKG_METADATA_STANDARD_URI, GPKG_METADATA_MIME_TYPE, build_gpkg_metadata_text()))

        cursor.execute("""
            INSERT INTO gpkg_metadata_reference
            (reference_scope, table_name, column_name, row_id_value, timestamp, md_file_id, md_parent_id)
            VALUES ('geopackage', NULL, NULL, NULL, ?, 1, NULL)
        """, (timestamp,))

        cursor.execute("SELECT table_name FROM gpkg_contents WHERE data_type = 'features' ORDER BY table_name")
        feature_tables = [row[0] for row in cursor.fetchall()]
        for table_name in feature_tables:
            cursor.execute("""
                INSERT INTO gpkg_metadata_reference
                (reference_scope, table_name, column_name, row_id_value, timestamp, md_file_id, md_parent_id)
                VALUES ('table', ?, NULL, NULL, ?, 1, NULL)
            """, (table_name, timestamp))

        cursor.execute("UPDATE gpkg_contents SET description = ?", (GPKG_CONTENTS_DESCRIPTION,))
        conn.commit()
    finally:
        conn.close()


def validate_gpkg_metadata(gpkg_path):
    conn = sqlite3.connect(gpkg_path)
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cursor.fetchall()}
        assert 'gpkg_metadata' in tables, 'gpkg_metadata table missing'
        assert 'gpkg_metadata_reference' in tables, 'gpkg_metadata_reference table missing'

        cursor.execute("SELECT COUNT(*) FROM gpkg_metadata")
        metadata_rows = cursor.fetchone()[0]
        assert metadata_rows >= 1, 'gpkg_metadata has no rows'

        cursor.execute("SELECT COUNT(*) FROM gpkg_metadata_reference")
        ref_rows = cursor.fetchone()[0]
        assert ref_rows >= 1, 'gpkg_metadata_reference has no rows'

        cursor.execute("PRAGMA table_info(gpkg_metadata)")
        metadata_cols = {row[1] for row in cursor.fetchall()}
        required_metadata_cols = {'id', 'md_scope', 'md_standard_uri', 'mime_type', 'metadata'}
        missing_metadata_cols = required_metadata_cols - metadata_cols
        assert not missing_metadata_cols, f'gpkg_metadata missing columns: {sorted(missing_metadata_cols)}'

        cursor.execute("PRAGMA table_info(gpkg_metadata_reference)")
        ref_cols = {row[1] for row in cursor.fetchall()}
        required_ref_cols = {
            'reference_scope', 'table_name', 'column_name',
            'row_id_value', 'timestamp', 'md_file_id', 'md_parent_id'
        }
        missing_ref_cols = required_ref_cols - ref_cols
        assert not missing_ref_cols, f'gpkg_metadata_reference missing columns: {sorted(missing_ref_cols)}'
    finally:
        conn.close()


def add_parquet_metadata(parquet_path):
    """Embed ODbL/provenance metadata in GeoParquet schema metadata."""
    table = pq.read_table(parquet_path)
    metadata = dict(table.schema.metadata or {})
    metadata[b'odbl_license'] = json.dumps(PARQUET_METADATA).encode('utf-8')
    updated = table.replace_schema_metadata(metadata)
    pq.write_table(updated, parquet_path, compression=GEOPARQUET_COMPRESSION)


def validate_parquet_metadata(parquet_path):
    metadata = pq.ParquetFile(parquet_path).schema_arrow.metadata or {}
    assert b'geo' in metadata, 'GeoParquet geo metadata missing'
    assert b'odbl_license' in metadata, 'Parquet ODbL metadata missing'
    parsed = json.loads(metadata[b'odbl_license'].decode('utf-8'))
    for key in ['license', 'license_url', 'attribution', 'source_url', 'derived_from', 'upstream_sources']:
        assert key in parsed, f'Parquet metadata missing key: {key}'


def convert_to_geoparquet(gpkg_path, parquet_path):
    info = read_info(str(gpkg_path))
    total_rows = info['features']
    log(f'  Converting {os.path.basename(gpkg_path)} to GeoParquet ({total_rows:,} features)...')
    temp_dir = tempfile.mkdtemp(prefix='geoparquet_')
    batch_files = []
    try:
        for batch_start in range(0, total_rows, GEOPARQUET_BATCH_SIZE):
            gdf = gpd.read_file(
                str(gpkg_path),
                rows=GEOPARQUET_BATCH_SIZE,
                skip_features=batch_start,
                engine='pyogrio'
            )
            if len(gdf) == 0:
                break
            batch_file = os.path.join(temp_dir, f'batch_{batch_start:08d}.parquet')
            gdf.to_parquet(batch_file, compression=GEOPARQUET_COMPRESSION, index=False)
            batch_files.append(batch_file)
            log(f'    Batch {batch_start:,}-{batch_start+len(gdf):,} written')
        if batch_files:
            log(f'  Merging {len(batch_files)} batches...')
            dfs = [gpd.read_parquet(bf) for bf in batch_files]
            combined = gpd.GeoDataFrame(pd.concat(dfs, ignore_index=True))
            combined.to_parquet(parquet_path, compression=GEOPARQUET_COMPRESSION, index=False)
            log(f'  Saved {parquet_path} ({os.path.getsize(parquet_path) / (1024*1024):.1f} MB)')
        else:
            log(f'  WARNING: No features found in {gpkg_path}')
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


prov_list = [PROVINCE] if PROVINCE else list(PROVINCES.keys())

# --- Load and validate census data ---

log('Loading census data...')
DB_df = read_dataframe(DB_fn)
DA_df = read_dataframe(DA_fn)
CSD_df = read_dataframe(CSD_fn)
CD_df = read_dataframe(CD_fn)
log(f'  DB: {len(DB_df)} polygons, CRS={DB_df.crs}')
log(f'  DA: {len(DA_df)} polygons, CRS={DA_df.crs}')
log(f'  CSD: {len(CSD_df)} polygons, CRS={CSD_df.crs}')
log(f'  CD: {len(CD_df)} polygons, CRS={CD_df.crs}')

log('Validating census geometries...')
DB_df = validate_geom(DB_df, 'DB')
DA_df = validate_geom(DA_df, 'DA')
CSD_df = validate_geom(CSD_df, 'CSD')
CD_df = validate_geom(CD_df, 'CD')

log('Reprojecting census data to EPSG:3979...')
DB_df = DB_df.to_crs(epsg=3979)
DA_df = DA_df.to_crs(epsg=3979)
CSD_df = CSD_df.to_crs(epsg=3979)
CD_df = CD_df.to_crs(epsg=3979)

log('Validating post-reprojection...')
DB_df = validate_geom(DB_df, 'DB_reproj')
DA_df = validate_geom(DA_df, 'DA_reproj')
CSD_df = validate_geom(CSD_df, 'CSD_reproj')
CD_df = validate_geom(CD_df, 'CD_reproj')

for name, df in [('DB', DB_df), ('DA', DA_df), ('CSD', CSD_df), ('CD', CD_df)]:
    assert df.crs.to_epsg() == 3979, f'{name} CRS is {df.crs}, expected EPSG:3979'

DB_df = DB_df[['DBUID', 'DBPOP2021', 'PRUID', 'geometry']]
DA_df = DA_df[['DAUID', 'DA_Population_2021_C1_COUNT_TOTAL', 'PRUID', 'geometry']]
CSD_df = CSD_df[['CSDUID', 'CSD_Population_2021_C1_COUNT_TOTAL', 'PRUID', 'geometry']]
CD_df = CD_df[['CDUID', 'CD_Population_2021_C1_COUNT_TOTAL', 'PRUID', 'geometry']]

log('Census data ready.')

# --- Process each province ---

os.makedirs(OUT_DIR, exist_ok=True)
os.makedirs(FINAL_DIR, exist_ok=True)
os.makedirs(GEOPARQUET_DIR, exist_ok=True)
current_time = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

for prov in tqdm(prov_list, desc="Processing Provinces"):
    assert prov.isalpha() and len(prov) == 2, f"prov must be 2-letter abbreviation, got: '{prov}'"
    pruid, fp_file = PROVINCES[prov]
    fp_path = os.path.join(FP_DIR, fp_file)
    log(f'\n{"="*60}')
    log(f'Processing {prov} (PRUID={pruid})')
    log(f'{"="*60}')

    # Filter census layers to province
    DB_prov = DB_df[DB_df['PRUID'] == pruid][['DBUID', 'DBPOP2021', 'geometry']].copy()
    DA_prov = DA_df[DA_df['PRUID'] == pruid][['DAUID', 'DA_Population_2021_C1_COUNT_TOTAL', 'geometry']].copy()
    CSD_prov = CSD_df[CSD_df['PRUID'] == pruid][['CSDUID', 'CSD_Population_2021_C1_COUNT_TOTAL', 'geometry']].copy()
    CD_prov = CD_df[CD_df['PRUID'] == pruid][['CDUID', 'CD_Population_2021_C1_COUNT_TOTAL', 'geometry']].copy()
    log(f'  Census: {len(DB_prov)} DBs, {len(DA_prov)} DAs, {len(CSD_prov)} CSDs, {len(CD_prov)} CDs')

    # Load footprints
    footprints_df = read_dataframe(fp_path)
    log(f'  Footprints: {len(footprints_df)} buildings loaded')
    footprints_df = validate_geom(footprints_df, f'{prov}_footprints')

    if footprints_df.crs is None:
        raise RuntimeError(f'{prov} footprints have no CRS. Cannot reproject safely.')

    # Reproject footprints to EPSG:3979 (source CRS is EPSG:102002 per Canada Structures Product Specs v1.0.0)
    footprints_df = footprints_df.to_crs(epsg=3979)
    footprints_df['BLDG_ID'] = footprints_df['CS_ID']

    # Representative points (inside polygon, unlike centroid)
    points_df = gpd.GeoDataFrame(
        {'BLDG_ID': footprints_df['BLDG_ID']},
        geometry=footprints_df['geometry'].representative_point(),
        crs=footprints_df.crs
    )

    # --- Points-in-Polygon analysis and building count ---

    log('  Performing spatial joins...')
    pip_DB, DB_prov = sjoin_count(points_df, DB_prov, 'DBUID', 'DBPOP2021', 'DB')
    pip_DA, DA_prov = sjoin_count(points_df, DA_prov, 'DAUID', 'DA_Population_2021_C1_COUNT_TOTAL', 'DA')
    pip_CSD, CSD_prov = sjoin_count(points_df, CSD_prov, 'CSDUID', 'CSD_Population_2021_C1_COUNT_TOTAL', 'CSD')
    pip_CD, CD_prov = sjoin_count(points_df, CD_prov, 'CDUID', 'CD_Population_2021_C1_COUNT_TOTAL', 'CD')

    log('  Calculating orphaned population from 0-building DBs...')
    # Extract DAUID from DBUID (first 8 characters)
    DB_prov['DAUID_from_DB'] = DB_prov['DBUID'].str[:8]
    
    # Find DBs with population but no buildings
    orphaned_dbs = DB_prov[(DB_prov['COUNT_DB'] == 0) & (DB_prov['DBPOP2021'] > 0)]
    
    # Sum the orphaned population per DA
    orphan_pop_da = orphaned_dbs.groupby('DAUID_from_DB')['DBPOP2021'].sum().reset_index(name='ORPHAN_POP')
    
    # Merge into DA_prov and calculate ratio per building in that DA
    DA_prov = DA_prov.merge(orphan_pop_da, left_on='DAUID', right_on='DAUID_from_DB', how='left')
    DA_prov['ORPHAN_POP'] = DA_prov['ORPHAN_POP'].fillna(0)
    
    # Calculate bonus ratio (handling division by zero if DA has 0 buildings)
    # If COUNT_DA is 0, the ratio will be inf, which we replace with 0
    DA_prov['ORPHAN_RATIO'] = DA_prov['ORPHAN_POP'] / DA_prov['COUNT_DA']
    DA_prov['ORPHAN_RATIO'] = DA_prov['ORPHAN_RATIO'].replace([np.inf, -np.inf, np.nan], 0)

    log('  Joining census ratios to building points...')

    # Merge UIDs and ratios onto points (attribute join, no spatial join needed)
    points_df = points_df.merge(pip_DB[['BLDG_ID', 'DBUID']], on='BLDG_ID', how='left')
    points_df = points_df.merge(DB_prov[['DBUID', 'DB_RATIO']], on='DBUID', how='left')

    points_df = points_df.merge(pip_DA[['BLDG_ID', 'DAUID']], on='BLDG_ID', how='left')
    points_df = points_df.merge(DA_prov[['DAUID', 'DA_RATIO', 'ORPHAN_RATIO']], on='DAUID', how='left')
    points_df['ORPHAN_RATIO'] = points_df['ORPHAN_RATIO'].fillna(0)

    points_df = points_df.merge(pip_CSD[['BLDG_ID', 'CSDUID']], on='BLDG_ID', how='left')
    points_df = points_df.merge(CSD_prov[['CSDUID', 'CSD_RATIO']], on='CSDUID', how='left')

    points_df = points_df.merge(pip_CD[['BLDG_ID', 'CDUID']], on='BLDG_ID', how='left')
    points_df = points_df.merge(CD_prov[['CDUID', 'CD_RATIO']], on='CDUID', how='left')

    # Calculate building population with fallback: DB → DA → CSD → CD, plus orphan bonus
    points_df['BLDG_POP'] = (
        points_df['DB_RATIO'].fillna(
            points_df['DA_RATIO'].fillna(
                points_df['CSD_RATIO'].fillna(
                    points_df['CD_RATIO']
                )
            )
        ) + points_df['ORPHAN_RATIO']
    ).round(3)

    points_df['POP_SOURCE'] = np.where(
        points_df['DB_RATIO'].notna(), 'DB_RATIO',
        np.where(
            points_df['DA_RATIO'].notna(), 'DA_RATIO',
            np.where(
                points_df['CSD_RATIO'].notna(), 'CSD_RATIO',
                np.where(points_df['CD_RATIO'].notna(), 'CD_RATIO', 'NONE')
            )
        )
    )

    n_bldg_pop_nan = points_df['BLDG_POP'].isna().sum()
    if n_bldg_pop_nan > 0:
        log(f'  BLDG_POP NaN before NONE cleanup: {n_bldg_pop_nan}')

    points_df.loc[points_df['POP_SOURCE'] == 'NONE', 'BLDG_POP'] = 0

    n_bldg_pop_nan_after = points_df['BLDG_POP'].isna().sum()
    log(f'  BLDG_POP NaN after NONE cleanup: {n_bldg_pop_nan_after}')

    points_df['HAS_ORPHAN_BONUS'] = (points_df['ORPHAN_RATIO'] > 0).astype(int)

    log('  Building population calculated...')

    # --- Validation ---

    n_none = (points_df['POP_SOURCE'] == 'NONE').sum()
    n_total = len(points_df)
    if n_none > 0:
        log(f'  WARNING: {n_none} buildings ({n_none/n_total*100:.1f}%) have no population source')

    log(f'  POP_SOURCE distribution:')
    for src in ['DB_RATIO', 'DA_RATIO', 'CSD_RATIO', 'CD_RATIO', 'NONE']:
        n = (points_df['POP_SOURCE'] == src).sum()
        log(f'    {src}: {n} ({n/n_total*100:.1f}%)')

    n_orphan_bonus = points_df['HAS_ORPHAN_BONUS'].sum()
    log(f'  Buildings receiving orphan bonus: {n_orphan_bonus}')

    # Height from Canada Structures layer
    points_df = points_df.merge(footprints_df[['BLDG_ID', 'Height']], on='BLDG_ID', how='left')
    points_df = points_df.rename(columns={'Height': 'HEIGHT'})

    for c in ['HEIGHT', 'DB_RATIO', 'DA_RATIO', 'CSD_RATIO', 'CD_RATIO', 'ORPHAN_RATIO']:
        if c in points_df.columns:
            points_df[c] = points_df[c].round(3)

    # --- Quality flags ---
    log('  Computing quality flags...')

    # QF_O: Orphan bonus exceeds DB allocation
    # Only flag when DB_RATIO > 0 (exclude rounding artifacts in large DBs)
    points_df['QF_O'] = (
        (points_df['ORPHAN_RATIO'] > points_df['DB_RATIO']) &
        (points_df['DB_RATIO'] > 0)
    ).astype(np.int8)

    # QF_V: Implausible population for building height
    # Only flag when we have positive confirmation of low height
    points_df['QF_V'] = (
        (points_df['BLDG_POP'] > 100) &
        (points_df['HEIGHT'] > 0) &
        (points_df['HEIGHT'] < 5)
    ).astype(np.int8)

    n_qf_o = points_df['QF_O'].sum()
    n_qf_v = points_df['QF_V'].sum()
    n_both = ((points_df['QF_O'] == 1) & (points_df['QF_V'] == 1)).sum()
    log(f'  QF_O (orphan exceeds DB): {n_qf_o:,} buildings')
    log(f'  QF_V (implausible pop/height): {n_qf_v:,} buildings')
    log(f'  Both flags: {n_both:,} buildings')

    # Log provincial summary for quality flags
    for flag_name in ['QF_O', 'QF_V']:
        flag_count = points_df[flag_name].sum()
        if flag_count > 0:
            flag_by_prov = points_df.loc[points_df[flag_name] == 1].groupby(
                points_df.loc[points_df[flag_name] == 1, 'DBUID'].str[:2]
            ).size()
            log(f'  {flag_name} by province:')
            # Avoid shadowing the outer province abbreviation used for output naming.
            for prov_code, count in flag_by_prov.items():
                log(f'    {prov_code}: {count:,}')

    # --- Assemble output layers ---

    out_cols = ['BLDG_ID', 'geometry', 'HEIGHT', 'DBUID', 'DB_RATIO',
                 'DAUID', 'DA_RATIO', 'CSDUID', 'CSD_RATIO',
                 'CDUID', 'CD_RATIO', 'ORPHAN_RATIO', 'HAS_ORPHAN_BONUS',
                 'BLDG_POP', 'POP_SOURCE', 'QF_O', 'QF_V']

    points_out = points_df[out_cols].copy()
    points_out = gpd.GeoDataFrame(points_out, geometry='geometry', crs='EPSG:3979')

    attr_cols = ['BLDG_ID', 'DBUID', 'DB_RATIO', 'DAUID', 'DA_RATIO',
                  'CSDUID', 'CSD_RATIO', 'CDUID', 'CD_RATIO', 'ORPHAN_RATIO',
                  'HAS_ORPHAN_BONUS', 'BLDG_POP', 'POP_SOURCE', 'HEIGHT', 'QF_O', 'QF_V']
    footprints_out = footprints_df[['BLDG_ID', 'geometry']].merge(
        points_df[attr_cols], on='BLDG_ID', how='left'
    )
    footprints_out = footprints_out[out_cols].copy()
    footprints_out = gpd.GeoDataFrame(footprints_out, geometry='geometry', crs='EPSG:3979')
    footprints_out['geometry'] = footprints_out['geometry'].apply(to_multipolygon)

    log(f'  Point layer finalized: {len(points_out)} features')
    log(f'  Footprint layer finalized: {len(footprints_out)} features')

    # --- Save ---

    pts_intm_path = f'{OUT_DIR}/Points_{prov}_{current_time}.gpkg'
    fps_intm_path = f'{OUT_DIR}/Footprints_{prov}_{current_time}.gpkg'
    write_dataframe(points_out, pts_intm_path, driver='GPKG')
    write_dataframe(footprints_out, fps_intm_path, driver='GPKG')
    log(f'  Saved intermediate: {os.path.basename(pts_intm_path)}, {os.path.basename(fps_intm_path)}')

    pts_final_path = f'{FINAL_DIR}/{VERSION_TAG}_Points_{prov}.gpkg'
    fps_final_path = f'{FINAL_DIR}/{VERSION_TAG}_Footprints_{prov}.gpkg'
    write_dataframe(points_out, pts_final_path, driver='GPKG')
    write_dataframe(footprints_out, fps_final_path, driver='GPKG')
    log(f'  Saved final: {os.path.basename(pts_final_path)}, {os.path.basename(fps_final_path)}')

    add_gpkg_metadata(pts_final_path)
    add_gpkg_metadata(fps_final_path)
    validate_gpkg_metadata(pts_final_path)
    validate_gpkg_metadata(fps_final_path)
    log('  Embedded GeoPackage metadata validated')

    zip_with_licenses(pts_final_path, f'{FINAL_DIR}/{VERSION_TAG}_Points_{prov}.zip')
    zip_with_licenses(fps_final_path, f'{FINAL_DIR}/{VERSION_TAG}_Footprints_{prov}.zip')

    os.remove(pts_final_path)
    os.remove(fps_final_path)
    log(f'  Removed unzipped final GPKGs (timestamped intermediates retained)')

    nat_points_path = f'{OUT_DIR}/{VERSION_TAG}_Points_Canada_{current_time}.gpkg'
    nat_footprints_path = f'{OUT_DIR}/{VERSION_TAG}_Footprints_Canada_{current_time}.gpkg'
    write_dataframe(
        points_out,
        nat_points_path,
        layer=NATIONAL_POINTS_LAYER,
        driver='GPKG',
        append=os.path.exists(nat_points_path),
    )
    write_dataframe(
        footprints_out,
        nat_footprints_path,
        layer=NATIONAL_FOOTPRINTS_LAYER,
        driver='GPKG',
        append=os.path.exists(nat_footprints_path),
    )
    log(f'  Appended to national: {os.path.basename(nat_points_path)}, {os.path.basename(nat_footprints_path)}')

    # --- Population conservation check ---
    log('  Population conservation:')
    total_bldg_pop = points_df['BLDG_POP'].sum()
    log(f'    Total BLDG_POP: {total_bldg_pop:,.1f}')
    log(f'    Total buildings: {n_total}')
    log(f'    Buildings with BLDG_POP > 0: {(points_df["BLDG_POP"] > 0).sum()}')
    log(f'    Buildings with BLDG_POP = 0: {(points_df["BLDG_POP"] == 0).sum()}')

    prov_pop = DB_prov['DBPOP2021'].sum()
    log(f'    Census DB total population ({prov}): {prov_pop:,.0f}')
    db_assigned = points_df[points_df['POP_SOURCE'] == 'DB_RATIO']['BLDG_POP'].sum()
    log(f'    BLDG_POP assigned via DB_RATIO: {db_assigned:,.1f}')

    # --- Output schema validation ---
    log('  Output schema validation:')
    for col in out_cols:
        present = col in points_out.columns and col in footprints_out.columns
        log(f'    {col}: {"OK" if present else "MISSING"}')
    log(f'    Points CRS: {points_out.crs}')
    log(f'    Footprints CRS: {footprints_out.crs}')
    log(f'    Points row count: {len(points_out)}')
    log(f'    Footprints row count: {len(footprints_out)}')

    # Free memory for next province
    del footprints_df, points_df, points_out, footprints_out
    del DB_prov, DA_prov, CSD_prov, CD_prov
    del pip_DB, pip_DA, pip_CSD, pip_CD

# --- National finalization ---

nat_pts_intm = f'{OUT_DIR}/{VERSION_TAG}_Points_Canada_{current_time}.gpkg'
nat_fps_intm = f'{OUT_DIR}/{VERSION_TAG}_Footprints_Canada_{current_time}.gpkg'

log('\n' + '='*60)
log('National finalization')
log('='*60)

for nat_intm, layer_type in [(nat_pts_intm, 'Points'), (nat_fps_intm, 'Footprints')]:
    final_name = f'{VERSION_TAG}_{layer_type}_Canada.gpkg'
    final_path = f'{FINAL_DIR}/{final_name}'

    log(f'  Copying {os.path.basename(nat_intm)} to {final_name}...')
    shutil.copy2(nat_intm, final_path)

    add_gpkg_metadata(final_path)
    validate_gpkg_metadata(final_path)
    log(f'  Embedded GeoPackage metadata validated for {final_name}')

    zip_with_licenses(final_path, f'{FINAL_DIR}/{final_name.replace(".gpkg", ".zip")}')

    os.remove(final_path)
    log(f'  Removed unzipped final {final_name}')

log('\nConverting national GeoPackages to GeoParquet...')
os.makedirs(GEOPARQUET_DIR, exist_ok=True)

convert_to_geoparquet(
    nat_pts_intm,
    f'{GEOPARQUET_DIR}/{VERSION_TAG}_Points_Canada.parquet'
)
add_parquet_metadata(f'{GEOPARQUET_DIR}/{VERSION_TAG}_Points_Canada.parquet')
validate_parquet_metadata(f'{GEOPARQUET_DIR}/{VERSION_TAG}_Points_Canada.parquet')
log(f'  Embedded GeoParquet metadata validated for {VERSION_TAG}_Points_Canada.parquet')
convert_to_geoparquet(
    nat_fps_intm,
    f'{GEOPARQUET_DIR}/{VERSION_TAG}_Footprints_Canada.parquet'
)
add_parquet_metadata(f'{GEOPARQUET_DIR}/{VERSION_TAG}_Footprints_Canada.parquet')
validate_parquet_metadata(f'{GEOPARQUET_DIR}/{VERSION_TAG}_Footprints_Canada.parquet')
log(f'  Embedded GeoParquet metadata validated for {VERSION_TAG}_Footprints_Canada.parquet')

# --- Save validation log ---
log_path = f'{OUT_DIR}/OBPL_validation_log_{current_time}.txt'
with open(log_path, 'w') as f:
    f.write('\n'.join(validation_log))
log(f'\nValidation log saved to {log_path}')

tend = time.perf_counter()
elapsed_time = tend - tstart
hours, remainder = divmod(elapsed_time, 3600)
minutes, seconds = divmod(remainder, 60)

log(f"Script execution time: {int(hours)} hours, {int(minutes)} minutes, {int(seconds)} seconds...")
