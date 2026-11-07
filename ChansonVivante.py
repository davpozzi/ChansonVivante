"""Entry point leggero: mostra lo splash prima di importare la UI e i servizi."""
import asyncio
import sys
from pathlib import Path

import flet as ft


APP_ROOT = (
    Path(sys.executable).parent.resolve()
    if getattr(sys, "frozen", False)
    else Path(__file__).parent.resolve()
)


async def main(page: ft.Page):
    page.title = "ChansonVivante"
    page.theme_mode = ft.ThemeMode.SYSTEM
    page.padding = 0
    page.window_width = 900
    page.window_height = 780
    page.window_min_width = 840
    page.window_min_height = 680
    page.window_resizable = True
    page.window.icon = str(APP_ROOT / "logo.ico")
    page.horizontal_alignment = ft.CrossAxisAlignment.CENTER
    page.vertical_alignment = ft.MainAxisAlignment.CENTER

    page.add(
        ft.Column(
            [
                ft.Icon(ft.Icons.GRAPHIC_EQ, size=46),
                ft.Text("ChansonVivante", size=24, weight=ft.FontWeight.W_600),
                ft.Text("Preparazione dell'ambiente audio...", size=13),
                ft.ProgressRing(width=22, height=22, stroke_width=2),
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=12,
        )
    )
    page.update()

    # Yield al renderer: lo splash appare prima di importare i moduli applicativi.
    await asyncio.sleep(0.2)
    from chansonvivante.ui.main_window import DemucsApp

    page.clean()
    DemucsApp(page)


if __name__ == "__main__":
    ft.app(target=main)
