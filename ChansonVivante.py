"""Entry point leggero: mostra lo splash prima di importare la UI e i servizi."""
import asyncio
import multiprocessing
import os
import sys
from datetime import datetime
from pathlib import Path

import flet as ft


APP_ROOT = (
    Path(sys.executable).parent.resolve()
    if getattr(sys, "frozen", False)
    else Path(__file__).parent.resolve()
)


def write_startup_diagnostic():
    """Registra i dati minimi del processo per diagnosticare avvii duplicati su Windows."""
    try:
        local_data = Path(
            os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
        )
        log_dir = local_data / "ChansonVivante" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        children = multiprocessing.active_children()
        line = (
            f"{datetime.now().astimezone().isoformat()} "
            f"pid={os.getpid()} ppid={os.getppid()} "
            f"frozen={getattr(sys, 'frozen', False)} "
            f"executable={sys.executable!r} "
            f"active_children={len(children)}\n"
        )
        with (log_dir / "startup.log").open("a", encoding="utf-8") as log:
            log.write(line)
    except Exception:
        # La diagnostica non deve mai impedire l'avvio dell'applicazione.
        pass


async def main(page: ft.Page):
    page.title = "ChansonVivante"
    page.theme_mode = ft.ThemeMode.SYSTEM
    page.padding = 0
    page.window.width = 900
    page.window.height = 780
    page.window.min_width = 840
    page.window.min_height = 680
    page.window.resizable = True
    resource_root = Path(getattr(sys, "_MEIPASS", APP_ROOT))
    page.window.icon = str(resource_root / "logo.ico")
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
    multiprocessing.freeze_support()
    write_startup_diagnostic()
    ft.run(main)
