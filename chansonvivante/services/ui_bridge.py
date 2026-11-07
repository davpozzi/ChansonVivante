"""Ponte tra worker asincroni e controlli della finestra Flet."""
import asyncio
import os
import queue
import threading
from pathlib import Path

import flet as ft

from . import runtime as _runtime
from .runtime import available_cuda_memory


class UIQueueMixin:
    async def _load_ai_after_ui(self):
        self.status_text.value = "Caricamento motore AI in background..."
        self.page.update()
        threading.Thread(target=self.load_ai_dependencies_worker, daemon=True).start()

    async def _poll_queue(self):
        while True:
            try:
                while True:
                    item = self.ui_queue.get_nowait()
                    kind = item[0]
                    if kind == "log":
                        self.append_log(item[1], item[2])
                    elif kind == "status":
                        self.status_text.value = item[1]
                        self.status_text.color = item[2]
                        self.append_log("INFO", item[1])
                    elif kind == "error":
                        self.status_text.value = f"Errore: {item[1]}"
                        self.status_text.color = "#f87171"
                        self.append_log("ERROR", item[1])
                        self._message("Errore elaborazione AI", item[1])
                    elif kind == "done":
                        self.status_text.value = item[1]
                        self.status_text.color = "#4ade80"
                        self.append_log("SUCCESS", item[1])
                        if item[2] and os.name == "nt":
                            try: os.startfile(item[2])
                            except OSError: pass
                    elif kind == "ai_ready":
                        self.ai_ready = True
                        try: self.has_cuda = bool(_runtime.torch.cuda.is_available())
                        except Exception: self.has_cuda = False
                        self.status_text.value = "Motore AI pronto. Pronto per l'elaborazione."
                        self.status_text.color = "#4ade80"
                        self.start_button.disabled = False
                        self.refresh_gpu_info()
                        self.append_log("SUCCESS", "Motore AI caricato.")
                        await asyncio.sleep(0.1)
                        self.check_model_on_startup()
                    elif kind == "ai_error":
                        self.status_text.value = "Motore AI non disponibile."
                        self.status_text.color = "#f87171"
                        self.append_log("ERROR", item[1])
                        self._message("Errore avvio AI", item[1])
                    elif kind == "model_install_finished":
                        self.model_installing = False
                    elif kind == "finished":
                        self.set_running_state(False)
            except queue.Empty:
                pass
            self.page.update()
            await asyncio.sleep(0.1)

    def _message(self, title, message):
        dlg = ft.AlertDialog(title=ft.Text(title), content=ft.Text(message),
            actions=[ft.TextButton(content="OK", on_click=lambda e: self.page.pop_dialog())])
        self.page.show_dialog(dlg)

    def _confirm(self, title, message, yes_callback):
        def yes(e):
            self.page.close(dlg)
            yes_callback()
        dlg = ft.AlertDialog(title=ft.Text(title), content=ft.Text(message),
            actions=[ft.TextButton(content="Annulla", on_click=lambda e: self.page.close(dlg)),
                     ft.FilledButton(content="Sì", on_click=yes)])
        self.page.open(dlg)

    def _start_clicked(self, e):
        self.start_thread()

    def _device_changed(self, e):
        self.device_mode_var.set(e.control.value)
        self.on_device_mode_change(e.control.value)
        self.page.update()

    def _budget_changed(self, e):
        self.on_budget_change(e.control.value)
        self.page.update()

    def check_model_on_startup(self):
        model_name = self.model_var.get()
        try:
            installed = self.is_model_installed(model_name)
        except Exception as error:
            self.append_log("WARNING", f"Controllo modello non riuscito: {error}")
            return
        if not installed:
            self._confirm("Modello non installato",
                f"Il modello '{model_name}' non è installato. Vuoi installarlo ora?\n\nIl download verrà mostrato nella finestra dei log.",
                lambda: self.start_model_installation(model_name))

    def start_thread(self):
        if not self.ai_ready:
            self._message("Motore AI", "Il motore AI è ancora in caricamento. Riprova tra qualche secondo.")
            return
        input_name = self.input_file.get()
        if not input_name:
            self._message("Errore", "Seleziona prima una traccia audio.")
            return
        if not Path(input_name).is_file():
            self._message("Errore", "Il file audio selezionato non esiste.")
            return
        selected_model = self.model_var.get()
        try: installed = self.is_model_installed(selected_model)
        except Exception as error:
            self._message("Errore modello", str(error)); return
        if not installed:
            self._confirm("Modello non installato",
                f"Il modello '{selected_model}' non è installato. Vuoi installarlo ora?\n\nDopo il download, premi di nuovo 'Avvia separazione'.",
                lambda: self.start_model_installation(selected_model))
            return
        settings = {
            "input_path": input_name, "output_dir": self.output_dir.get(),
            "format": self.format_var.get(), "model": self.model_var.get(),
            "is_24bit": self.bit_var.get() == "24-bit",
            "shifts": int(self.shifts_var.get().split()[0]),
            "two_stems": "2 tracce" in self.stems_var.get(),
            "device_mode": self.device_mode_var.get(), "budget_gb": self.budget_gb,
        }
        self.set_running_state(True)
        self.ui_queue.put(("status", "Preparazione separazione...", "#fbbf24"))
        threading.Thread(target=self.run_demucs_api, args=(settings,), daemon=True).start()

    def open_log_window(self):
        if self.log_window is not None:
            self.page.open(self.log_window)
            return
        self.log_content = ft.TextField(value="", multiline=True, min_lines=15,
            max_lines=24, read_only=True, text_size=12, expand=True,
            text_style=ft.TextStyle(font_family="Consolas"))
        dlg = ft.AlertDialog(
            modal=False, title=ft.Text("ChansonVivante · Log elaborazione"),
            content=ft.Container(content=self.log_content, width=760, height=430),
            actions=[
                ft.TextButton(content="Svuota log", on_click=lambda e: self.clear_log()),
                ft.TextButton(content="Chiudi", on_click=lambda e: self.page.close(dlg)),
            ])
        self.log_window = dlg
        self.page.open(dlg)
        self._refresh_log_view()

    def append_log(self, level, message):
        self.log_history.append((level, message))
        if len(self.log_history) > 5000:
            del self.log_history[:1000]
        if self.log_window is not None:
            self._refresh_log_view()

    def _refresh_log_view(self):
        if self.log_window is not None:
            self.log_content.value = "\n".join(f"[{level}] {msg}" for level, msg in self.log_history)
            self.page.update()

    def clear_log(self):
        self.log_history.clear()
        self._refresh_log_view()

    def refresh_gpu_info(self):
        memory = available_cuda_memory()
        if memory:
            free_gb, total_gb = memory
            self.gpu_info.value = f"CUDA disponibile · VRAM libera {free_gb:.1f} GB / {total_gb:.1f} GB"
            self.gpu_info.color = "#4ade80"
        elif self.has_cuda:
            self.gpu_info.value = "CUDA rilevata; memoria libera non leggibile. Sarà usata la gestione prudenziale."
            self.gpu_info.color = "#fbbf24"
        else:
            self.gpu_info.value = "GPU CUDA non disponibile: sarà possibile elaborare usando la CPU."
            self.gpu_info.color = "#fbbf24"
        self.on_device_mode_change(self.device_mode_var.get())

    def on_budget_change(self, value):
        self.budget_gb = round(float(value) * 2) / 2
        self.budget_text.value = f"Budget VRAM: {self.budget_gb:.1f} GB"

    def on_device_mode_change(self, _value=None):
        manual = self.device_mode_var.get() == "Manuale"
        self.budget_slider.disabled = not (manual and self.has_cuda)
        options = ["Automatica", "Manuale", "Solo CPU"] if self.has_cuda else ["Automatica", "Solo CPU"]
        self.device_control.options = [ft.DropdownOption(key=x, text=x) for x in options]
        if not self.has_cuda and self.device_mode_var.get() == "Manuale":
            self.device_mode_var.set("Automatica")
            self.device_control.value = "Automatica"

    def set_running_state(self, running):
        self.start_button.disabled = running or not self.ai_ready
        self.start_button.content = "Elaborazione in corso..." if running else "Avvia separazione"
        for control in [self.input_field, self.output_field, self.format_control,
                        self.bit_control, self.model_control, self.shifts_control,
                        self.stems_control, self.device_control, self.budget_slider,
                        self.input_browse_button, self.output_browse_button]:
            control.disabled = running
        self.progress.visible = running
        self.page.update()

    async def browse_input(self):
        files = await self.input_picker.pick_files(
            allow_multiple=False,
            file_type=ft.FilePickerFileType.CUSTOM,
            allowed_extensions=["mp3", "wav", "flac", "m4a"],
        )
        if files:
            selected_path = files[0].path
            if selected_path:
                self.input_file.set(selected_path)
                self.input_field.value = selected_path
                self.page.update()

    async def browse_output(self):
        selected_path = await self.output_picker.get_directory_path()
        if selected_path:
            self.output_dir.set(selected_path)
            self.output_field.value = selected_path
            self.page.update()