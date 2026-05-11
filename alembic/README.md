\# Database Migrations



To set up Alembic for TimescaleDB:



1\. Install alembic: pip install alembic

2\. Initialize: alembic init alembic

3\. Configure alembic.ini and env.py for async engine

4\. Create hypertable migration:

&#x20;  op.execute("SELECT create\_hypertable('violation\_events', 'time');")



For now, tables are created via `Base.metadata.create\_all()` on startup.

