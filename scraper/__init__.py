"""CA ADU Zoning API - scraper worker package.

Deployable to Render as a weekly cron worker. Iterates the 8 target cities in
the `cities` table, dispatches each to the right publisher adapter (ALP or
Municode), extracts raw ADU / zoning section text and upserts it into the
`zoning_sections` table via the Supabase service role.
"""

__all__ = ["__version__"]
__version__ = "0.1.0"
