# Database migration notes

`app.py:init_db()` applies idempotent SQLite upgrades for the starter schema. It adds `videos.user_id` and `steps.kind`, and marks untouched legacy `Transcript section N` rows as transcript segments. SQLAlchemy creates the additional users/reports tables without dropping existing rows.

`versions/001_add_ownership_and_reports.sql` documents the equivalent additive schema change for operators migrating a legacy database manually. Take a backup first. Do not run the reference SQL against a fresh database where `user_id` already exists. A full SQLite-to-PostgreSQL data migration is intentionally manual and documented in the project README.
