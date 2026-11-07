"""Regression tests for the Flet 1.x UI migration.

These tests exercise control construction and the callbacks that were previously
missed by the migration smoke test. They intentionally avoid launching a desktop
window or loading the heavy Demucs/PyTorch runtime.
"""
import asyncio
import inspect
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import flet as ft

import ChansonVivante
from chansonvivante.ui.main_window import DemucsApp


class FakePage:
    def __init__(self):
        self.services = []
        self.window = ft.Window()
        self.controls = []
        self.tasks = []
        self.dialogs = []
        self.update_count = 0

    def add(self, *controls):
        self.controls.extend(controls)

    def clean(self):
        self.controls.clear()

    def update(self):
        self.update_count += 1

    def run_task(self, handler, *args):
        self.tasks.append((handler, args))

    def show_dialog(self, dialog):
        self.dialogs.append(dialog)

    def pop_dialog(self):
        if self.dialogs:
            self.dialogs.pop()


class FakeFilePicker:
    def __init__(self, files=None, directory=None):
        self.files = files or []
        self.directory = directory
        self.pick_args = None

    async def pick_files(self, **kwargs):
        self.pick_args = kwargs
        return self.files

    async def get_directory_path(self):
        return self.directory


class FletMigrationTests(unittest.TestCase):
    def setUp(self):
        self.page = FakePage()
        self.app = DemucsApp(self.page)

    def test_entrypoint_and_window_configuration(self):
        self.assertTrue(callable(ft.run))
        self.assertTrue(callable(getattr(ft.Page, "show_dialog", None)))
        self.assertTrue(callable(getattr(ft.Page, "pop_dialog", None)))
        self.assertEqual(self.page.window.width, 900)
        self.assertEqual(self.page.window.height, 780)
        self.assertEqual(self.page.window.min_width, 840)
        self.assertEqual(self.page.window.min_height, 680)
        self.assertTrue(self.page.window.resizable)

    def test_all_dropdowns_use_select_events_and_explicit_options(self):
        dropdowns = (
            self.app.format_control,
            self.app.bit_control,
            self.app.model_control,
            self.app.shifts_control,
            self.app.stems_control,
            self.app.device_control,
        )
        for dropdown in dropdowns:
            self.assertIsNotNone(dropdown.on_select)
            self.assertTrue(dropdown.options)
            for option in dropdown.options:
                self.assertIsNotNone(option.key)
                self.assertIsNotNone(option.text)

        self.app.format_control.on_select(
            SimpleNamespace(control=SimpleNamespace(value="wav"))
        )
        self.assertEqual(self.app.format_var.get(), "wav")

        self.app.bit_control.on_select(
            SimpleNamespace(control=SimpleNamespace(value="24-bit"))
        )
        self.assertEqual(self.app.bit_var.get(), "24-bit")

        self.app.model_control.on_select(
            SimpleNamespace(control=SimpleNamespace(value="Approfondita"))
        )
        self.assertEqual(self.app.model_var.get(), "htdemucs_ft")

        self.app.shifts_control.on_select(
            SimpleNamespace(control=SimpleNamespace(value="2 (Preciso)"))
        )
        self.assertEqual(self.app.shifts_var.get(), "2 (Preciso)")

        self.app.stems_control.on_select(
            SimpleNamespace(control=SimpleNamespace(value="Tutti gli strumenti (4 tracce)"))
        )
        self.assertEqual(self.app.stems_var.get(), "Tutti gli strumenti (4 tracce)")

    def test_slider_keeps_on_change_and_updates_vram_budget(self):
        self.assertIsNotNone(self.app.budget_slider.on_change)
        self.app.budget_slider.on_change(
            SimpleNamespace(control=SimpleNamespace(value=4.25))
        )
        self.assertEqual(self.app.budget_gb, 4.0)
        self.assertEqual(self.app.budget_text.value, "Budget VRAM: 4.0 GB")

    def test_file_picker_buttons_await_results(self):
        self.assertTrue(inspect.iscoroutinefunction(ft.FilePicker.pick_files))
        self.assertTrue(inspect.iscoroutinefunction(ft.FilePicker.get_directory_path))
        self.assertTrue(asyncio.iscoroutinefunction(self.app.browse_input))
        self.assertTrue(asyncio.iscoroutinefunction(self.app.browse_output))

        self.app.input_picker = FakeFilePicker(
            files=[SimpleNamespace(path="C:/audio/brano.wav")]
        )
        self.app.output_picker = FakeFilePicker(directory="C:/audio/output")

        asyncio.run(self.app.browse_input())
        asyncio.run(self.app.browse_output())

        self.assertEqual(self.app.input_file.get(), "C:/audio/brano.wav")
        self.assertEqual(self.app.input_field.value, "C:/audio/brano.wav")
        self.assertEqual(self.app.output_dir.get(), "C:/audio/output")
        self.assertEqual(self.app.output_field.value, "C:/audio/output")
        self.assertEqual(
            self.app.input_picker.pick_args["file_type"],
            ft.FilePickerFileType.CUSTOM,
        )
        self.assertEqual(
            self.app.input_picker.pick_args["allowed_extensions"],
            ["mp3", "wav", "flac", "m4a"],
        )

    def test_dialogs_open_and_close_with_flet_1_page_api(self):
        self.app._message("Titolo", "Messaggio")
        self.assertEqual(len(self.page.dialogs), 1)
        self.page.dialogs[-1].actions[0].on_click(None)
        self.assertEqual(len(self.page.dialogs), 0)

        called = []
        self.app._confirm("Conferma", "Procedere?", lambda: called.append(True))
        self.assertEqual(len(self.page.dialogs), 1)
        self.page.dialogs[-1].actions[1].on_click(None)
        self.assertEqual(called, [True])
        self.assertEqual(len(self.page.dialogs), 0)

    def test_log_dialog_can_open_refresh_and_close(self):
        self.app.open_log_window()
        self.assertEqual(len(self.page.dialogs), 1)
        self.app.append_log("INFO", "riga di prova")
        self.assertIn("[INFO] riga di prova", self.app.log_content.value)
        self.app.log_window.actions[-1].on_click(None)
        self.assertEqual(len(self.page.dialogs), 0)

    def test_button_content_and_running_state(self):
        self.assertEqual(self.app.start_button.content, "Avvia separazione")
        self.app.ai_ready = True
        self.app.set_running_state(True)
        self.assertEqual(self.app.start_button.content, "Elaborazione in corso...")
        self.assertTrue(self.app.start_button.disabled)
        self.assertTrue(self.app.progress.visible)

        self.app.set_running_state(False)
        self.assertEqual(self.app.start_button.content, "Avvia separazione")
        self.assertFalse(self.app.start_button.disabled)
        self.assertFalse(self.app.progress.visible)

    def test_file_picker_cancel_does_not_erase_current_selection(self):
        self.app.input_file.set("C:/audio/precedente.wav")
        self.app.input_field.value = "C:/audio/precedente.wav"
        self.app.output_dir.set("C:/audio/output")
        self.app.output_field.value = "C:/audio/output"
        self.app.input_picker = FakeFilePicker(files=[])
        self.app.output_picker = FakeFilePicker(directory=None)

        asyncio.run(self.app.browse_input())
        asyncio.run(self.app.browse_output())

        self.assertEqual(self.app.input_file.get(), "C:/audio/precedente.wav")
        self.assertEqual(self.app.input_field.value, "C:/audio/precedente.wav")
        self.assertEqual(self.app.output_dir.get(), "C:/audio/output")
        self.assertEqual(self.app.output_field.value, "C:/audio/output")

    def test_start_thread_passes_every_selected_setting_to_demucs(self):
        self.app.ai_ready = True
        self.app.is_model_installed = lambda _model: True
        self.app.output_dir.set("C:/audio/output")
        self.app.format_var.set("wav")
        self.app.bit_var.set("24-bit")
        self.app.model_var.set("htdemucs_ft")
        self.app.shifts_var.set("2 (Preciso)")
        self.app.stems_var.set("Tutti gli strumenti (4 tracce)")
        self.app.device_mode_var.set("Manuale")
        self.app.budget_gb = 5.5

        with tempfile.NamedTemporaryFile(suffix=".wav") as source:
            self.app.input_file.set(source.name)
            with patch("chansonvivante.services.ui_bridge.threading.Thread") as thread:
                self.app.start_thread()

        thread.assert_called_once()
        kwargs = thread.call_args.kwargs
        self.assertIs(kwargs["target"].__self__, self.app)
        self.assertIs(kwargs["target"].__func__, self.app.run_demucs_api.__func__)
        self.assertTrue(kwargs["daemon"])
        settings = kwargs["args"][0]
        self.assertEqual(settings, {
            "input_path": source.name,
            "output_dir": "C:/audio/output",
            "format": "wav",
            "model": "htdemucs_ft",
            "is_24bit": True,
            "shifts": 2,
            "two_stems": False,
            "device_mode": "Manuale",
            "budget_gb": 5.5,
        })
        thread.return_value.start.assert_called_once()
        self.assertTrue(self.app.start_button.disabled)

    def test_gpu_mode_controls_manual_budget_availability(self):
        self.app.has_cuda = True
        self.app.device_mode_var.set("Manuale")
        self.app.on_device_mode_change()
        self.assertFalse(self.app.budget_slider.disabled)
        self.assertEqual(
            [option.key for option in self.app.device_control.options],
            ["Automatica", "Manuale", "Solo CPU"],
        )

        self.app.has_cuda = False
        self.app.on_device_mode_change()
        self.assertTrue(self.app.budget_slider.disabled)
        self.assertEqual(self.app.device_mode_var.get(), "Automatica")
        self.assertEqual(self.app.device_control.value, "Automatica")
        self.assertEqual(
            [option.key for option in self.app.device_control.options],
            ["Automatica", "Solo CPU"],
        )

    def test_log_dialog_can_be_reopened_and_cleared(self):
        self.app.append_log("INFO", "prima riga")
        self.app.open_log_window()
        self.page.dialogs[-1].actions[-1].on_click(None)
        self.assertEqual(len(self.page.dialogs), 0)

        self.app.open_log_window()
        self.assertEqual(len(self.page.dialogs), 1)
        self.assertIn("prima riga", self.app.log_content.value)
        self.page.dialogs[-1].actions[0].on_click(None)
        self.assertEqual(self.app.log_history, [])
        self.assertEqual(self.app.log_content.value, "")

    def test_missing_model_prompts_before_installation(self):
        self.app.is_model_installed = lambda _model: False
        self.app.check_model_on_startup()
        self.assertEqual(len(self.page.dialogs), 1)
        self.assertIn("htdemucs", self.page.dialogs[0].content.value)
        self.page.dialogs[0].actions[0].on_click(None)
        self.assertEqual(len(self.page.dialogs), 0)

    def test_queue_poller_applies_worker_events_on_the_ui_loop(self):
        self.app.model_installing = True
        self.app.ui_queue.put(("log", "INFO", "worker log"))
        self.app.ui_queue.put(("status", "Elaborazione...", "#fbbf24"))
        self.app.ui_queue.put(("error", "errore simulato"))
        self.app.ui_queue.put(("model_install_finished",))
        self.app.ui_queue.put(("finished",))

        async def one_poll_cycle():
            task = asyncio.create_task(self.app._poll_queue())
            await asyncio.sleep(0.01)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        asyncio.run(one_poll_cycle())

        self.assertEqual(self.app.status_text.value, "Errore: errore simulato")
        self.assertFalse(self.app.model_installing)
        self.assertTrue(any("worker log" in message for _, message in self.app.log_history))
        self.assertEqual(len(self.page.dialogs), 1)

    def test_device_options_are_updated_without_legacy_dropdown_api(self):
        self.app._device_changed(
            SimpleNamespace(control=SimpleNamespace(value="Solo CPU"))
        )
        self.assertEqual(self.app.device_mode_var.get(), "Solo CPU")
        self.assertEqual(
            [option.key for option in self.app.device_control.options],
            ["Automatica", "Solo CPU"],
        )

    def test_startup_splash_then_constructs_application(self):
        page = FakePage()
        asyncio.run(ChansonVivante.main(page))
        self.assertEqual(page.title, "ChansonVivante")
        self.assertEqual(page.window.width, 900)
        self.assertEqual(len(page.controls), 1)
        self.assertIsInstance(page.controls[0], ft.Column)
        self.assertEqual(len(page.tasks), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
