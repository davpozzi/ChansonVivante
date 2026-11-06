"""Application entry point. The desktop interface is implemented with native Flet controls."""
import flet as ft
from app_flet_clean import main

if __name__ == "__main__":
    ft.app(target=main)
