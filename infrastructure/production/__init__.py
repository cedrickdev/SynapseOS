"""Production infrastructure composition."""

from infrastructure.production.composition import build_production_application
from infrastructure.production.resources import (
    ProductionResources,
    build_production_resources,
)

__all__ = [
    "ProductionResources",
    "build_production_application",
    "build_production_resources",
]
