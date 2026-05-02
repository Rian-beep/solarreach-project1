"""Composite scoring pipeline.

discover  → fetches the cheap signals (PVGIS, IMD, geocoding, mock CH).
score     → combines them into the 0-100 composite_score.
gate      → returns whether enrichment + paid APIs should fire.
"""
