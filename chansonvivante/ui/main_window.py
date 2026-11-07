"""Interfaccia desktop essenziale per ChansonVivante, basata su controlli Flet nativi.

La finestra Flet gestisce esclusivamente stato e presentazione; il motore Demucs
è fornito dai servizi applicativi.
"""
import flet as ft

from chansonvivante.services.runtime import APP_ROOT, Value
from chansonvivante.services.demucs_backend import DemucsBackend


class DemucsApp(DemucsBackend):
    """Presentazione sobria; riutilizza integralmente il backend esistente."""

    def __init__(self, page):
        self.page = page
        page.title = "ChansonVivante"
        page.theme_mode = ft.ThemeMode.SYSTEM
        page.padding = 0
        page.horizontal_alignment = ft.CrossAxisAlignment.CENTER
        page.vertical_alignment = ft.MainAxisAlignment.START
        page.window.width = 900
        page.window.height = 780
        page.window.min_width = 840
        page.window.min_height = 680
        page.window.resizable = True

        self.input_file = Value("")
        self.output_dir = Value(str(APP_ROOT))
        self.format_var = Value("flac")
        self.bit_var = Value("16-bit")
        self.model_var = Value("htdemucs")
        self.stems_var = Value("Solo Voce e Base (2 tracce)")
        self.shifts_var = Value("1 (Standard)")
        self.device_mode_var = Value("Automatica")
        self.budget_gb = 3.0
        self.ui_queue = __import__("queue").Queue()
        self.log_history = []
        self.log_window = None
        self.log_textbox = None
        self.has_cuda = False
        self.ai_ready = False
        self.model_installing = False

        self._build_ui()
        self.page.run_task(self._poll_queue)
        self.page.run_task(self._load_ai_after_ui)

    def _model_mode_changed(self, e):
        # L'interfaccia espone una scelta comprensibile; il backend riceve il nome Demucs.
        self.model_var.set("htdemucs_ft" if e.control.value == "Approfondita" else "htdemucs")
        self.page.update()

    def _build_ui(self):
        self.input_picker = ft.FilePicker(on_result=self._input_picked)
        self.output_picker = ft.FilePicker(on_result=self._output_picked)
        self.page.overlay.extend([self.input_picker, self.output_picker])

        self.input_field = ft.TextField(
            label="File audio", value="", read_only=True, expand=True,
            hint_text="Seleziona un file MP3, WAV, FLAC o M4A",
            border_radius=4,
        )
        self.output_field = ft.TextField(
            label="Cartella di destinazione", value=str(APP_ROOT),
            read_only=True, expand=True, border_radius=4,
        )

        self.format_control = ft.Dropdown(
            label="Formato", value="flac", expand=True,
            options=[ft.dropdown.Option(x) for x in ("flac", "wav", "mp3")],
            on_change=lambda e: self.format_var.set(e.control.value),
        )
        self.bit_control = ft.Dropdown(
            label="Qualità", value="16-bit", expand=True,
            options=[ft.dropdown.Option(x) for x in ("16-bit", "24-bit")],
            on_change=lambda e: self.bit_var.set(e.control.value),
        )
        self.model_control = ft.Dropdown(
            label="Modalità", value="Veloce", expand=True,
            options=[ft.dropdown.Option("Veloce"), ft.dropdown.Option("Approfondita")],
            on_change=self._model_mode_changed,
        )
        self.shifts_control = ft.Dropdown(
            label="Precisione", value="1 (Standard)", expand=True,
            options=[ft.dropdown.Option(x) for x in (
                "0 (Veloce)", "1 (Standard)", "2 (Preciso)", "3 (Lento)"
            )],
            on_change=lambda e: self.shifts_var.set(e.control.value),
        )
        self.stems_control = ft.Dropdown(
            label="Tracce da generare", value=self.stems_var.get(), expand=True,
            options=[
                ft.dropdown.Option("Solo Voce e Base (2 tracce)"),
                ft.dropdown.Option("Tutti gli strumenti (4 tracce)"),
            ],
            on_change=lambda e: self.stems_var.set(e.control.value),
        )
        self.device_control = ft.Dropdown(
            label="Modalità di elaborazione", value="Automatica", width=250,
            options=[ft.dropdown.Option(x) for x in ("Automatica", "Manuale", "Solo CPU")],
            on_change=self._device_changed,
        )
        self.budget_text = ft.Text("Memoria GPU: 3,0 GB")
        self.budget_slider = ft.Slider(
            min=1, max=12, divisions=22, value=3,
            on_change=self._budget_changed, expand=True,
        )
        self.gpu_info = ft.Text("Rilevamento GPU in corso...", size=12)
        self.status_text = ft.Text(
            "Preparazione del motore audio...", size=13, expand=True
        )
        self.progress = ft.ProgressRing(width=18, height=18, stroke_width=2, visible=False)
        self.start_button = ft.Button(
            content="Avvia separazione", on_click=self._start_clicked,
            height=42, width=210, disabled=True,
        )
        self.logs_button = ft.TextButton(
            "Visualizza log", on_click=lambda e: self.open_log_window()
        )
        self.input_browse_button = ft.OutlinedButton(
            "Sfoglia...", on_click=lambda e: self.input_picker.pick_files(
                allow_multiple=False,
                allowed_extensions=["mp3", "wav", "flac", "m4a"],
            ),
        )
        self.output_browse_button = ft.OutlinedButton(
            "Sfoglia...", on_click=lambda e: self.output_picker.get_directory_path()
        )

        heading = ft.Column(
            [
                ft.Icon(ft.Icons.GRAPHIC_EQ, size=34),
                ft.Text("ChansonVivante", size=25, weight=ft.FontWeight.W_600),
                ft.Text("Separazione delle tracce audio", size=13),
            ],
            spacing=3,
        )

        files_section = ft.Column(
            [
                ft.Text("File", size=16, weight=ft.FontWeight.W_600),
                ft.Row([self.input_field, self.input_browse_button], spacing=8),
                ft.Row([self.output_field, self.output_browse_button], spacing=8),
            ],
            spacing=9,
        )

        settings_section = ft.Column(
            [
                ft.Text("Impostazioni", size=16, weight=ft.FontWeight.W_600),
                ft.Row([self.format_control, self.bit_control], spacing=12),
                ft.Row([self.model_control, self.shifts_control], spacing=12),
                self.stems_control,
                ft.Text(
                    "Veloce usa htdemucs, per una separazione più rapida. Approfondita usa "
                    "htdemucs_ft, che può migliorare leggermente il risultato ma richiede "
                    "circa quattro volte il tempo.",
                    size=12,
                ),
            ],
            spacing=9,
        )

        gpu_section = ft.Column(
            [
                ft.Text("GPU", size=16, weight=ft.FontWeight.W_600),
                ft.Row([self.device_control, self.budget_text], spacing=16),
                ft.Row(
                    [self.budget_slider, ft.Text("1–12 GB", size=11)],
                    spacing=8,
                ),
                self.gpu_info,
            ],
            spacing=8,
        )

        content = ft.Column(
            [
                heading,
                ft.Divider(height=1),
                files_section,
                ft.Divider(height=1),
                settings_section,
                ft.Divider(height=1),
                gpu_section,
                ft.Divider(height=1),
                ft.Row([self.progress, self.status_text], spacing=10),
                ft.Row(
                    [self.start_button, self.logs_button],
                    alignment=ft.MainAxisAlignment.START,
                    spacing=14,
                ),
                ft.Text(
                    "Il budget VRAM è indicativo. La memoria effettivamente disponibile "
                    "dipende anche da Windows e dagli altri programmi in esecuzione.",
                    size=11,
                ),
            ],
            spacing=16,
        )

        # Lo scroll deve appartenere al contenitore che occupa l'area client
        # della finestra. La Column interna, da sola, non ha un'altezza limitata.
        self.page.add(
            ft.Column(
                [
                    ft.Container(
                        content=content,
                        width=780,
                        padding=ft.Padding.symmetric(horizontal=22, vertical=24),
                    )
                ],
                expand=True,
                scroll=ft.ScrollMode.AUTO,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=0,
            )
        )
        self.page.update()
