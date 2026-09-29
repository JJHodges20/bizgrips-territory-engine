"""Public-data ingestion (Milestone 1).

Pure parsing and computation live here so they can be unit tested on tiny fixtures; the CLIs
in ``scripts/`` only wire arguments, downloads and the database together.

Modules:
    download   fetch a URL to data/raw with a sha256 checksum (skip when already present)
    geography  boundary shapefile -> centroids, areas, rook adjacency, state, city, postal ZIP
    census     ACS 5-year estimates -> per-ZCTA field values (API or summary-file backend)
    store      upserts into zcta_markets / zcta_adjacency and provenance records
    states     FIPS -> USPS state code reference table
"""
