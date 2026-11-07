"""Download, cache e verifica dei modelli Demucs."""
import contextlib
import gc
import os
import threading
from pathlib import Path
from urllib.parse import urlparse

import yaml

from . import runtime as _runtime
from .runtime import APP_MODELS_DIR, QueueLogStream


class ModelManagerMixin:
    def load_ai_dependencies_worker(self):
        """Importa le librerie pesanti senza bloccare il thread della GUI."""
        
        try:
            import soundfile as soundfile_module
            import torch as torch_module
            # Imposta limiti espliciti: il default può essere molto aggressivo sui PC
            # con molti core logici. Demucs non ha bisogno di centinaia di worker.
            torch_module.set_num_threads(4)
            try:
                torch_module.set_num_interop_threads(1)
            except RuntimeError:
                # PyTorch consente di impostarlo solo prima dell'avvio del pool.
                pass
            import demucs as demucs_module
            import demucs.api  # noqa: F401
            import imageio_ffmpeg

            ffmpeg_exe_path = Path(imageio_ffmpeg.get_ffmpeg_exe())
            ffmpeg_folder = str(ffmpeg_exe_path.parent.resolve())
            os.environ["PATH"] = ffmpeg_folder + os.pathsep + os.environ.get("PATH", "")

            _runtime.sf = soundfile_module
            _runtime.torch = torch_module
            _runtime.demucs = demucs_module
            self.ui_queue.put(("ai_ready",))
        except ImportError as error:
            self.ui_queue.put(("ai_error", f"Impossibile caricare il motore AI: {error}"))
        except Exception as error:
            self.ui_queue.put(("ai_error", f"Errore durante il caricamento del motore AI: {error}"))

    def model_cache_entries(self, model_name):
        """Restituisce i file effettivi richiesti dalla cache Hugging Face o legacy."""
        from huggingface_hub import try_to_load_from_cache
        from demucs.hf import DEFAULT_NAMESPACE, hf_repo_name

        namespace = DEFAULT_NAMESPACE
        model_id = model_name
        if "/" in model_name:
            namespace, model_id = model_name.split("/", 1)
        repo_id = f"{namespace}/{hf_repo_name(model_id)}"
        yaml_name = f"{model_id}.yaml"
        cached_yaml = try_to_load_from_cache(repo_id, yaml_name)

        # Demucs 4.1 prova prima Hugging Face: i pesi sono file safetensors.
        if isinstance(cached_yaml, str) and Path(cached_yaml).is_file():
            with open(cached_yaml, "r", encoding="utf-8") as file:
                model_bag = yaml.safe_load(file) or {}
            entries = [(f"{repo_id}/{yaml_name}", Path(cached_yaml))]
            for signature in model_bag.get("models", []):
                filename = f"{signature}.safetensors"
                cached_file = try_to_load_from_cache(repo_id, filename)
                path = (
                    Path(cached_file)
                    if isinstance(cached_file, str) and Path(cached_file).is_file()
                    else None
                )
                entries.append((f"{repo_id}/{filename}", path))
            return entries

        # Compatibilità con il repository remoto legacy (.th).
        remote_root = Path(_runtime.demucs.pretrained.REMOTE_ROOT)
        bag_file = remote_root / f"{model_name}.yaml"
        files_list = remote_root / "files.txt"
        if not bag_file.is_file() or not files_list.is_file():
            raise RuntimeError(
                f"Impossibile leggere i metadati Demucs per il modello '{model_name}'."
            )

        with bag_file.open("r", encoding="utf-8") as file:
            model_bag = yaml.safe_load(file) or {}
        remote_models = _runtime.demucs.pretrained._parse_remote_files(files_list)
        checkpoint_dir = Path(_runtime.torch.hub.get_dir()) / "checkpoints"
        entries = []
        for signature in model_bag.get("models", []):
            url = remote_models.get(signature)
            if not url:
                raise RuntimeError(
                    f"Checkpoint '{signature}' non trovato nei metadati Demucs."
                )
            filename = Path(urlparse(url).path).name
            entries.append((filename, checkpoint_dir / filename))
        return entries

    def is_model_installed(self, model_name):
        """Un modello è installato solo se sono presenti tutti i suoi file."""
        entries = self.model_cache_entries(model_name)
        return bool(entries) and all(
            path is not None and path.is_file() and path.stat().st_size > 0
            for _, path in entries
        )

    def start_model_installation(self, model_name):
        if getattr(self, "model_installing", False):
            return
        self.model_installing = True
        self.set_running_state(True)
        self.ui_queue.put(("status", f"Download del modello {model_name}...", "orange"))
        self.open_log_window()
        threading.Thread(
            target=self.install_model_worker, args=(model_name,), daemon=True
        ).start()

    def install_model_worker(self, model_name):
        """Scarica il modello e registra anche gli errori delle operazioni preliminari."""
        stdout_stream = QueueLogStream(self.ui_queue, "INFO")
        stderr_stream = QueueLogStream(self.ui_queue, "WARNING")
        try:
            # Tutte le operazioni, compresa la preparazione dei percorsi, devono
            # essere dentro il try: con pythonw.exe gli errori non appaiono in console.
            self.ui_queue.put(("log", "INFO", f"Avvio installazione modello: {model_name}"))
            self.ui_queue.put(("log", "INFO", f"Cartella modelli locale: {APP_MODELS_DIR}"))

            hf_cache_dir = Path(os.environ["HF_HOME"]) / "hub"
            checkpoint_dir = Path(_runtime.torch.hub.get_dir()) / "checkpoints"
            self.ui_queue.put(("log", "INFO", f"Cache Hugging Face: {hf_cache_dir}"))
            self.ui_queue.put(("log", "INFO", f"Cache checkpoint legacy: {checkpoint_dir}"))

            with contextlib.redirect_stdout(stdout_stream), contextlib.redirect_stderr(stderr_stream):
                self.ui_queue.put(("log", "INFO", "Download e caricamento del modello in corso..."))
                separator = _runtime.demucs.api.Separator(
                    model=model_name, device="cpu", shifts=0, overlap=0.25
                )
                del separator
                gc.collect()

            self.ui_queue.put(("log", "INFO", "Download terminato. Verifica dei file..."))
            cache_entries = self.model_cache_entries(model_name)
            for cache_name, cache_path in cache_entries:
                exists = (
                    cache_path is not None
                    and cache_path.is_file()
                    and cache_path.stat().st_size > 0
                )
                self.ui_queue.put((
                    "log",
                    "INFO" if exists else "ERROR",
                    f"{'OK' if exists else 'MANCANTE'}: {cache_name}"
                    + (f" -> {cache_path}" if cache_path is not None else ""),
                ))

            if not cache_entries or not self.is_model_installed(model_name):
                raise RuntimeError(
                    f"Il download di '{model_name}' è terminato, ma uno o più checkpoint "
                    "non risultano presenti nella cartella locale."
                )

            self.ui_queue.put((
                "done",
                f"Modello '{model_name}' installato e pronto.",
                None,
            ))
        except Exception as error:
            self.ui_queue.put((
                "error",
                f"Installazione di '{model_name}' non riuscita: "
                f"{type(error).__name__}: {error}",
            ))
        finally:
            try:
                stdout_stream.flush()
                stderr_stream.flush()
            except Exception as log_error:
                self.ui_queue.put((
                    "log",
                    "ERROR",
                    f"Errore durante la chiusura del log: {log_error}",
                ))
            self.ui_queue.put(("model_install_finished",))
            self.ui_queue.put(("finished",))

