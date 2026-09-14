"""Postgres, pgvector and Redis. The only package that imports a database driver.

Every repository query is scoped by org_id; a repository method without one does not exist,
except the workspace lookup that finds the org and the workers' sweeps across every org.
"""
