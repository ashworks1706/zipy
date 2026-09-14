-- Runs once, on an empty data volume. Tables come from alembic (just migrate), not from here.
CREATE EXTENSION IF NOT EXISTS vector;
CREATE DATABASE langfuse;
