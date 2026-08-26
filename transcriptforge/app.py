import os
import queue
import subprocess
import sys
import threading
import wave
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

# pyw.exe intentionally starts without console streams. Whisper and its
# progress helpers expect writable streams even when the GUI has no console.
if sys.stdout is None: sys.stdout = open(os.devnull, "w")
if sys.stderr is None: sys.stderr = open(os.devnull, "w")

from .controller import TranscriptionController
from .media import SUPPORTED_EXTENSIONS
from .models_cache import MODEL_NAMES, cache_dir, download_model, model_available
from .settings import OutputLocationHistory, RecordingFolderSettings, RecordingHistory
from .speakers import SpeakerProfileStore, remove_review_sample
from .version import __version__

DEFAULT_RECORDINGS_FOLDER = Path(r"C:\Users\dariusk\OneDrive - stryten.com\Recordings")

class App(tk.Tk):
    def __init__(self, initial_input=None, auto_start=False, prompt_recording_folder=False, recording_folder=None, identify_speakers=False):
        super().__init__(); self.title(f"TranscriptForge v{__version__}"); self.geometry("900x650"); self.events = queue.Queue(); self.controller = None; self.speaker_review = None; self.speaker_review_analysis = None; self.output_history = OutputLocationHistory(); self.recording_settings = RecordingFolderSettings()
        self.input_var = tk.StringVar(); self.folder_var = tk.StringVar(); self.filename_var = tk.StringVar(); self.model_var = tk.StringVar(value="small.en"); self.language_var = tk.StringVar(value="en"); self.status_var = tk.StringVar(value="Select an audio or video file.")
        self._build(); self.identify_speakers.set(identify_speakers); self.model_var.trace_add("write", lambda *_: self._update_model_button()); self._update_model_button(); self.after(100, self._poll); self.after(150, lambda: self._startup(initial_input, auto_start, prompt_recording_folder, recording_folder))
    def _build(self):
        root = ttk.Frame(self, padding=12); root.pack(fill="both", expand=True); root.columnconfigure(1, weight=1)
        self._row(root, 0, "Input file", self.input_var, self._browse_input); self._folder_row(root, 1); self._row(root, 2, "Output filename", self.filename_var, None)
        ttk.Label(root, text="Whisper model").grid(row=3, column=0, sticky="w", pady=5); ttk.Combobox(root, textvariable=self.model_var, values=MODEL_NAMES, state="readonly").grid(row=3, column=1, sticky="ew", pady=5); self.download_button = ttk.Button(root, text="Download model", command=self._download); self.download_button.grid(row=3, column=2, padx=5); ttk.Button(root, text="⚙", width=3, command=self._open_setup).grid(row=0, column=3, padx=(8, 0))
        self.retain = tk.BooleanVar(); self.include_timestamps = tk.BooleanVar(value=True); self.open_after = tk.BooleanVar(value=True); self.identify_speakers = tk.BooleanVar(value=False); self.rename_source = tk.BooleanVar(value=True)
        self.progress = ttk.Progressbar(root, mode="determinate"); self.progress.grid(row=4, column=0, columnspan=4, sticky="ew", pady=8); ttk.Label(root, textvariable=self.status_var).grid(row=5, column=0, columnspan=4, sticky="w")
        self.log = tk.Text(root, height=15, state="disabled", wrap="word"); self.log.grid(row=6, column=0, columnspan=4, sticky="nsew", pady=8); root.rowconfigure(6, weight=1)
        self.new_button = ttk.Button(root, text="New transcription", command=self._new_transcription); self.new_button.grid(row=7, column=0, sticky="w"); self.transcribe_button = ttk.Button(root, text="Transcribe", command=self._start, state="disabled"); self.transcribe_button.grid(row=7, column=1, sticky="e"); self.cancel_button = ttk.Button(root, text="Cancel", command=self._cancel, state="disabled"); self.cancel_button.grid(row=7, column=2, padx=5)
    def _row(self, parent, row, label, variable, command):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=5); ttk.Entry(parent, textvariable=variable).grid(row=row, column=1, sticky="ew", pady=5)
        if command: ttk.Button(parent, text="Browse", command=command).grid(row=row, column=2, padx=5)
    def _folder_row(self, parent, row):
        ttk.Label(parent, text="Output folder").grid(row=row, column=0, sticky="w", pady=5); self.folder_combo = ttk.Combobox(parent, textvariable=self.folder_var, values=self.output_history.locations, state="normal"); self.folder_combo.grid(row=row, column=1, sticky="ew", pady=5); ttk.Button(parent, text="Browse", command=self._browse_folder).grid(row=row, column=2, padx=5)
    def _open_setup(self):
        dialog = tk.Toplevel(self); dialog.title("TranscriptForge Setup"); dialog.transient(self); dialog.grab_set(); dialog.resizable(False, False)
        frame = ttk.Frame(dialog, padding=14); frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Optional features", font=("TkDefaultFont", 10, "bold")).pack(anchor="w", pady=(0, 8))
        ttk.Label(frame, text="These settings apply to the next transcription.", wraplength=420).pack(anchor="w", pady=(0, 8))
        ttk.Label(frame, text="Language").pack(anchor="w"); ttk.Entry(frame, textvariable=self.language_var, width=12).pack(anchor="w", pady=(2, 8))
        ttk.Checkbutton(frame, text="Retain intermediate WAV", variable=self.retain).pack(anchor="w", pady=2)
        ttk.Checkbutton(frame, text="Include timestamped segments", variable=self.include_timestamps).pack(anchor="w", pady=2)
        ttk.Checkbutton(frame, text="Open transcript after completion", variable=self.open_after).pack(anchor="w", pady=2)
        ttk.Checkbutton(frame, text="Identify speakers locally", variable=self.identify_speakers).pack(anchor="w", pady=2)
        ttk.Checkbutton(frame, text="Rename media to match output", variable=self.rename_source).pack(anchor="w", pady=2)
        controls = ttk.Frame(frame); controls.pack(fill="x", pady=(14, 0)); ttk.Button(controls, text="Manage profiles", command=self._manage_profiles).pack(side="left"); ttk.Button(controls, text="View history", command=self._show_history).pack(side="left", padx=6); ttk.Button(controls, text="Close", command=lambda: (dialog.grab_release(), dialog.destroy())).pack(side="right")
    def _show_history(self):
        dialog = tk.Toplevel(self); dialog.title("Transcription history"); dialog.transient(self); dialog.geometry("1200x560"); dialog.minsize(800, 360)
        frame = ttk.Frame(dialog, padding=12); frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Completed and previous transcription attempts are stored locally on this PC.", wraplength=1100).pack(anchor="w", pady=(0, 8))
        columns = ("name", "status", "updated", "original", "media", "transcript")
        table = ttk.Treeview(frame, columns=columns, show="headings")
        headings = {"name": "File name", "status": "Status", "updated": "Updated", "original": "Original path", "media": "Final media path", "transcript": "Transcript path"}
        widths = {"name": 280, "status": 100, "updated": 185, "original": 360, "media": 360, "transcript": 360}
        for column in columns:
            table.heading(column, text=headings[column]); table.column(column, width=widths[column], anchor="w")
        y_scrollbar = ttk.Scrollbar(frame, orient="vertical", command=table.yview); x_scrollbar = ttk.Scrollbar(frame, orient="horizontal", command=table.xview); table.configure(yscrollcommand=y_scrollbar.set, xscrollcommand=x_scrollbar.set); table.pack(side="top", fill="both", expand=True); y_scrollbar.pack(side="right", fill="y"); x_scrollbar.pack(side="bottom", fill="x")
        records = sorted(RecordingHistory().records, key=lambda item: item.get("updated_at", ""), reverse=True)
        for record in records:
            original = record.get("original_path", "")
            table.insert("", "end", values=(Path(original).name if original else "(unknown)", record.get("status", ""), record.get("updated_at", ""), original, record.get("final_path", ""), record.get("output_path", "")))
        if not records:
            ttk.Label(frame, text="No transcription history yet.").pack(anchor="w", pady=8)
        selected_path = tk.StringVar(value="Select a row to see its full paths.")
        ttk.Label(dialog, textvariable=selected_path, anchor="w").pack(fill="x", padx=12, pady=(8, 4))
        def selected_record():
            selection = table.selection()
            if not selection:
                return None
            return records[table.index(selection[0])]
        def show_selection(_event=None):
            record = selected_record()
            if record:
                selected_path.set(f"Original: {record.get('original_path', '')}   |   Transcript: {record.get('output_path', '')}")
        def open_selected_transcript():
            record = selected_record(); path = Path(record.get("output_path", "")) if record else None
            if path and path.is_file():
                self._open_output(path)
            elif record:
                messagebox.showinfo("Transcript unavailable", "The transcript file is no longer at the recorded location.")
        def open_selected_folder():
            record = selected_record(); path = Path(record.get("output_path", "")) if record else None
            if path and path.parent.is_dir():
                os.startfile(str(path.parent))
        table.bind("<<TreeviewSelect>>", show_selection)
        buttons = ttk.Frame(dialog); buttons.pack(fill="x", padx=12, pady=(0, 10)); ttk.Button(buttons, text="Open transcript", command=open_selected_transcript).pack(side="left"); ttk.Button(buttons, text="Open folder", command=open_selected_folder).pack(side="left", padx=6); ttk.Button(buttons, text="Close", command=dialog.destroy).pack(side="right")
    def _browse_input(self):
        configured = Path(self.recording_settings.folder) if self.recording_settings.folder else DEFAULT_RECORDINGS_FOLDER
        initialdir = configured if configured.is_dir() else Path.home()
        path = filedialog.askopenfilename(initialdir=str(initialdir), filetypes=[("Media", " ".join(f"*{x}" for x in SUPPORTED_EXTENSIONS)), ("All files", "*.*")])
        if path: self.input_var.set(path); p = Path(path); self.folder_var.set(str(p.parent)); self.filename_var.set(p.stem + ".md"); self.transcribe_button.configure(state="normal")
    def _validate_saved_recording_folder(self):
        configured = Path(self.recording_settings.folder) if self.recording_settings.folder else DEFAULT_RECORDINGS_FOLDER
        if configured.is_dir():
            if not self.recording_settings.folder:
                self.recording_settings.set(configured)
            return
        self._ask_for_recording_folder(configured)
    def _startup(self, initial_input, auto_start, prompt_recording_folder, recording_folder):
        if recording_folder:
            self.recording_settings.set(recording_folder)
        if prompt_recording_folder or not (Path(self.recording_settings.folder).is_dir() if self.recording_settings.folder else DEFAULT_RECORDINGS_FOLDER.is_dir()):
            configured = Path(self.recording_settings.folder) if self.recording_settings.folder else DEFAULT_RECORDINGS_FOLDER
            self._ask_for_recording_folder(configured)
        if initial_input:
            source = Path(initial_input)
            if source.is_file():
                self.input_var.set(str(source)); self.folder_var.set(str(source.parent)); self.filename_var.set(source.stem + ".md"); self.transcribe_button.configure(state="normal")
                if auto_start:
                    self.after(250, self._start)
    def _ask_for_recording_folder(self, missing: Path):
        message = "TranscriptForge could not find the saved recording folder.\n\n"
        if missing:
            message += f"Saved location:\n{missing}\n\n"
        message += "Choose the recording folder for this computer."
        messagebox.showinfo("Recording folder required", message)
        selected = filedialog.askdirectory(title="Choose recording folder", mustexist=True)
        if selected:
            self.recording_settings.set(selected)
            self._write_log(f"Recording folder set to: {selected}")
        else:
            self._write_log("No recording folder selected. Use Browse when choosing an input file.")
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
        rename_target = output.with_suffix(source.suffix)
        self.rename_overwrite = False
        if self.rename_source.get() and rename_target.resolve() != source.resolve() and rename_target.exists():
            if not messagebox.askyesno("Replace existing media?", f"Replace the existing media file?\n\n{rename_target}"): return
            self.rename_overwrite = True
        self.active_source = source; self.active_output = output; self.controller = TranscriptionController(lambda k, v: self.events.put((k, v))); self.transcribe_button.configure(state="disabled"); self.new_button.configure(state="disabled"); self.cancel_button.configure(state="normal"); self.progress["value"] = 0; self._write_log("Starting local transcription..."); self.controller.start(source, output, self.model_var.get(), self.language_var.get(), self.retain.get(), self.include_timestamps.get(), self.identify_speakers.get(), self.rename_source.get(), self.rename_overwrite)
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
    def _render_sample_controls(self, parent, source: Path, cluster):
        for child in parent.winfo_children(): child.destroy()
        if not cluster.samples:
            ttk.Label(parent, text="No samples kept").pack(side="left", padx=4)
            return
        for index, sample in enumerate(list(cluster.samples)):
            sample_frame = ttk.Frame(parent); sample_frame.pack(side="left", padx=2)
            ttk.Button(sample_frame, text=f"Play {index + 1}", command=lambda c=cluster.identifier, s=sample: self._play_sample(source, c, s)).pack(side="left")
            ttk.Button(sample_frame, text="X", width=2, command=lambda i=index, c=cluster, p=parent: self._remove_speaker_sample(c, p, i)).pack(side="left", padx=(1, 0))
    def _remove_speaker_sample(self, cluster, parent, index: int):
        if index < len(cluster.samples):
            removed = remove_review_sample(self.speaker_review_analysis, cluster, index)
            self._write_log(f"Removed sample from {cluster.identifier}: {removed[0]:.2f}s-{removed[1]:.2f}s")
            self._render_sample_controls(parent, self.speaker_review_source, cluster)
    def _show_speaker_review(self, payload):
        analysis = payload["analysis"]; clusters = payload.get("clusters", analysis.clusters); source = Path(payload["wav_path"]); self.speaker_review_source = source; self.speaker_review_analysis = analysis; dialog = tk.Toplevel(self); self.speaker_review = dialog; dialog.title(payload.get("title", "Identify speakers")); dialog.transient(self); dialog.grab_set(); dialog.protocol("WM_DELETE_WINDOW", self._cancel_speaker_review)
        frame = ttk.Frame(dialog, padding=12); frame.pack(fill="both", expand=True); ttk.Label(frame, text=payload.get("instructions", "Listen to each voice sample and confirm or edit the suggested name."), wraplength=720).pack(anchor="w", pady=(0, 10)); name_vars = {}
        existing_names = sorted(set(payload.get("existing_names", [])))
        choices = [""] + existing_names + ["Unknown"]
        for cluster in clusters:
            row = ttk.Frame(frame); row.pack(fill="x", pady=5); ttk.Label(row, text=cluster.identifier, width=14).pack(side="left"); sample_controls = ttk.Frame(row); sample_controls.pack(side="left"); self._render_sample_controls(sample_controls, source, cluster)
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
                elif kind == "done": self.status_var.set("Completed"); self._write_log(f"Wrote {value}"); self._remember_output_location(Path(value).parent); self._record_history("completed", Path(value)); self._complete(); self._open_output(value) if self.open_after.get() else None
                elif kind == "cancelled": self.status_var.set("Cancelled"); self._write_log(str(value)); self._record_history("cancelled"); self._reset(); self._update_model_button()
                elif kind == "error": self.status_var.set("Error"); self._write_log(str(value)); self._record_history("failed"); messagebox.showerror("Transcription failed", str(value)); self._reset(); self._update_model_button()
        except queue.Empty: pass
        self.after(100, self._poll)
    def _reset(self): self.transcribe_button.configure(state="normal" if self.input_var.get() else "disabled"); self.new_button.configure(state="normal"); self.cancel_button.configure(state="disabled")
    def _complete(self): self.transcribe_button.configure(state="disabled"); self.new_button.configure(state="normal"); self.cancel_button.configure(state="disabled")
    def _record_history(self, status, output=None):
        source = getattr(self, "active_source", None)
        if source:
            try:
                final_media = output.with_suffix(source.suffix) if output and self.rename_source.get() else None
                RecordingHistory().update(source, status, output, final_media)
            except OSError as exc:
                self._write_log(f"Could not update recording history: {exc}")
    def _new_transcription(self):
        self.input_var.set(""); self.folder_var.set(""); self.filename_var.set(""); self.model_var.set("small.en"); self.language_var.set("en"); self.retain.set(False); self.include_timestamps.set(True); self.open_after.set(True); self.identify_speakers.set(False); self.rename_source.set(True); self.progress["value"] = 0; self.status_var.set("Select an audio or video file."); self.log.configure(state="normal"); self.log.delete("1.0", "end"); self.log.configure(state="disabled"); self.transcribe_button.configure(state="disabled")
    def _open_output(self, path):
        try: os.startfile(str(path))
        except OSError as exc: self._write_log(f"Could not open transcript automatically: {exc}")

def main():
    arguments = sys.argv[1:]
    def value_after(name):
        return arguments[arguments.index(name) + 1] if name in arguments and arguments.index(name) + 1 < len(arguments) else None
    app = App(value_after("--input"), "--auto-start" in arguments, "--prompt-recording-folder" in arguments, value_after("--recording-folder"), "--identify-speakers" in arguments)
    app.mainloop()
