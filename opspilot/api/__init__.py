"""OpsPilot API routes module."""
from opspilot.api.routes_webhook import router as webhook_router
from opspilot.api.routes_diagnose import router as diagnose_router

__all__ = ["webhook_router", "diagnose_router"]
