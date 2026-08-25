import threading
from pathlib import Path

from .audio import read_wav
from .media import decode_to_wav, temporary_work_dir
from .models_cache import cache_dir, load_model
from .output import atomic_write, render_markdown
from .speakers import SpeakerProfileStore, analyze_speakers, apply_speaker_names, refine_unresolved_clusters, save_confirmed_profiles
from .transcription import transcribe_samples

class TranscriptionController:
    def __init__(self, callback=None):
        self.callback = callback or (lambda kind, value: None); self.cancel_event = threading.Event(); self.review_event = threading.Event(); self.speaker_names = {}; self.thread = None
    def cancel(self): self.cancel_event.set(); self.review_event.set()
    def set_speaker_names(self, names: dict[str, str]): self.speaker_names = dict(names); self.review_event.set()
    def start(self, source: Path, output: Path, model_name: str, language="en", retain_wav=False, include_timestamps=True, identify_speakers=False):
        self.cancel_event.clear(); self.review_event.clear(); self.speaker_names = {}; self.thread = threading.Thread(target=self._run, args=(source, output, model_name, language, retain_wav, include_timestamps, identify_speakers), daemon=True); self.thread.start()
    def _emit(self, kind, value=None): self.callback(kind, value)
    def _run(self, source, output, model_name, language, retain_wav, include_timestamps, identify_speakers):
        try:
            with temporary_work_dir() as temp:
                wav = decode_to_wav(source, Path(temp)); self._emit("status", "Decoded audio")
                samples, rate = read_wav(wav)
                analysis = None
                if identify_speakers:
                    self._emit("status", "Analyzing local speaker voices")
                    analysis = analyze_speakers(samples, rate, self.cancel_event, lambda x: self._emit("log", x), lambda x: self._emit("progress", x * .2))
                    if analysis.clusters:
                        profile_store = SpeakerProfileStore()
                        self.review_event.clear()
                        self._emit("speaker_review", {"wav_path": str(wav), "analysis": analysis, "clusters": analysis.clusters, "existing_names": sorted(profile_store.profiles), "title": "Identify speakers - first pass", "instructions": "Confirm the obvious voices. Blank entries will be rechecked against the confirmed profiles before transcription starts."})
                        while not self.review_event.wait(.2):
                            if self.cancel_event.is_set():
                                raise InterruptedError("Speaker review cancelled")
                        if self.cancel_event.is_set():
                            raise InterruptedError("Speaker review cancelled")
                        first_pass_names = dict(self.speaker_names)
                        profile_store = save_confirmed_profiles(analysis, first_pass_names, profile_store)
                        final_names, unresolved, profile_store = refine_unresolved_clusters(analysis, first_pass_names, profile_store)
                        confirmed_ids = {identifier for identifier, value in first_pass_names.items() if value.strip()}
                        auto_count = sum(1 for identifier, value in final_names.items() if identifier not in confirmed_ids and value.strip())
                        if auto_count:
                            self._emit("log", f"Automatically matched {auto_count} additional speaker cluster(s) from confirmed profiles.")
                        if unresolved:
                            self.review_event.clear()
                            self._emit("speaker_review", {"wav_path": str(wav), "analysis": analysis, "clusters": unresolved, "existing_names": sorted(profile_store.profiles), "title": "Identify remaining speakers", "instructions": "These are the remaining uncertain voices. Select an existing name, type a new name, or choose Unknown."})
                            while not self.review_event.wait(.2):
                                if self.cancel_event.is_set():
                                    raise InterruptedError("Speaker review cancelled")
                            if self.cancel_event.is_set():
                                raise InterruptedError("Speaker review cancelled")
                            second_pass_names = dict(self.speaker_names)
                            final_names.update(second_pass_names)
                            save_confirmed_profiles(analysis, second_pass_names, profile_store)
                        self.speaker_names = final_names
                    else:
                        self._emit("log", "No distinct voice samples were found; continuing without speaker labels.")
                self._emit("status", "Loading local Whisper model")
                model = load_model(model_name, cache_dir())
                segments, stats = transcribe_samples(samples, rate, model, language, self.cancel_event, lambda x: self._emit("log", x), lambda x: self._emit("progress", .2 + x * .8 if identify_speakers else x))
                if self.cancel_event.is_set(): raise InterruptedError("Transcription cancelled")
                if analysis and analysis.clusters:
                    apply_speaker_names(segments, analysis, self.speaker_names, save_profiles=False)
                atomic_write(output, render_markdown(source, model_name, language, len(samples) / rate, segments, stats, cache_dir(), include_timestamps))
                if retain_wav: retained = output.with_suffix(".decoded.wav"); retained.write_bytes(wav.read_bytes()); self._emit("log", f"Retained intermediate WAV: {retained}")
            self._emit("done", output)
        except InterruptedError as exc: self._emit("cancelled", str(exc))
        except Exception as exc: self._emit("error", str(exc))
