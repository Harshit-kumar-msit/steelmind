"""
api/routes/__init__.py
Re-exports all routers so main.py can import them cleanly.
"""
from app.api.routes import equipment, sensors, alerts, workorders, copilot, anomaly
from app.api.routes._combined import reports_router as reports, inventory_router as inventory, auth_router as auth

# Re-create module objects that match what main.py expects
import types

reports_mod  = types.SimpleNamespace(router=reports)
inventory_mod= types.SimpleNamespace(router=inventory)
auth_mod     = types.SimpleNamespace(router=auth)

# Expose as attributes so `from app.api.routes import reports` works
reports  = reports_mod
inventory= inventory_mod
auth     = auth_mod
