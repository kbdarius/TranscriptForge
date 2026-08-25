import os
import queue
import subprocess
import threading
import wave
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .controller import TranscriptionController
from .media import SUPPORTED_EXTENSIONS
from .models_cache import MODEL_NAMES, cache_dir, download_model, model_available
from .settings import OutputLocationHistory
from .speakers import SpeakerProfileStore
from .version import __version__

DEFAULT_RECORDINGS_FOLDER = Path(r"C:\Users\dariusk\OneDrive - stryten.com\Recordings")

class App(tk.Tk):
    def __init__(self):
        super().__init__(); self.title(f"TranscriptForge v{__version__}"); self.geometry("900x650"); self.events = queue.Queue(); self.controller = None; self.speaker_review = None; self.output_history = OutputLocationHistory()
        self.input_var = tk.StringVar(); self.folder_var = tk.StringVar(); self.filename_var = tk.StringVar(); self.model_var = tk.StringVar(value="small.en"); self.language_var = tk.StringVar(value="en"); self.status_var = tk.StringVar(value="Select an audio or video file.")
        self._build(); self.model_var.trace_add("write", lambda *_: self._update_model_button()); self._update_model_button(); self.after(100, self._poll)
    def _build(self):
        root = ttk.Frame(self, padding=12); root.pack(fill="both", expand=True); root.columnconfigure(1, weight=1)
        self._row(root, 0, "Input file", self.input_var, self._browse_input); self._folder_row(root, 1); self._row(root, 2, "Output filename", self.filename_var, None)
        ttk.Label(root, text="Whisper model").grid(row=3, column=0, sticky="w", pady=5); ttk.Combobox(root, textvariable=self.model_var, values=MODEL_NAMES, state="readonly").grid(row=3, column=1, sticky="ew", pady=5); self.download_button = ttk.Button(root, text="Download model", command=self._download); self.download_button.grid(row=3, column=2, padx=5)
        advanced = ttk.LabelFrame(root, text="Advanced"); advanced.grid(row=4, column=0, columnspan=3, sticky="ew", pady=8); ttk.Label(advanced, text="Language").pack(side="left", padx=6); ttk.Entry(advanced, textvariable=self.language_var, width=8).pack(side="left"); self.retain = tk.BooleanVar(); ttk.Checkbutton(advanced, text="Retain intermediate WAV", variable=self.retain).pack(side="left", padx=10); self.include_timestamps = tk.BooleanVar(value=True); ttk.Checkbutton(advanced, text="Timestamped segments", variable=self.include_timestamps).pack(side="left", padx=10); self.open_after = tk.BooleanVar(value=True); ttk.Checkbutton(advanced, text="Open transcript", variable=self.open_after).pack(side="left", padx=10); self.identify_speakers = tk.BooleanVar(value=False); ttk.Checkbutton(advanced, text="Identify speakers locally", variable=self.identify_speakers).pack(side="left", padx=10); ttk.Button(advanced, text="Manage profiles", command=self._manage_profiles).pack(side="left", padx=6)
        self.progress = ttk.Progressbar(root, mode="determinate"); self.progress.grid(row=5, column=0, columnspan=3, sticky="ew", pady=8); ttk.Label(root, textvariable=self.status_var).grid(row=6, column=0, columnspan=3, sticky="w")
        self.log = tk.Text(root, height=15, state="disabled", wrap="word"); self.log.grid(row=7, column=0, columnspan=3, sticky="nsew", pady=8); root.rowconfigure(7, weight=1)
        self.transcribe_button = ttk.Button(root, text="Transcribe", command=self._start); self.transcribe_button.grid(row=8, column=1, sticky="e"); self.cancel_button = ttk.Button(root, text="Cancel", command=self._cancel, state="disabled"); self.cancel_button.grid(row=8, column=2, padx=5)
    def _row(self, parent, row, label, variable, command):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=5); ttk.Entry(parent, textvariable=variable).grid(row=row, column=1, sticky="ew", pady=5)
        if command: ttk.Button(parent, text="Browse", command=command).grid(row=row, column=2, padx=5)
    def _folder_row(self, parent, row):
        ttk.Label(parent, text="Output folder").grid(row=row, column=0, sticky="w", pady=5); self.folder_combo = ttk.Combobox(parent, textvariable=self.folder_var, values=self.output_history.locations, state="normal"); self.folder_combo.grid(row=row, column=1, sticky="ew", pady=5); ttk.Button(parent, text="Browse", command=self._browse_folder).grid(row=row, column=2, padx=5)
    def _browse_input(self):
        initialdir = DEFAULT_RECORDINGS_FOLDER if DEFAULT_RECORDINGS_FOLDER.is_dir() else Path.home()
        path = filedialog.askopenfilename(initialdir=str(initialdir), filetypes=[("Media", " ".join(f"*{x}" for x in SUPPORTED_EXTENSIONS)), ("All files", "*.*")])
        if path: self.input_var.set(path); p = Path(path); self.folder_var.set(str(p.parent)); self.filename_var.set(p.stem + ".md")
    def _browse_folder(self):
        path = filedialog.askdirectory(); self.folder_var.set(path) if path else None
    def _remember_output_location(self, location: Path):
        self.output_history.remember(location); self.folder_combo.configure(values=self.output_history.locations); self.folder_var.set(str(location))
    def _write_log(self, text): self.log.configure(state="normal"); self.log.insert("end", text + "\n"); self.log.see("end"); self.log.configure(state="disabled")
    def _update_model_button(self):
        if not hasattr(self, "download_button"):
            return
        installed = model_available(self.model_var.get())
        self.download_button.configure(text="Model installed" if installed else "Download model", state="disabled" if installed else "normal")
    def _start(self):
        source = Path(self.input_var.get()); output = Path(self.folder_var.get()) / self.filename_var.get(); output = output.with_suffix(".md")
        if not source.is_file() or source.suffix.lower() not in SUPPORTED_EXTENSIONS: return messagebox.showerror("Invalid input", "Choose an existing supported audio or video file.")
        if output.resolve() == source.resolve(): return messagebox.showerror("Invalid output", "The output must not overwrite the input.")
        if output.exists() and not messagebox.askyesno("Overwrite?", f"Replace {output.name}?"): return
        if not model_available(self.model_var.get()): return messagebox.showerror("Model unavailable", "Download the selected model before transcribing.")
        self.controller = TranscriptionController(lambda k, v: self.events.put((k, v))); self.transcribe_button.configure(state="disabled"); self.cancel_button.configure(state="normal"); self.progress["value"] = 0; self._write_log("Starting local transcription..."); self.controller.start(source, output, self.model_var.get(), self.language_var.get(), self.retain.get(), self.include_timestamps.get(), self.identify_speakers.get())
    def _cancel(self):
        if self.controller: self.controller.cancel(); self.status_var.set("Cancellation requested...")
    def _download(self):
        name = self.model_var.get(); self._write_log(f"Downloading {name} to {cache_dir()}...")
        self.download_button.configure(state="disabled", text="Downloading...")
        def work():
            try: download_model(name); self.events.put(("model_ready", name)); self.events.put(("log", f"Model {name} is ready."))
            except Exception as exc: self.events.put(("error", str(exc)))
        threading.Thread(target=work, daemon=True).start()
    def _write_sample(self, source: Path, start: float, end: float, target: Path) -> None:
        with wave.open(str(source), "rb") as reader:
            rate, channels, width = reader.getframerate(), reader.getnchannels(), reader.getsampwidth()
            reader.setpos(max(0, int(start * rate)))
            frames = reader.readframes(max(1, int((end - start) * rate)))
        with wave.open(str(target), "wb") as writer:
            writer.setnchannels(channels); writer.setsampwidth(width); writer.setframerate(rate); writer.writeframes(frames)
    def _play_sample(self, source: Path, cluster_id: str, sample: tuple[float, float]):
        try:
            import winsound
            target = source.parent / f"{cluster_id}-{int(sample[0] * 1000)}.wav"
            if not target.exists(): self._write_sample(source, sample[0], sample[1], target)
            winsound.PlaySound(str(target), winsound.SND_FILENAME | winsound.SND_ASYNC)
        except Exception as exc:
            self._write_log(f"Could not play speaker sample: {exc}")
    def _show_speaker_review(self, payload):
        analysis = payload["analysis"]; clusters = payload.get("clusters", analysis.clusters); source = Path(payload["wav_path"]); dialog = tk.Toplevel(self); self.speaker_review = dialog; dialog.title(payload.get("title", "Identify speakers")); dialog.transient(self); dialog.grab_set(); dialog.protocol("WM_DELETE_WINDOW", self._cancel_speaker_review)
        frame = ttk.Frame(dialog, padding=12); frame.pack(fill="both", expand=True); ttk.Label(frame, text=payload.get("instructions", "Listen to each voice sample and confirm or edit the suggested name."), wraplength=720).pack(anchor="w", pady=(0, 10)); name_vars = {}
        existing_names = sorted(set(payload.get("existing_names", [])))
        choices = [""] + existing_names + ["Unknown"]
        for cluster in clusters:
            row = ttk.Frame(frame); row.pack(fill="x", pady=5); ttk.Label(row, text=cluster.identifier, width=14).pack(side="left")
            for sample_number, sample in enumerate(cluster.samples, start=1): ttk.Button(row, text=f"Play {sample_number}", command=lambda c=cluster.identifier, s=sample: self._play_sample(source, c, s)).pack(side="left", padx=2)
            suggestion = cluster.suggested_name or ""; hint = f"  (suggested {suggestion}, {cluster.suggestion_score:.0%})" if suggestion and cluster.suggestion_score is not None else ""
            ttk.Label(row, text=hint).pack(side="left", padx=4); variable = tk.StringVar(value=suggestion); name_vars[cluster.identifier] = variable; ttk.Combobox(row, textvariable=variable, values=choices, width=24).pack(side="right", fill="x", expand=True)
        buttons = ttk.Frame(frame); buttons.pack(fill="x", pady=(12, 0)); ttk.Button(buttons, text="Cancel", command=self._cancel_speaker_review).pack(side="right", padx=5); ttk.Button(buttons, text="Continue", command=lambda: self._finish_speaker_review(name_vars)).pack(side="right")
    def _finish_speaker_review(self, name_vars):
        names = {identifier: variable.get() for identifier, variable in name_vars.items()}; dialog = self.speaker_review; self.speaker_review = None
        if dialog: dialog.grab_release(); dialog.destroy()
        if self.controller: self.controller.set_speaker_names(names)
    def _cancel_speaker_review(self):
        dialog = self.speaker_review; self.speaker_review = None
        if dialog: dialog.grab_release(); dialog.destroy()
        if self.controller: self.controller.cancel()
    def _manage_profiles(self):
        store = SpeakerProfileStore(); dialog = tk.Toplevel(self); dialog.title("Speaker profiles"); dialog.transient(self); dialog.grab_set(); frame = ttk.Frame(dialog, padding=12); frame.pack(fill="both", expand=True); ttk.Label(frame, text=f"Profiles are stored locally as voice embeddings in:\n{store.path}", wraplength=650).pack(anchor="w"); listing = tk.Listbox(frame, height=10, width=50); listing.pack(fill="both", expand=True, pady=8)
        for name in sorted(store.profiles): listing.insert("end", f"{name} ({len(store.profiles[name])} samples)")
        def remove_selected():
            selection = listing.curselection()
            if not selection: return
            name = sorted(store.profiles)[selection[0]]; del store.profiles[name]; store.save(); listing.delete(selection[0])
        controls = ttk.Frame(frame); controls.pack(fill="x"); ttk.Button(controls, text="Delete selected", command=remove_selected).pack(side="left"); ttk.Button(controls, text="Close", command=lambda: (dialog.grab_release(), dialog.destroy())).pack(side="right")
    def _poll(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "progress": self.progress["value"] = value * 100
                elif kind == "status": self.status_var.set(value)
                elif kind == "log": self._write_log(str(value))
                elif kind == "model_ready": self._update_model_button()
                elif kind == "speaker_review": self._show_speaker_review(value)
                elif kind == "done": self.status_var.set("Completed"); self._write_log(f"Wrote {value}"); self._remember_output_location(Path(value).parent); self._reset(); self._open_output(value) if self.open_after.get() else None
                elif kind == "cancelled": self.status_var.set("Cancelled"); self._write_log(str(value)); self._reset(); self._update_model_button()
                elif kind == "error": self.status_var.set("Error"); self._write_log(str(value)); messagebox.showerror("Transcription failed", str(value)); self._reset(); self._update_model_button()
        except queue.Empty: pass
        self.after(100, self._poll)
    def _reset(self): self.transcribe_button.configure(state="normal"); self.cancel_button.configure(state="disabled")
    def _open_output(self, path):
        try: os.startfile(str(path))
        except OSError as exc: self._write_log(f"Could not open transcript automatically: {exc}")

def main():
    App().mainloop()
