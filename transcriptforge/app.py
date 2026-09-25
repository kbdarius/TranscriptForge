import os
import queue
import re
import subprocess
import sys
import threading
import wave
import zipfile
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

# pyw.exe intentionally starts without console streams. Whisper and its
# progress helpers expect writable streams even when the GUI has no console.
if sys.stdout is None: sys.stdout = open(os.devnull, "w")
if sys.stderr is None: sys.stderr = open(os.devnull, "w")

from .controller import TranscriptionController
from .configuration import export_configuration, import_configuration
from .media import SUPPORTED_EXTENSIONS
from .models_cache import MODEL_NAMES, cache_dir, download_model, model_available
from .output import append_markdown_content
from .settings import FilenameTemplateSettings, MeetingOutputSettings, OutputLocationHistory, PreferencesSettings, RecordingFolderSettings, RecordingHistory, SampleRejectionStore
from .speakers import SpeakerProfileStore, remove_review_sample
from .speaker_names import similar_speaker_names, speaker_name_choices, speaker_name_suggestions
from .outlook_calendar import meetings_on, today_meetings
from .version import __version__

DEFAULT_RECORDINGS_FOLDER = Path(r"C:\Users\dariusk\OneDrive - stryten.com\Recordings")
NO_MEETING_SELECTION = "No meeting selected - use current workflow"

class App(tk.Tk):
    def __init__(self, initial_input=None, auto_start=False, prompt_recording_folder=False, recording_folder=None, identify_speakers=False):
        super().__init__(); self.title(f"TranscriptForge v{__version__}"); self.geometry("950x680"); self.events = queue.Queue(); self.controller = None; self.speaker_review = None; self.speaker_review_analysis = None; self._recent_speaker_names = []; self.output_history = OutputLocationHistory(); self.recording_settings = RecordingFolderSettings(); self.meeting_output_settings = MeetingOutputSettings(); self.today_outlook_meetings = []; self.selected_outlook_meeting = None; self.outlook_loading = True; self.outlook_ready = False; self._outlook_fetch_started = False
        self._scheduled_meeting_dialog = None; self._scheduled_meeting_combo = None; self._scheduled_meeting_var = None; self._scheduled_meeting_status = None; self._scheduled_meetings = []
        self.input_var = tk.StringVar(); self.folder_var = tk.StringVar(); self.filename_var = tk.StringVar(); self.meeting_var = tk.StringVar(); self.model_var = tk.StringVar(value="small.en"); self.language_var = tk.StringVar(value="en"); self.expected_speakers_var = tk.StringVar(); self.status_var = tk.StringVar(value="Select an audio or video file.")
        self.filename_templates = FilenameTemplateSettings(); self._job_controls = []; self._build(); self._load_preferences(); self.identify_speakers.set(self.identify_speakers.get() or identify_speakers); self.model_var.trace_add("write", lambda *_: self._update_model_button()); self._update_model_button(); self.after(100, self._poll); self.after(150, lambda: self._startup(initial_input, auto_start, prompt_recording_folder, recording_folder)); self.after(250, self._load_today_outlook_meetings)
    def _window_title(self, label):
        return f"TranscriptForge v{__version__} - {label}"
    def _build(self):
        root = ttk.Frame(self, padding=12); root.pack(fill="both", expand=True); root.columnconfigure(1, weight=1)
        self._meeting_row(root, 0); self.input_entry = self._row(root, 1, "Input file", self.input_var, self._browse_input); self._folder_row(root, 2); self.filename_entry = self._row(root, 3, "Output filename", self.filename_var, None)
        ttk.Label(root, text="Whisper model").grid(row=4, column=0, sticky="w", pady=5); ttk.Combobox(root, textvariable=self.model_var, values=MODEL_NAMES, state="readonly").grid(row=4, column=1, sticky="ew", pady=5); self.download_button = ttk.Button(root, text="Download model", command=self._download); self.download_button.grid(row=4, column=2, padx=5); self.setup_button = ttk.Button(root, text="⚙", width=3, command=self._open_setup); self.setup_button.grid(row=1, column=3, padx=(8, 0)); self._job_controls.append(self.setup_button)
        self.retain = tk.BooleanVar(); self.include_timestamps = tk.BooleanVar(value=True); self.open_after = tk.BooleanVar(value=True); self.identify_speakers = tk.BooleanVar(value=False); self.rename_source = tk.BooleanVar(value=True)
        self.progress = ttk.Progressbar(root, mode="determinate"); self.progress.grid(row=5, column=0, columnspan=4, sticky="ew", pady=8); ttk.Label(root, textvariable=self.status_var).grid(row=6, column=0, columnspan=4, sticky="w")
        self.log = tk.Text(root, height=15, state="disabled", wrap="word"); self.log.grid(row=7, column=0, columnspan=4, sticky="nsew", pady=8); root.rowconfigure(7, weight=1)
        self.new_button = ttk.Button(root, text="New transcription", command=self._new_transcription); self.new_button.grid(row=8, column=0, sticky="w"); self.transcribe_button = ttk.Button(root, text="Transcribe", command=self._start, state="disabled"); self.transcribe_button.grid(row=8, column=1, sticky="e"); self.cancel_button = ttk.Button(root, text="Cancel", command=self._cancel, state="disabled"); self.cancel_button.grid(row=8, column=2, padx=5); self.append_button = ttk.Button(root, text="Add content", command=self._append_content, state="disabled"); self.append_button.grid(row=8, column=3, padx=5)

    def _meeting_row(self, parent, row):
        ttk.Label(parent, text="Today's Outlook meeting").grid(row=row, column=0, sticky="w", pady=5)
        self.meeting_combo = ttk.Combobox(parent, textvariable=self.meeting_var, state="disabled")
        self.meeting_combo.grid(row=row, column=1, sticky="ew", pady=5)
        self.meeting_combo.bind("<<ComboboxSelected>>", self._select_outlook_meeting)
        self.refresh_meetings_button = ttk.Button(parent, text="Refresh", command=self._refresh_outlook_meetings)
        self.refresh_meetings_button.grid(row=row, column=2, padx=5)
        self._job_controls.extend([self.meeting_combo, self.refresh_meetings_button])
    def _row(self, parent, row, label, variable, command):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=5); entry = ttk.Entry(parent, textvariable=variable); entry.grid(row=row, column=1, sticky="ew", pady=5)
        if command:
            button = ttk.Button(parent, text="Browse", command=command); button.grid(row=row, column=2, padx=5); self._job_controls.append(button)
            if label == "Input file":
                self.input_browse_button = button
        return entry
    def _folder_row(self, parent, row):
        ttk.Label(parent, text="Output folder").grid(row=row, column=0, sticky="w", pady=5); self.folder_combo = ttk.Combobox(parent, textvariable=self.folder_var, values=self.output_history.locations, state="normal"); self.folder_combo.grid(row=row, column=1, sticky="ew", pady=5); button = ttk.Button(parent, text="Browse", command=self._browse_folder); button.grid(row=row, column=2, padx=5); self._job_controls.append(button)

    def _load_today_outlook_meetings(self):
        if self._outlook_fetch_started:
            return
        self._outlook_fetch_started = True
        self.outlook_loading = True
        if getattr(self, "refresh_meetings_button", None):
            self.refresh_meetings_button.configure(state="disabled")
        self.meeting_var.set("Loading today's meetings…")

        def work():
            try:
                self.events.put(("outlook_meetings", today_meetings()))
            except Exception as exc:
                self.events.put(("outlook_error", str(exc)))

        threading.Thread(target=work, daemon=True).start()

    def _refresh_outlook_meetings(self):
        if self.outlook_loading:
            return
        self._outlook_fetch_started = False
        self._load_today_outlook_meetings()

    def _set_today_outlook_meetings(self, meetings):
        self.outlook_loading = False
        self.outlook_ready = True
        self.today_outlook_meetings = meetings
        values = [meeting.display for meeting in meetings]
        self.meeting_combo.configure(values=values, state="readonly")
        self.refresh_meetings_button.configure(state="normal")
        self.meeting_var.set("Select a meeting (optional)" if values else "No Outlook meetings today")

    def _select_outlook_meeting(self, _event=None):
        selected = next((meeting for meeting in self.today_outlook_meetings if meeting.display == self.meeting_var.get()), None)
        if selected is None:
            self.selected_outlook_meeting = None
            return
        try:
            self._reconcile_outlook_names(selected, self)
        except (OSError, ValueError, TypeError) as exc:
            messagebox.showerror(self._window_title("Could not save speaker-name decision"), str(exc), parent=self)
            return
        self.selected_outlook_meeting = selected
        self._apply_meeting_output(selected)
        self._write_log(f"Selected Outlook meeting: {selected.subject}. Its invitees will be used for speaker matching.")

    def _reconcile_outlook_names(self, meeting, parent):
        store = SpeakerProfileStore()
        preference_names = self._speaker_shortlist()
        for outlook_name in meeting.possible_speakers:
            candidates_by_key = {
                name.casefold(): name
                for name in (*store.profiles, *preference_names)
            }
            candidates = sorted(candidates_by_key.values(), key=str.casefold)
            for profile_name, _score in similar_speaker_names(outlook_name, candidates):
                if store.name_match_was_rejected(outlook_name, profile_name):
                    continue
                canonical_name = store.canonical_name(profile_name)
                if canonical_name.casefold() == outlook_name.casefold():
                    if canonical_name != outlook_name:
                        store.confirm_name_alias(profile_name, outlook_name)
                    break
                same_person = messagebox.askyesno(
                    self._window_title("Confirm speaker name"),
                    f"Outlook lists '{outlook_name}', which is similar to the existing name '{profile_name}'. "
                    f"Are these the same person?\n\n"
                    f"Yes will merge any saved profile under '{outlook_name}' and use Outlook's spelling in future speaker lists. "
                    "No will keep the names separate.",
                    parent=parent,
                )
                if same_person:
                    store.confirm_name_alias(profile_name, outlook_name)
                    break
                store.reject_name_match(outlook_name, profile_name)

    def _apply_meeting_output(self, meeting):
        saved = self.meeting_output_settings.get(meeting.subject)
        filename_base = saved["filename_base"] if saved else meeting.subject
        if saved:
            self.folder_var.set(saved["output_folder"])
        self.filename_var.set(f"{filename_base}-{self._meeting_date(meeting):%Y%m%d}.md")
        self.filename_templates.remember(filename_base)

    def _accept_speaker_name_selection(self, event, combo, combos, names, recent_names):
        values = list(combo.cget("values"))
        index = combo.current()
        if 0 <= index < len(values):
            combo.set(values[index])
        elif values and combo.get().casefold() not in {value.casefold() for value in values}:
            # Some Tk versions report current() as -1 for a mouse selection
            # made from a just-refreshed type-ahead list. Commit the visible
            # first suggestion instead of leaving the search text (for
            # example, "JO") in the field.
            combo.set(values[0])
        self._remember_speaker_name(combo, combos, names, recent_names)
        return "break"

    def _meeting_date(self, meeting):
        source = Path(self.input_var.get())
        if source.is_file():
            match = re.search(r"(?<!\d)(\d{8})[_-](\d{6})(?!\d)", source.stem)
            if match:
                try:
                    return datetime.strptime("".join(match.groups()), "%Y%m%d%H%M%S")
                except ValueError:
                    pass
            try:
                return datetime.fromtimestamp(source.stat().st_mtime)
            except OSError:
                return meeting.start
        return meeting.start

    def _remember_selected_meeting_output(self, meeting=None):
        meeting = meeting or self.selected_outlook_meeting
        folder = self.folder_var.get().strip()
        if meeting is None or not folder:
            return
        stem = Path(self.filename_var.get()).stem
        base = re.sub(r"[-_]\d{8}$", "", stem).strip(" -_") or meeting.subject
        self.meeting_output_settings.remember(meeting.subject, folder, base)
    def _configuration_preferences(self):
        return {"language": self.language_var.get(), "whisper_model": self.model_var.get(), "expected_speakers": self.expected_speakers_var.get(), "retain_wav": self.retain.get(), "include_timestamps": self.include_timestamps.get(), "open_after": self.open_after.get(), "identify_speakers": self.identify_speakers.get(), "rename_source": self.rename_source.get()}

    def _load_preferences(self):
        preferences = PreferencesSettings().values
        if isinstance(preferences.get("language"), str): self.language_var.set(preferences["language"])
        if preferences.get("whisper_model") in MODEL_NAMES: self.model_var.set(preferences["whisper_model"])
        if isinstance(preferences.get("expected_speakers"), str): self.expected_speakers_var.set(preferences["expected_speakers"])
        for key, variable in (("retain_wav", self.retain), ("include_timestamps", self.include_timestamps), ("open_after", self.open_after), ("identify_speakers", self.identify_speakers), ("rename_source", self.rename_source)):
            if isinstance(preferences.get(key), bool): variable.set(preferences[key])

    def _save_preferences(self):
        PreferencesSettings().save(self._configuration_preferences())
    def _export_configuration(self):
        path = filedialog.asksaveasfilename(title=self._window_title("Export configuration"), defaultextension=".tfconfig", filetypes=[("TranscriptForge configuration", "*.tfconfig"), ("All files", "*.*")])
        if not path:
            return
        try:
            export_configuration(Path(path), self._configuration_preferences(), self.filename_templates.names)
            self._write_log(f"Exported portable configuration: {path}")
            messagebox.showinfo(self._window_title("Configuration exported"), "Transfer this .tfconfig file to the other PC, then use Import configuration there.", parent=self)
        except (OSError, ValueError) as exc:
            messagebox.showerror(self._window_title("Could not export configuration"), str(exc), parent=self)
    def _import_configuration(self):
        path = filedialog.askopenfilename(title=self._window_title("Import configuration"), filetypes=[("TranscriptForge configuration", "*.tfconfig"), ("All files", "*.*")])
        if not path:
            return
        if not messagebox.askyesno(self._window_title("Import configuration"), "Import portable preferences and merge speaker training data?\n\nThis will not import recording folders, output-location history, transcription history, models, audio, or transcripts.", parent=self):
            return
        try:
            result = import_configuration(Path(path))
            preferences = result.get("preferences", {})
            if isinstance(preferences, dict):
                if isinstance(preferences.get("language"), str): self.language_var.set(preferences["language"])
                if preferences.get("whisper_model") in MODEL_NAMES: self.model_var.set(preferences["whisper_model"])
                if isinstance(preferences.get("expected_speakers"), str): self.expected_speakers_var.set(preferences["expected_speakers"])
                for key, variable in (("retain_wav", self.retain), ("include_timestamps", self.include_timestamps), ("open_after", self.open_after), ("identify_speakers", self.identify_speakers), ("rename_source", self.rename_source)):
                    if isinstance(preferences.get(key), bool): variable.set(preferences[key])
            self.filename_templates.load(); self._save_preferences()
            self._write_log(f"Imported configuration: {result.get('profiles', 0)} new voice samples and {result.get('rejections', 0)} sample decisions.")
            messagebox.showinfo(self._window_title("Configuration imported"), f"Imported {result.get('profiles', 0)} new voice samples and {result.get('rejections', 0)} sample decisions.\n\nThis PC's folder settings and histories were left unchanged.", parent=self)
        except (OSError, ValueError, zipfile.BadZipFile) as exc:
            messagebox.showerror(self._window_title("Could not import configuration"), str(exc), parent=self)
    def _open_setup(self):
        dialog = tk.Toplevel(self); dialog.title(self._window_title("Setup")); dialog.transient(self); dialog.grab_set(); dialog.resizable(False, False)
        frame = ttk.Frame(dialog, padding=14); frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Optional features", font=("TkDefaultFont", 10, "bold")).pack(anchor="w", pady=(0, 8))
        ttk.Label(frame, text="These settings apply to the next transcription.", wraplength=420).pack(anchor="w", pady=(0, 8))
        ttk.Label(frame, text="Language").pack(anchor="w"); ttk.Entry(frame, textvariable=self.language_var, width=12).pack(anchor="w", pady=(2, 8))
        ttk.Label(frame, text="Expected speakers (optional, comma-separated)").pack(anchor="w"); ttk.Entry(frame, textvariable=self.expected_speakers_var, width=42).pack(anchor="w", pady=(2, 8))
        ttk.Checkbutton(frame, text="Retain intermediate WAV", variable=self.retain).pack(anchor="w", pady=2)
        ttk.Checkbutton(frame, text="Include timestamped segments", variable=self.include_timestamps).pack(anchor="w", pady=2)
        ttk.Checkbutton(frame, text="Open transcript after completion", variable=self.open_after).pack(anchor="w", pady=2)
        ttk.Checkbutton(frame, text="Identify speakers locally", variable=self.identify_speakers).pack(anchor="w", pady=2)
        ttk.Checkbutton(frame, text="Rename media to match output", variable=self.rename_source).pack(anchor="w", pady=2)
        ttk.Label(frame, text="Common filename", font=("TkDefaultFont", 9, "bold")).pack(anchor="w", pady=(12, 2))
        ttk.Label(frame, text="Select or add a recurring meeting name. Use adds YYYYMMDD-Name.md to the output filename.", wraplength=420).pack(anchor="w")
        template_var = tk.StringVar(); template_combo = ttk.Combobox(frame, textvariable=template_var, values=self.filename_templates.names, width=42); template_combo.pack(fill="x", pady=(4, 4))
        template_controls = ttk.Frame(frame); template_controls.pack(fill="x")
        def add_template():
            self.filename_templates.remember(template_var.get()); template_combo.configure(values=self.filename_templates.names); template_var.set(template_var.get().strip())
        def use_template():
            name = " ".join(template_var.get().strip().split())
            if not name:
                return messagebox.showinfo(self._window_title("Common filename"), "Type or select a recurring meeting name first.")
            self.filename_templates.remember(name); template_combo.configure(values=self.filename_templates.names)
            source = Path(self.input_var.get())
            date = datetime.fromtimestamp(source.stat().st_mtime).strftime("%Y%m%d") if source.is_file() else datetime.now().strftime("%Y%m%d")
            self.filename_var.set(f"{name}-{date}.md")
            dialog.grab_release(); dialog.destroy()
        ttk.Button(template_controls, text="Add to list", command=add_template).pack(side="left"); ttk.Button(template_controls, text="Use for output filename", command=use_template).pack(side="left", padx=6)
        transfer = ttk.LabelFrame(frame, text="Transfer to another PC", padding=8); transfer.pack(fill="x", pady=(14, 0)); ttk.Label(transfer, text="Transfers preferences, filename templates, and speaker training data. Computer-specific paths and histories stay local.", wraplength=420).pack(anchor="w"); transfer_buttons = ttk.Frame(transfer); transfer_buttons.pack(fill="x", pady=(8, 0)); ttk.Button(transfer_buttons, text="Export configuration", command=self._export_configuration).pack(side="left"); ttk.Button(transfer_buttons, text="Import configuration", command=self._import_configuration).pack(side="left", padx=6)
        controls = ttk.Frame(frame); controls.pack(fill="x", pady=(14, 0)); ttk.Button(controls, text="Manage profiles", command=self._manage_profiles).pack(side="left"); ttk.Button(controls, text="View history", command=self._show_history).pack(side="left", padx=6)
        def close_setup():
            self._save_preferences(); dialog.grab_release(); dialog.destroy()
        ttk.Button(controls, text="Close", command=close_setup).pack(side="right")
    def _show_history(self):
        dialog = tk.Toplevel(self); dialog.title(self._window_title("Transcription history")); dialog.transient(self); dialog.geometry("1200x560"); dialog.minsize(800, 360)
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
                messagebox.showinfo(self._window_title("Transcript unavailable"), "The transcript file is no longer at the recorded location.")
        def open_selected_folder():
            record = selected_record(); path = Path(record.get("output_path", "")) if record else None
            if path and path.parent.is_dir():
                os.startfile(str(path.parent))
        def unignore_selected():
            record = selected_record()
            if not record or record.get("status") not in {"ignored", "pending"}:
                return messagebox.showinfo(self._window_title("Restore recording"), "Select an ignored or pending recording first.", parent=dialog)
            source = Path(record.get("original_path", ""))
            if not source.is_file():
                return messagebox.showinfo(self._window_title("Recording unavailable"), f"The original recording is not available:\n\n{source}", parent=dialog)
            RecordingHistory().update(source, "retry")
            self._write_log(f"Restored recording to scan queue: {source.name}")
            dialog.destroy()
            messagebox.showinfo(self._window_title("Recording restored"), f"{source.name} will be considered on the next scheduled scan.", parent=self)
        table.bind("<<TreeviewSelect>>", show_selection)
        buttons = ttk.Frame(dialog); buttons.pack(fill="x", padx=12, pady=(0, 10)); ttk.Button(buttons, text="Open transcript", command=open_selected_transcript).pack(side="left"); ttk.Button(buttons, text="Open folder", command=open_selected_folder).pack(side="left", padx=6); ttk.Button(buttons, text="Unignore / requeue", command=unignore_selected).pack(side="left", padx=6); ttk.Button(buttons, text="Close", command=dialog.destroy).pack(side="right")
    def _browse_input(self):
        configured = Path(self.recording_settings.folder) if self.recording_settings.folder else DEFAULT_RECORDINGS_FOLDER
        initialdir = configured if configured.is_dir() else Path.home()
        path = filedialog.askopenfilename(title=self._window_title("Choose input file"), initialdir=str(initialdir), filetypes=[("Media", " ".join(f"*{x}" for x in SUPPORTED_EXTENSIONS)), ("All files", "*.*")])
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
                    self.after(250, lambda: self._show_scheduled_choice(source))
    def _show_scheduled_choice(self, source: Path):
        dialog = tk.Toplevel(self); dialog.title(self._window_title("New recording found")); dialog.transient(self); dialog.grab_set(); dialog.resizable(False, False)
        frame = ttk.Frame(dialog, padding=14); frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="A new recording was found by the scheduled scan.", font=("TkDefaultFont", 10, "bold")).pack(anchor="w")
        ttk.Label(frame, text=str(source), wraplength=620).pack(anchor="w", pady=(8, 12))
        ttk.Label(frame, text="Choose what to do with this recording. Ignore keeps the audio and removes it from the scan queue. You can restore it later from Setup > View history.", wraplength=620).pack(anchor="w")
        ttk.Label(frame, text="Meeting (optional)").pack(anchor="w", pady=(12, 2))
        meeting_var = tk.StringVar(value=NO_MEETING_SELECTION)
        meeting_combo = ttk.Combobox(frame, textvariable=meeting_var, values=[NO_MEETING_SELECTION], state="readonly", width=72)
        meeting_combo.pack(fill="x")
        meeting_status = tk.StringVar(value="Loading Outlook meetings for this recording date...")
        ttk.Label(frame, textvariable=meeting_status, wraplength=620).pack(anchor="w", pady=(2, 8))
        ttk.Label(frame, text="Maximum expected speakers (soft limit, optional)").pack(anchor="w")
        speaker_limit_var = tk.StringVar()
        ttk.Entry(frame, textvariable=speaker_limit_var, width=8).pack(anchor="w", pady=(2, 0))
        ttk.Label(
            frame,
            text="Extra distinct voices stay available for review; the limit never merges or deletes them.",
            wraplength=620,
        ).pack(anchor="w", pady=(2, 0))
        self._scheduled_meeting_dialog = dialog
        self._scheduled_meeting_combo = meeting_combo
        self._scheduled_meeting_var = meeting_var
        self._scheduled_meeting_status = meeting_status
        self._scheduled_meetings = []

        def selected_meeting():
            return next((meeting for meeting in self._scheduled_meetings if meeting.display == meeting_var.get()), None)

        def update_limit(_event=None):
            meeting = selected_meeting()
            speaker_limit_var.set(str(len(meeting.possible_speakers)) if meeting and meeting.possible_speakers else "")

        meeting_combo.bind("<<ComboboxSelected>>", update_limit)

        def close():
            dialog.grab_release(); dialog.destroy()
            if self._scheduled_meeting_dialog is dialog:
                self._scheduled_meeting_dialog = None
                self._scheduled_meeting_combo = None
                self._scheduled_meeting_var = None
                self._scheduled_meeting_status = None
                self._scheduled_meetings = []

        def transcribe():
            meeting = selected_meeting()
            try:
                max_speakers = self._parse_speaker_limit(speaker_limit_var.get())
            except ValueError as exc:
                return messagebox.showerror(self._window_title("Invalid speaker limit"), str(exc), parent=dialog)
            if meeting is not None:
                try:
                    self._reconcile_outlook_names(meeting, dialog)
                except (OSError, ValueError, TypeError) as exc:
                    return messagebox.showerror(self._window_title("Could not save speaker-name decision"), str(exc), parent=dialog)
                self._apply_meeting_output(meeting)
            close()
            self._start(
                meeting_override=meeting,
                use_meeting_override=True,
                max_speakers=max_speakers,
            )

        def ignore():
            RecordingHistory().update(source, "ignored")
            self._write_log(f"Ignored recording: {source.name}")
            close(); self._new_transcription()
        def delete():
            if not messagebox.askyesno(self._window_title("Delete recording?"), f"Delete this recording permanently from the recording folder?\n\n{source}", parent=dialog):
                return
            try:
                source.unlink()
                RecordingHistory().update(source, "deleted")
                self._write_log(f"Deleted recording: {source.name}")
                close(); self._new_transcription()
            except OSError as exc:
                messagebox.showerror(self._window_title("Could not delete recording"), str(exc), parent=dialog)
        buttons = ttk.Frame(frame); buttons.pack(fill="x", pady=(16, 0))
        ttk.Button(buttons, text="Transcribe", command=transcribe).pack(side="left")
        ttk.Button(buttons, text="Ignore", command=ignore).pack(side="left", padx=8)
        ttk.Button(buttons, text="Delete", command=delete).pack(side="left")
        ttk.Button(buttons, text="Cancel", command=close).pack(side="right")
        dialog.protocol("WM_DELETE_WINDOW", close)
        recording_time = self._recording_datetime(source)
        self._load_scheduled_meetings(dialog, recording_time)

    @staticmethod
    def _recording_datetime(source: Path):
        match = re.search(r"(?<!\d)(\d{8})[_-](\d{6})(?!\d)", source.stem)
        if match:
            try:
                return datetime.strptime("".join(match.groups()), "%Y%m%d%H%M%S")
            except ValueError:
                pass
        try:
            return datetime.fromtimestamp(source.stat().st_mtime)
        except OSError:
            return datetime.now()

    @staticmethod
    def _parse_speaker_limit(value):
        clean = str(value).strip()
        if not clean:
            return None
        if not clean.isdecimal() or int(clean) < 1:
            raise ValueError("Enter a positive whole number, or leave the field empty for no limit.")
        return int(clean)

    def _load_scheduled_meetings(self, dialog, recording_time):
        def work():
            try:
                meetings = meetings_on(recording_time)
            except Exception as exc:
                self.events.put(("scheduled_meeting_error", (dialog, str(exc))))
            else:
                self.events.put(("scheduled_meetings", (dialog, meetings)))

        threading.Thread(target=work, daemon=True).start()

    def _set_scheduled_meetings(self, dialog, meetings):
        if dialog is not self._scheduled_meeting_dialog or self._scheduled_meeting_combo is None:
            return
        try:
            if not dialog.winfo_exists():
                return
        except tk.TclError:
            return
        self._scheduled_meetings = meetings
        values = [NO_MEETING_SELECTION, *(meeting.display for meeting in meetings)]
        self._scheduled_meeting_combo.configure(values=values)
        if self._scheduled_meeting_status is not None:
            self._scheduled_meeting_status.set(
                f"{len(meetings)} Outlook meeting(s) found for the recording date."
                if meetings
                else "No Outlook meetings found for the recording date. You can still transcribe without one."
            )

    def _set_scheduled_meeting_error(self, dialog, error):
        if dialog is not self._scheduled_meeting_dialog or self._scheduled_meeting_combo is None:
            return
        try:
            if not dialog.winfo_exists():
                return
        except tk.TclError:
            return
        self._scheduled_meetings = []
        self._scheduled_meeting_combo.configure(values=[NO_MEETING_SELECTION])
        if self._scheduled_meeting_status is not None:
            self._scheduled_meeting_status.set(
                f"Could not load Outlook meetings: {error}. You can still transcribe without one."
            )
        self._write_log(f"Could not read Outlook meetings for the recording date: {error}")
    def _ask_for_recording_folder(self, missing: Path):
        message = "TranscriptForge could not find the saved recording folder.\n\n"
        if missing:
            message += f"Saved location:\n{missing}\n\n"
        message += "Choose the recording folder for this computer."
        messagebox.showinfo(self._window_title("Recording folder required"), message)
        selected = filedialog.askdirectory(title=self._window_title("Choose recording folder"), mustexist=True)
        if selected:
            self.recording_settings.set(selected)
            self._write_log(f"Recording folder set to: {selected}")
        else:
            self._write_log("No recording folder selected. Use Browse when choosing an input file.")
    def _browse_folder(self):
        path = filedialog.askdirectory(title=self._window_title("Choose output folder")); self.folder_var.set(path) if path else None
    def _remember_output_location(self, location: Path):
        self.output_history.remember(location); self.folder_combo.configure(values=self.output_history.locations); self.folder_var.set(str(location))
    def _write_log(self, text): self.log.configure(state="normal"); self.log.insert("end", text + "\n"); self.log.see("end"); self.log.configure(state="disabled")
    def _update_model_button(self):
        if not hasattr(self, "download_button"):
            return
        installed = model_available(self.model_var.get())
        self.download_button.configure(text="Model installed" if installed else "Download model", state="disabled" if installed else "normal")
    def _start(self, *, meeting_override=None, use_meeting_override=False, max_speakers=None):
        if self.outlook_loading and not use_meeting_override:
            return messagebox.showinfo(self._window_title("Outlook meetings still loading"), "Today's Outlook meetings are still loading. Please wait a moment, or use Refresh before starting transcription.", parent=self)
        if getattr(self, "awaiting_transcription", False):
            return self._confirm_transcription()
        meeting = meeting_override if use_meeting_override else self.selected_outlook_meeting
        expected_speakers = self._outlook_speaker_names(meeting) if meeting else self._speaker_shortlist() or None
        if meeting and expected_speakers and max_speakers is None and not use_meeting_override:
            max_speakers = len(expected_speakers)
        self._save_preferences()
        source = Path(self.input_var.get()); output = Path(self.folder_var.get()) / self.filename_var.get(); output = output.with_suffix(".md")
        if not source.is_file() or source.suffix.lower() not in SUPPORTED_EXTENSIONS: return messagebox.showerror(self._window_title("Invalid input"), "Choose an existing supported audio or video file.")
        if output.resolve() == source.resolve(): return messagebox.showerror(self._window_title("Invalid output"), "The output must not overwrite the input.")
        if output.exists() and not messagebox.askyesno(self._window_title("Overwrite?"), f"Replace {output.name}?"): return
        if not model_available(self.model_var.get()): return messagebox.showerror(self._window_title("Model unavailable"), "Download the selected model before transcribing.")
        if meeting is not None:
            self._remember_selected_meeting_output(meeting)
        rename_target = source.with_name(output.stem + source.suffix)
        self.rename_overwrite = False
        if self.rename_source.get() and rename_target.resolve() != source.resolve() and rename_target.exists():
            if not messagebox.askyesno(self._window_title("Replace existing media?"), f"Replace the existing media file?\n\n{rename_target}"): return
            self.rename_overwrite = True
        identify_speakers = self.identify_speakers.get() or meeting is not None or max_speakers is not None
        if identify_speakers and not self.identify_speakers.get():
            self._write_log("Speaker identification is enabled for this recording because a meeting or speaker limit was selected.")
        self.active_source = source; self.active_output = output; self.active_meeting = meeting; self._recent_speaker_names = []; self.controller = TranscriptionController(lambda k, v: self.events.put((k, v))); self._set_job_fields_enabled(False); self.transcribe_button.configure(state="disabled"); self.new_button.configure(state="disabled"); self.cancel_button.configure(state="normal"); self.progress["value"] = 0; self._write_log("Starting local transcription..."); self.controller.start(source, output, self.model_var.get(), self.language_var.get(), self.retain.get(), self.include_timestamps.get(), identify_speakers, self.rename_source.get(), self.rename_overwrite, expected_speakers, max_speakers, meeting is not None)

    @staticmethod
    def _outlook_speaker_names(meeting):
        store = SpeakerProfileStore()
        names = {}
        for name in meeting.possible_speakers:
            if name.strip():
                canonical = store.canonical_name(name)
                names.setdefault(canonical.casefold(), canonical)
        return sorted(names.values(), key=str.casefold)
    def _confirm_transcription(self):
        source = Path(self.input_var.get()); output = (Path(self.folder_var.get()) / self.filename_var.get()).with_suffix(".md")
        if not source.is_file() or source.suffix.lower() not in SUPPORTED_EXTENSIONS:
            return messagebox.showerror(self._window_title("Invalid input"), "Choose an existing supported audio or video file.")
        if output.resolve() == source.resolve():
            return messagebox.showerror(self._window_title("Invalid output"), "The output must not overwrite the input.")
        if output.exists() and not messagebox.askyesno(self._window_title("Overwrite?"), f"Replace {output.name}?"):
            return
        meeting = getattr(self, "active_meeting", None)
        if meeting is not None:
            self._remember_selected_meeting_output(meeting)
        rename_overwrite = False; rename_target = source.with_name(output.stem + source.suffix)
        if self.rename_source.get() and rename_target.resolve() != source.resolve() and rename_target.exists():
            if not messagebox.askyesno(self._window_title("Replace existing media?"), f"Replace the existing media file?\n\n{rename_target}"):
                return
            rename_overwrite = True
        self.active_source = source; self.active_output = output; self.awaiting_transcription = False; self._set_job_fields_enabled(False); self.transcribe_button.configure(state="disabled", text="Transcribe"); self.status_var.set("Starting transcription..."); self.controller.set_output(output, self.rename_source.get(), rename_overwrite); self.controller.continue_transcription()
    def _cancel(self):
        if self.controller: self.controller.cancel(); self.status_var.set("Cancellation requested...")
    def _speaker_shortlist(self):
        return [" ".join(value.strip().split()) for value in self.expected_speakers_var.get().replace(";", ",").split(",") if value.strip()]
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
            dialog = tk.Toplevel(self); dialog.title(self._window_title("Remove speaker sample")); dialog.transient(self); dialog.grab_set(); frame = ttk.Frame(dialog, padding=12); frame.pack(fill="both", expand=True)
            ttk.Label(frame, text="Why should this sample be removed?").pack(anchor="w")
            reason_var = tk.StringVar(value="Too noisy or unclear")
            reasons = ["Possible overlapping speakers", "Speakers changed too quickly", "Too noisy or unclear", "Wrong speaker cluster", "Mostly silence or audio artifact", "Duplicate sample", "Other"]
            ttk.Combobox(frame, textvariable=reason_var, values=reasons, state="readonly", width=34).pack(fill="x", pady=(4, 8))
            ttk.Label(frame, text="Optional note").pack(anchor="w"); note = tk.Text(frame, height=3, width=42); note.pack(fill="x", pady=(2, 8))
            def confirm():
                embedding = list(cluster.sample_embeddings[index]) if index < len(cluster.sample_embeddings) else []
                reason = reason_var.get(); removed = remove_review_sample(self.speaker_review_analysis, cluster, index)
                if embedding:
                    SampleRejectionStore().add(embedding, reason, note.get("1.0", "end"), str(getattr(self, "active_source", "")))
                dialog.grab_release(); dialog.destroy(); self._write_log(f"Removed sample from {cluster.identifier}: {removed[0]:.2f}s-{removed[1]:.2f}s ({reason})"); self._render_sample_controls(parent, self.speaker_review_source, cluster)
            buttons = ttk.Frame(frame); buttons.pack(fill="x"); ttk.Button(buttons, text="Cancel", command=lambda: (dialog.grab_release(), dialog.destroy())).pack(side="right", padx=4); ttk.Button(buttons, text="Remove sample", command=confirm).pack(side="right")
    def _update_speaker_name_suggestions(self, event, combo, names, recent_names):
        if event.keysym in {"Up", "Down", "Return", "Escape", "Tab"}:
            return
        suggestions = speaker_name_suggestions(names, combo.get(), recent_names)
        combo._tf_suggestions = suggestions
        combo._tf_suggestion_index = -1
        combo.configure(values=suggestions)
        if suggestions:
            combo.after_idle(lambda: combo.tk.call("ttk::combobox::Post", str(combo)))

    def _navigate_speaker_name_suggestions(self, event, combo, names, recent_names, combos):
        suggestions = getattr(combo, "_tf_suggestions", None)
        if not suggestions:
            suggestions = speaker_name_suggestions(names, combo.get(), recent_names)
            combo._tf_suggestions = suggestions
            combo.configure(values=suggestions)
        if event.keysym in {"Up", "Down"}:
            if not suggestions:
                return "break"
            index = getattr(combo, "_tf_suggestion_index", -1)
            if event.keysym == "Down":
                index = min(index + 1, len(suggestions) - 1)
            else:
                index = max(index - 1, 0)
            combo._tf_suggestion_index = index
            combo.set(suggestions[index])
            combo.selection_range(0, tk.END)
            return "break"
        if event.keysym == "Return":
            index = getattr(combo, "_tf_suggestion_index", -1)
            if suggestions and index >= 0:
                combo.set(suggestions[index])
            elif suggestions and combo.get().casefold() not in {name.casefold() for name in suggestions}:
                combo.set(suggestions[0])
            self._remember_speaker_name(combo, combos, names, recent_names)
            combo.tk.call("ttk::combobox::Unpost", str(combo))
            return "break"
        if event.keysym == "Escape":
            combo.tk.call("ttk::combobox::Unpost", str(combo))
            return "break"

    @staticmethod
    def _remember_speaker_name(combo, combos, names, recent_names):
        selected = " ".join(combo.get().split())
        if not selected:
            return
        recent_names[:] = [name for name in recent_names if name.casefold() != selected.casefold()]
        recent_names.insert(0, selected)
        choices = speaker_name_choices(names, recent_names)
        for name_combo in combos:
            name_combo.configure(values=choices)

    def _show_speaker_review(self, payload):
        analysis = payload["analysis"]
        clusters = payload.get("clusters", analysis.clusters)
        source = Path(payload["wav_path"])
        self.speaker_review_source = source
        self.speaker_review_analysis = analysis
        dialog = tk.Toplevel(self)
        self.speaker_review = dialog
        dialog.title(self._window_title(payload.get("title", "Identify speakers")))
        dialog.transient(self)
        dialog.grab_set()
        dialog.protocol("WM_DELETE_WINDOW", self._cancel_speaker_review)

        frame = ttk.Frame(dialog, padding=12)
        frame.pack(fill="both", expand=True)
        instructions = payload.get(
            "instructions",
            "Listen to each voice sample and confirm or edit the suggested name. "
            "Uncheck Learn when a labeled cluster should not train future recognition.",
        )
        overflow_count = sum(cluster.over_limit for cluster in clusters)
        if overflow_count and analysis.speaker_limit is not None:
            instructions += (
                f" {overflow_count} additional distinct voice group(s) exceed the soft limit of "
                f"{analysis.speaker_limit}; they are kept below for review, not merged or discarded."
            )
        ttk.Label(frame, text=instructions, wraplength=720).pack(anchor="w", pady=(0, 4))
        ttk.Label(
            frame,
            text="Type to filter names; use the arrow keys and Enter to select. "
            "Invitees are suggested first; type a guest name for a voice not on the list. Names selected in this review move to the top.",
        ).pack(anchor="w", pady=(0, 10))

        name_vars = {}
        learn_vars = {}
        name_combos = []
        recent_names = self._recent_speaker_names
        existing_names = sorted(set(payload.get("existing_names", [])), key=str.casefold)
        choices = speaker_name_choices(existing_names)
        ordered_clusters = (
            [cluster for cluster in clusters if not cluster.over_limit]
            + [cluster for cluster in clusters if cluster.over_limit]
        )
        overflow_heading_shown = False
        for cluster in ordered_clusters:
            if cluster.over_limit and not overflow_heading_shown:
                ttk.Separator(frame).pack(fill="x", pady=(8, 3))
                ttk.Label(
                    frame,
                    text="Additional distinct voices beyond the soft limit",
                ).pack(anchor="w", pady=(0, 3))
                overflow_heading_shown = True
            row = ttk.Frame(frame)
            row.pack(fill="x", pady=5)
            ttk.Label(row, text=cluster.identifier, width=14).pack(side="left")
            sample_controls = ttk.Frame(row)
            sample_controls.pack(side="left")
            self._render_sample_controls(sample_controls, source, cluster)

            suggestion = cluster.suggested_name or ""
            hint = f"  (suggested {suggestion}, {cluster.suggestion_score:.0%})" if suggestion and cluster.suggestion_score is not None else ""
            ttk.Label(row, text=hint).pack(side="left", padx=4)
            variable = tk.StringVar(value=suggestion)
            name_vars[cluster.identifier] = variable
            combo = ttk.Combobox(row, textvariable=variable, values=choices, width=24, state="normal")
            combo.pack(side="right", fill="x", expand=True)
            combo.bind(
                "<FocusIn>",
                lambda _event, widget=combo: widget.after_idle(
                    lambda: widget.selection_range(0, tk.END)
                ),
            )
            combo.bind(
                "<KeyRelease>",
                lambda event, widget=combo: self._update_speaker_name_suggestions(
                    event, widget, existing_names, recent_names
                ),
            )
            remember = lambda _event, widget=combo: self._remember_speaker_name(
                widget, name_combos, existing_names, recent_names
            )
            combo.bind(
                "<<ComboboxSelected>>",
                lambda event, widget=combo: self._accept_speaker_name_selection(
                    event, widget, name_combos, existing_names, recent_names
                ),
            )
            combo.bind(
                "<KeyPress>",
                lambda event, widget=combo: self._navigate_speaker_name_suggestions(
                    event, widget, existing_names, recent_names, name_combos
                ),
            )
            combo.bind(
                "<FocusOut>",
                lambda event, widget=combo, original=suggestion: (
                    self._remember_speaker_name(
                        widget, name_combos, existing_names, recent_names
                    )
                    if widget.get() != original
                    else None
                ),
            )
            name_combos.append(combo)

            learn = tk.BooleanVar(value=True)
            learn_vars[cluster.identifier] = learn
            ttk.Checkbutton(row, text="Learn", variable=learn).pack(side="right", padx=6)

        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=(12, 0))
        ttk.Button(buttons, text="Cancel", command=self._cancel_speaker_review).pack(side="right", padx=5)
        ttk.Button(
            buttons,
            text="Continue",
            command=lambda: self._finish_speaker_review(name_vars, learn_vars),
        ).pack(side="right")
    def _finish_speaker_review(self, name_vars, learn_vars):
        names = {identifier: variable.get() for identifier, variable in name_vars.items()}; learning = {identifier: variable.get() for identifier, variable in learn_vars.items()}; dialog = self.speaker_review; self.speaker_review = None
        if dialog: dialog.grab_release(); dialog.destroy()
        if self.controller: self.controller.set_speaker_names(names, learning)
    def _cancel_speaker_review(self):
        dialog = self.speaker_review; self.speaker_review = None
        if dialog: dialog.grab_release(); dialog.destroy()
        if self.controller: self.controller.cancel()
    def _manage_profiles(self):
        store = SpeakerProfileStore(); dialog = tk.Toplevel(self); dialog.title(self._window_title("Speaker profiles")); dialog.transient(self); dialog.grab_set(); frame = ttk.Frame(dialog, padding=12); frame.pack(fill="both", expand=True); ttk.Label(frame, text=f"Profiles are stored locally as voice embeddings in:\n{store.path}", wraplength=650).pack(anchor="w"); listing = tk.Listbox(frame, height=10, width=50); listing.pack(fill="both", expand=True, pady=8)
        for name in sorted(store.profiles): listing.insert("end", f"{name} ({len(store.profiles[name])} archived, {len(store.active_vectors(name))} active)")
        def remove_selected():
            selection = listing.curselection()
            if not selection: return
            name = sorted(store.profiles)[selection[0]]
            store.delete_profile(name)
            listing.delete(selection[0])
        controls = ttk.Frame(frame); controls.pack(fill="x"); ttk.Button(controls, text="Delete selected", command=remove_selected).pack(side="left"); ttk.Button(controls, text="Close", command=lambda: (dialog.grab_release(), dialog.destroy())).pack(side="right")
    def _poll(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "progress": self.progress["value"] = value * 100
                elif kind == "status": self.status_var.set(value)
                elif kind == "log": self._write_log(str(value))
                elif kind == "model_ready": self._update_model_button()
                elif kind == "outlook_meetings": self._set_today_outlook_meetings(value)
                elif kind == "outlook_error": self.outlook_loading = False; self.outlook_ready = True; self.meeting_combo.configure(values=(), state="disabled"); self.refresh_meetings_button.configure(state="normal"); self.meeting_var.set("Outlook calendar unavailable"); self._write_log(f"Could not read today's Outlook meetings: {value}")
                elif kind == "scheduled_meetings": self._set_scheduled_meetings(*value)
                elif kind == "scheduled_meeting_error": self._set_scheduled_meeting_error(*value)
                elif kind == "speaker_review": self._show_speaker_review(value)
                elif kind == "ready": self.awaiting_transcription = True; self._set_job_fields_enabled(True, include_input=False); self.transcribe_button.configure(state="normal", text="Start transcription"); self.status_var.set(str(value)); self._write_log(str(value))
                elif kind == "done": self.status_var.set("Completed"); self._write_log(f"Wrote {value}"); self._remember_output_location(Path(value).parent); self._record_history("completed", Path(value)); self._complete(); self.append_button.configure(state="normal"); self._open_output(value) if self.open_after.get() else None
                elif kind == "cancelled": self.status_var.set("Cancelled"); self._write_log(str(value)); self._record_history("cancelled"); self._reset(); self._update_model_button()
                elif kind == "error": self.status_var.set("Error"); self._write_log(str(value)); self._record_history("failed"); messagebox.showerror(self._window_title("Transcription failed"), str(value)); self._reset(); self._update_model_button()
        except queue.Empty: pass
        self.after(100, self._poll)
    def _set_job_fields_enabled(self, enabled, include_setup=True, include_input=True):
        state = "normal" if enabled else "disabled"
        if include_input:
            self.input_entry.configure(state=state)
        self.filename_entry.configure(state=state); self.folder_combo.configure(state=state)
        for control in self._job_controls:
            if (include_setup or control is not self.setup_button) and (include_input or control is not self.input_browse_button):
                control.configure(state=("readonly" if enabled and control is self.meeting_combo else state))
    def _reset(self): self.awaiting_transcription = False; self._set_job_fields_enabled(True); self.transcribe_button.configure(state="normal" if self.input_var.get() else "disabled", text="Transcribe"); self.new_button.configure(state="normal"); self.cancel_button.configure(state="disabled")
    def _complete(self): self.awaiting_transcription = False; self._set_job_fields_enabled(True); self.transcribe_button.configure(state="disabled", text="Transcribe"); self.new_button.configure(state="normal"); self.cancel_button.configure(state="disabled")
    def _record_history(self, status, output=None):
        source = getattr(self, "active_source", None)
        if source:
            try:
                final_media = source.with_name(output.stem + source.suffix) if output and self.rename_source.get() else None
                RecordingHistory().update(source, status, output, final_media)
            except OSError as exc:
                self._write_log(f"Could not update recording history: {exc}")
    def _new_transcription(self):
        self.input_var.set(""); self.folder_var.set(""); self.filename_var.set(""); self.meeting_var.set("Select a meeting (optional)" if self.today_outlook_meetings else "No Outlook meetings today"); self.selected_outlook_meeting = None; self.active_meeting = None; self.model_var.set("small.en"); self.language_var.set("en"); self.expected_speakers_var.set(""); self.retain.set(False); self.include_timestamps.set(True); self.open_after.set(True); self.identify_speakers.set(False); self.rename_source.set(True); self.awaiting_transcription = False; self.progress["value"] = 0; self.status_var.set("Select an audio or video file."); self.log.configure(state="normal"); self.log.delete("1.0", "end"); self.log.configure(state="disabled"); self.transcribe_button.configure(state="disabled", text="Transcribe"); self.append_button.configure(state="disabled")
    def _append_content(self):
        path = getattr(self, "active_output", None)
        if not path or not Path(path).is_file():
            return messagebox.showerror(self._window_title("Transcript unavailable"), "Complete a transcription before adding content.")
        dialog = tk.Toplevel(self); dialog.title(self._window_title("Add content to transcript")); dialog.transient(self); dialog.grab_set(); frame = ttk.Frame(dialog, padding=12); frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Paste the message or other content to append to the transcript.").pack(anchor="w")
        ttk.Label(frame, text="Provided by").pack(anchor="w", pady=(10, 2))
        provider = tk.StringVar(value="Unknown"); choices = ["Unknown"] + sorted(SpeakerProfileStore().profiles); ttk.Combobox(frame, textvariable=provider, values=choices, width=36).pack(fill="x")
        ttk.Label(frame, text="Content").pack(anchor="w", pady=(10, 2)); content = tk.Text(frame, width=80, height=10, wrap="word"); content.pack(fill="both", expand=True)
        def save_content():
            try:
                append_markdown_content(Path(path), provider.get(), content.get("1.0", "end")); self._write_log(f"Appended content provided by {provider.get().strip() or 'Unknown'} to {Path(path).name}"); dialog.grab_release(); dialog.destroy()
            except (OSError, ValueError) as exc:
                messagebox.showerror(self._window_title("Could not add content"), str(exc), parent=dialog)
        buttons = ttk.Frame(frame); buttons.pack(fill="x", pady=(10, 0)); ttk.Button(buttons, text="Cancel", command=lambda: (dialog.grab_release(), dialog.destroy())).pack(side="right", padx=4); ttk.Button(buttons, text="Append content", command=save_content).pack(side="right")
    def _open_output(self, path):
        try: os.startfile(str(path))
        except OSError as exc: self._write_log(f"Could not open transcript automatically: {exc}")

def main():
    arguments = sys.argv[1:]
    def value_after(name):
        return arguments[arguments.index(name) + 1] if name in arguments and arguments.index(name) + 1 < len(arguments) else None
    app = App(value_after("--input"), "--auto-start" in arguments, "--prompt-recording-folder" in arguments, value_after("--recording-folder"), "--identify-speakers" in arguments)
    app.mainloop()
