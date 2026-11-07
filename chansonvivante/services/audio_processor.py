"""Caricamento audio, separazione Demucs e gestione GPU/CPU."""
import contextlib
import gc
import inspect
import os
from pathlib import Path

from . import runtime as _runtime
from .runtime import (
    QueueLogStream,
    VRAM_RESERVE_GB,
    SEGMENT_RETRY_ORDER,
    available_cuda_memory,
    is_cuda_oom,
    segment_for_budget,
)


class AudioProcessingMixin:
    def choose_gpu_budget(self, settings):
        memory = available_cuda_memory()
        if memory is None:
            return None, "CUDA non disponibile o memoria GPU non rilevabile."

        free_gb, total_gb = memory
        reserve = max(VRAM_RESERVE_GB, total_gb * 0.12)
        usable_gb = max(0.0, free_gb - reserve)

        if settings["device_mode"] == "Solo CPU":
            return None, "Modalità CPU selezionata."

        if settings["device_mode"] == "Manuale":
            target = min(settings["budget_gb"], usable_gb)
            if target < 1.0:
                return None, (
                    f"VRAM libera insufficiente: {free_gb:.1f} GB. "
                    "Passaggio alla CPU per evitare un avvio destinato a fallire."
                )
            return target, (
                f"Budget richiesto {settings['budget_gb']:.1f} GB; "
                f"budget GPU effettivo stimato {target:.1f} GB."
            )

        if usable_gb < 1.0:
            return None, (
                f"Solo {free_gb:.1f} GB di VRAM libera: uso della CPU."
            )
        target = min(usable_gb, max(1.0, total_gb * 0.65))
        return target, (
            f"Gestione automatica: {free_gb:.1f} GB liberi, "
            f"budget GPU stimato {target:.1f} GB."
        )

    def separate_with_gpu(self, audio_tensor, sample_rate, settings, budget_gb):
        initial_segment = segment_for_budget(budget_gb)
        try:
            supports_segment = "segment" in inspect.signature(_runtime.demucs.api.Separator).parameters
        except (TypeError, ValueError):
            supports_segment = False

        if not supports_segment:
            # Versioni Demucs meno recenti possono non esporre il parametro segment.
            # In quel caso evitiamo un TypeError e tentiamo una sola esecuzione standard.
            attempts = [None]
        elif initial_segment is None:
            attempts = SEGMENT_RETRY_ORDER
        else:
            attempts = [initial_segment] + [
                segment for segment in SEGMENT_RETRY_ORDER
                if segment is not None and segment < initial_segment
            ]

        last_oom_message = None
        for segment in attempts:
            try:
                self.ui_queue.put((
                    "status",
                    "Separazione su GPU" + (
                        f" · segmenti da {segment:g} s" if segment else " · segmentazione predefinita"
                    ),
                    "green",
                ))
                separator_kwargs = {
                    "model": settings["model"],
                    "device": "cuda",
                    "shifts": settings["shifts"],
                    "overlap": 0.25,
                }
                if segment is not None and supports_segment:
                    separator_kwargs["segment"] = segment
                separator = _runtime.demucs.api.Separator(**separator_kwargs)
                origin, separated = separator.separate_tensor(audio_tensor, sample_rate)
                return separator, origin, separated
            except Exception as error:
                if not is_cuda_oom(error):
                    raise
                last_oom_message = str(error)
                # Rimuove i riferimenti del traceback a tensori/modelli CUDA prima del retry.
                try:
                    error.__traceback__ = None
                except Exception:
                    pass
                self.ui_queue.put((
                    "status",
                    "Memoria GPU esaurita: riduco i segmenti e riprovo...",
                    "orange",
                ))
                try:
                    del separator
                except UnboundLocalError:
                    pass
                gc.collect()
                try:
                    _runtime.torch.cuda.empty_cache()
                except Exception:
                    pass

        raise RuntimeError(last_oom_message or "CUDA out of memory: memoria GPU insufficiente.")

    def run_demucs_api(self, settings):
        """Cattura i messaggi stdout/stderr di Demucs e delle librerie usate."""
        self.ui_queue.put(("log", "INFO", "Avvio elaborazione Demucs."))
        stdout_stream = QueueLogStream(self.ui_queue, "INFO")
        stderr_stream = QueueLogStream(self.ui_queue, "WARNING")
        try:
            with contextlib.redirect_stdout(stdout_stream), contextlib.redirect_stderr(stderr_stream):
                self._run_demucs_api_impl(settings)
        finally:
            stdout_stream.flush()
            stderr_stream.flush()

    def _run_demucs_api_impl(self, settings):
        try:
            input_path = Path(settings["input_path"]).resolve()
            out_dir = Path(settings["output_dir"]).resolve()
            fmt = settings["format"]

            self.ui_queue.put(("status", "Caricamento file audio...", "orange"))
            data, sample_rate = _runtime.sf.read(
                str(input_path), dtype="float32", always_2d=True
            )
            audio_tensor = _runtime.torch.from_numpy(data).t().contiguous()

            budget_gb, budget_message = self.choose_gpu_budget(settings)
            self.ui_queue.put(("status", budget_message, "orange"))

            separator = None
            if budget_gb is not None:
                try:
                    separator, origin, separated = self.separate_with_gpu(
                        audio_tensor, sample_rate, settings, budget_gb
                    )
                except Exception as error:
                    if not is_cuda_oom(error):
                        raise
                    gc.collect()
                    try:
                        _runtime.torch.cuda.empty_cache()
                    except Exception:
                        pass
                    self.ui_queue.put((
                        "status",
                        "La GPU non ha memoria sufficiente anche con segmenti ridotti: riprovo su CPU. Potrebbe richiedere molto più tempo.",
                        "orange",
                    ))
                    separator = _runtime.demucs.api.Separator(
                        model=settings["model"],
                        device="cpu",
                        shifts=settings["shifts"],
                        overlap=0.25,
                    )
                    origin, separated = separator.separate_tensor(audio_tensor, sample_rate)
            else:
                self.ui_queue.put(("status", "Separazione su CPU...", "orange"))
                separator = _runtime.demucs.api.Separator(
                    model=settings["model"],
                    device="cpu",
                    shifts=settings["shifts"],
                    overlap=0.25,
                )
                origin, separated = separator.separate_tensor(audio_tensor, sample_rate)

            self.ui_queue.put(("status", "Salvataggio dei file separati...", "orange"))
            is_24bit = settings["is_24bit"]
            kwargs = {
                "samplerate": separator.samplerate,
                "bitrate": 320 if fmt == "mp3" else None,
                "preset": 2 if fmt == "mp3" else None,
                "clip": "rescale",
                "as_float": False if is_24bit or fmt == "mp3" else True,
                "bits_per_sample": 24 if is_24bit and fmt in ("wav", "flac") else 16,
            }

            # Una cartella per brano direttamente nella destinazione scelta:
            # niente sottocartella aggiuntiva con il nome del modello.
            final_folder = out_dir / input_path.stem
            final_folder.mkdir(parents=True, exist_ok=True)

            if settings["two_stems"]:
                vocals = separated["vocals"]
                accompaniment = sum(
                    tensor for name, tensor in separated.items() if name != "vocals"
                )
                _runtime.demucs.api.save_audio(vocals, final_folder / f"vocals.{fmt}", **kwargs)
                _runtime.demucs.api.save_audio(
                    accompaniment, final_folder / f"no_vocals.{fmt}", **kwargs
                )
            else:
                for stem_name, stem_tensor in separated.items():
                    _runtime.demucs.api.save_audio(
                        stem_tensor, final_folder / f"{stem_name}.{fmt}", **kwargs
                    )

            if not final_folder.exists() or not any(final_folder.iterdir()):
                raise RuntimeError("I file non sono stati scritti nella cartella finale.")

            self.ui_queue.put((
                "done",
                "Completato con successo!",
                str(final_folder),
            ))
        except Exception as error:
            self.ui_queue.put(("error", str(error)))
        finally:
            self.ui_queue.put(("finished",))



