"""Avvio dell'app con splash screen prima di importare il motore audio."""
import asyncio
import flet as ft


async def main(page: ft.Page):
    # Imposta subito i limiti della finestra, già durante lo splash.
    page.title = "ChansonVivante"
    page.theme_mode = ft.ThemeMode.SYSTEM
    page.padding = 0
    page.window_width = 900
    page.window_height = 780
    page.window_min_width = 840
    page.window_min_height = 680
    page.window_resizable = True
    page.horizontal_alignment = ft.CrossAxisAlignment.CENTER
    page.vertical_alignment = ft.MainAxisAlignment.CENTER

    page.add(
        ft.Column(
            [
                ft.Text("ChansonVivante", size=24, weight=ft.FontWeight.W_600),
                ft.Text("Caricamento del motore audio...", size=13),
                ft.ProgressRing(width=22, height=22, stroke_width=2),
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=12,
        )
    )
    page.update()

    # Lascia il tempo a Flet di mostrare lo splash prima degli import pesanti.
    await asyncio.sleep(0.2)
    from app_flet_clean import DemucsApp

    page.clean()
    DemucsApp(page)


if __name__ == "__main__":
    ft.app(target=main)
