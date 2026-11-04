-- Reference migration for the legacy SQLite schema. app.py applies the SQLite
-- equivalent add-column migration idempotently at startup. PostgreSQL deployments
-- use SQLAlchemy create_all for new tables; apply this only to legacy databases.
ALTER TABLE videos ADD COLUMN user_id INTEGER REFERENCES user(id);
ALTER TABLE steps ADD COLUMN kind VARCHAR(30) DEFAULT 'instruction';
-- Do not delete or rewrite existing video/step rows. Assign legacy ownership
-- after creating the initial administrator account.
