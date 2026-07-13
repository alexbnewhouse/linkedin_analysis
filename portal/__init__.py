"""NHA Pathways portal data pipeline: education->career join + per-major analyses.

Computes every per-major number behind the Pathways portal prototype from the
committed spine (`paths/`), the education rollup (`normalized/education.parquet`),
the occupation transition network, the industry taxonomy, and O*NET Job Zones.
Single driver: `python -m portal.run_portal_data`.
"""
