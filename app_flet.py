"""Compatibility import for integrations using the historical module path."""
from chansonvivante.services.runtime import APP_ROOT, Value, resource_path
from chansonvivante.ui.main_window import DemucsApp

__all__ = ["APP_ROOT", "Value", "DemucsApp", "resource_path"]
