"""Guided Windows setup for TranscriptForge."""

from __future__ import annotations

import argparse
import importlib.metadata
import importlib.util
import os
import platform
import queue
import re
import shutil
import struct
import subprocess
import sys
import threading
import traceback
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Sequence
from urllib.parse import urlsplit

import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

from .models_cache import MODEL_NAMES
from .version import __version__

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REQUIREMENTS_PATH = PROJECT_ROOT / "requirements.txt"
BUILD_TOOLS_URL = "https://visualstudio.microsoft.com/visual-cpp-build-tools/"

_PACKAGE_DETAILS = {
    "openai-whisper": ("Local speech-to-text engine", True, "whisper"),
    "torch": ("Neural-network runtime for transcription", True, "torch"),
    "numpy": ("Audio samples and numerical processing", True, "numpy"),
    "imageio-ffmpeg": ("Bundled FFmpeg for media decoding", True, "imageio_ffmpeg"),
    "resemblyzer": ("Optional local speaker identification", False, "resemblyzer"),
    "pywin32": ("Optional Python COM client for Outlook Classic; PowerShell fallback is available", False, "win32com"),
    "soundcard": ("Optional live system-audio recording", False, "soundcard"),
}

_NETWORK_FAILURE_MARKERS = (
    "could not fetch url",
    "max retries exceeded",
    "sslerror",
    "certificate_verify_failed",
    "connectionerror",
    "proxyerror",
    "readtimeout",
    "connection timed out",
    "connection refused",
    "connection reset",
    "failed to establish a new connection",
    "getaddrinfo failed",
    "name or service not known",
    "temporary failure in name resolution",
    "403 forbidden",
    "407 proxy",
    "429 too many requests",
    "http error 401",
    "http error 403",
    "http error 407",
    "401 client error",
    "403 client error",
    "407 client error",
    "blocked by firewall",
    "connection blocked",
    "blocked by policy",
    "access denied by policy",
)

_URL_PATTERN = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
_URL_CREDENTIALS_PATTERN = re.compile(r"(https?://)[^/\s@]+@", re.IGNORECASE)
_HOST_PATTERN = re.compile(r"\bhost\s*=\s*['\"]?([a-z0-9.-]+)", re.IGNORECASE)
_REQUIREMENT_NAME_PATTERN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)")
_MSVC_ERROR_MARKERS = (
    "microsoft visual c++ 14.0 or greater is required",
    "microsoft visual c++",
    "unable to find vcvarsall",
)


@dataclass(frozen=True)
class PackageSpec:
    distribution: str
    requirement: str
    purpose: str
    required: bool
    import_name: str | None = None


@dataclass(frozen=True)
class SetupIssue:
    name: str
    purpose: str
    required: bool
    command: tuple[str, ...]
    output: str
    summary: str


@dataclass(frozen=True)
class InstallResult:
    spec: PackageSpec
    command: tuple[str, ...]
    return_code: int | None
    output: str
    summary: str

    @property
    def succeeded(self) -> bool:
        return self.return_code == 0

    def as_issue(self) -> SetupIssue:
        return SetupIssue(
            name=self.spec.distribution,
            purpose=self.spec.purpose,
            required=self.spec.required,
            command=self.command,
            output=self.output,
            summary=self.summary,
        )


def normalize_distribution_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_requirement_name(requirement: str) -> str:
    text = requirement.split(";", 1)[0].strip()
    match = _REQUIREMENT_NAME_PATTERN.match(text)
    if match is None:
        raise ValueError(f"Unsupported requirement entry: {requirement}")
    return match.group(1)


def load_package_specs(path: Path = REQUIREMENTS_PATH) -> tuple[PackageSpec, ...]:
    specs = []
    seen = set()
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        name = parse_requirement_name(line)
        normalized = normalize_distribution_name(name)
        if normalized in seen:
            raise ValueError(f"Duplicate package requirement: {name}")
        seen.add(normalized)
        purpose, required, import_name = _PACKAGE_DETAILS.get(
            normalized,
            ("Python package declared by the project", True, None),
        )
        specs.append(PackageSpec(name, line, purpose, required, import_name))
    if not specs:
        raise ValueError(f"No package requirements were found in {path}")
    return tuple(specs)


def installed_version(distribution: str) -> str | None:
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return None


def console_python_executable(executable: str | None = None) -> str:
    current = Path(executable or sys.executable)
    if current.name.lower() == "pythonw.exe":
        console_python = current.with_name("python.exe")
        if console_python.is_file():
            return str(console_python)
    return str(current)


def use_user_site(prefix: str = sys.prefix, base_prefix: str = sys.base_prefix) -> bool:
    return prefix == base_prefix


def build_pip_install_command(
    python_executable: str,
    requirement: str,
    install_to_user_site: bool,
    force_reinstall: bool = False,
    upgrade: bool = False,
) -> tuple[str, ...]:
    command = [
        python_executable,
        "-m",
        "pip",
        "install",
        "--no-cache-dir",
        "--disable-pip-version-check",
        "--progress-bar",
        "off",
    ]
    if upgrade:
        command.append("--upgrade")
    if install_to_user_site:
        command.append("--user")
    if force_reinstall:
        command.append("--force-reinstall")
    command.append(requirement)
    return tuple(command)


def classify_install_failure(name: str, output: str) -> str:
    text = output.lower()
    if any(marker in text for marker in _MSVC_ERROR_MARKERS):
        if "webrtcvad" in text:
            return (
                "The native webrtcvad dependency could not be compiled because "
                "Microsoft C++ Build Tools (MSVC 14 or later) are missing or unavailable. "
                "This is a local compiler requirement, not a network block."
            )
        return (
            f"{name} or one of its native dependencies could not be compiled because Microsoft C++ Build Tools "
            "(MSVC 14 or later) are missing or unavailable."
        )
    if any(marker in text for marker in _NETWORK_FAILURE_MARKERS):
        return "Package download or network access failed. Ask IT to review the listed executable and hosts."
    if "access is denied" in text or "access denied" in text or "permissionerror" in text or "winerror 5" in text:
        return "Windows denied access while installing the package. Check the account permissions or endpoint policy."
    if "no matching distribution found" in text:
        return "Pip could not find a compatible package release for this Python environment."
    useful_lines = [line.strip() for line in output.splitlines() if line.strip()]
    if useful_lines:
        return _URL_CREDENTIALS_PATTERN.sub(r"\1[credentials-redacted]@", useful_lines[-1])[:300]
    return "The installer failed without returning diagnostic output."


def extract_hosts(output: str) -> tuple[str, ...]:
    hosts = set()
    for match in _URL_PATTERN.finditer(output):
        raw_url = match.group(0).rstrip(".,;:)]}")
        host = urlsplit(raw_url).hostname
        if host:
            hosts.add(host.lower())
    for match in _HOST_PATTERN.finditer(output):
        hosts.add(match.group(1).lower())
    return tuple(sorted(hosts))


def make_support_report(
    issues: Iterable[SetupIssue],
    python_executable: str,
    build_tools_found: bool,
    app_version: str = __version__,
) -> str:
    issue_list = tuple(issues)
    lines = [
        f"Software: TranscriptForge setup, version {app_version}",
        f"Operating system: {platform.platform()}",
        f"Python version: {sys.version.split()[0]}",
        f"Python executable: {python_executable}",
        (
            "Microsoft C++ Build Tools: detected"
            if build_tools_found
            else "Microsoft C++ Build Tools: not detected (conditional prerequisite)"
        ),
        "Package/model downloads are started by this Python executable.",
    ]
    if not issue_list:
        lines.append("No failed setup steps have been recorded.")
    all_hosts = set()
    has_msvc_failure = False
    package_network_without_host = False
    for issue in issue_list:
        status = "required" if issue.required else "optional feature"
        lines.extend(
            [
                "",
                f"Failed item: {issue.name} ({status})",
                f"Feature: {issue.purpose}",
                f"Reason: {issue.summary}",
                f"Command: {subprocess.list2cmdline(issue.command)}",
            ]
        )
        issue_hosts = extract_hosts(issue.output)
        all_hosts.update(issue_hosts)
        text = issue.output.lower()
        has_msvc_failure = has_msvc_failure or any(marker in text for marker in _MSVC_ERROR_MARKERS)
        network_failure = any(marker in text for marker in _NETWORK_FAILURE_MARKERS)
        is_pip_command = "-m" in issue.command and "pip" in issue.command
        package_network_without_host = (
            package_network_without_host or (network_failure and is_pip_command and not issue_hosts)
        )
    if package_network_without_host:
        all_hosts.update(("pypi.org", "files.pythonhosted.org"))
    if all_hosts:
        lines.extend(
            [
                "",
                "Hosts seen in the installer output:",
                *[f"- {host} (HTTPS)" for host in sorted(all_hosts)],
                f"Executable for IT to review: {python_executable}",
            ]
        )
    if has_msvc_failure:
        lines.extend(
            [
                "",
                "Microsoft C++ Build Tools:",
                "The MSVC x64/x86 compiler was not detected or a package build requested it.",
                "Ask IT about the Visual Studio Build Tools C++ workload (MSVC 14+ and a Windows SDK).",
                f"Official installer page: {BUILD_TOOLS_URL}",
            ]
        )
    lines.extend(
        [
            "",
            "This report contains setup diagnostics only. It does not include recordings, transcripts, or speaker profiles.",
        ]
    )
    return "\n".join(lines)


RunCommand = Callable[[Sequence[str], Callable[[str], None]], tuple[int, str]]
InstallEvent = Callable[[str, PackageSpec, object | None], None]


def run_install_sequence(
    packages: Sequence[PackageSpec],
    python_executable: str,
    install_to_user_site: bool,
    run_command: RunCommand,
    emit: InstallEvent,
    force_reinstall: frozenset[str] = frozenset(),
) -> tuple[InstallResult, ...]:
    results = []
    for spec in packages:
        key = normalize_distribution_name(spec.distribution)
        command = build_pip_install_command(
            python_executable,
            spec.requirement,
            install_to_user_site,
            key in force_reinstall,
        )
        emit("started", spec, None)
        try:
            return_code, output = run_command(
                command,
                lambda line: emit("output", spec, line),
            )
        except OSError as exc:
            return_code = None
            output = str(exc)
            emit("output", spec, output)
        summary = "" if return_code == 0 else classify_install_failure(spec.distribution, output)
        result = InstallResult(spec, command, return_code, output, summary)
        results.append(result)
        emit("result", spec, result)
    return tuple(results)


def run_import_check_sequence(
    packages: Sequence[PackageSpec],
    python_executable: str,
    run_command: RunCommand,
    emit: InstallEvent,
) -> tuple[InstallResult, ...]:
    results = []
    for spec in packages:
        if not spec.import_name:
            continue
        command = (
            python_executable,
            "-c",
            f"import importlib; importlib.import_module({spec.import_name!r})",
        )
        emit("verify_started", spec, None)
        try:
            return_code, output = run_command(
                command,
                lambda line: emit("verify_output", spec, line),
            )
        except OSError as exc:
            return_code = None
            output = str(exc)
            emit("verify_output", spec, output)
        summary = "" if return_code == 0 else classify_install_failure(spec.distribution, output)
        result = InstallResult(spec, command, return_code, output, summary)
        results.append(result)
        emit("verify_result", spec, result)
    return tuple(results)


def run_command(
    command: Sequence[str],
    on_line: Callable[[str], None] | None = None,
) -> tuple[int, str]:
    kwargs = {
        "args": list(command),
        "cwd": str(PROJECT_ROOT),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "bufsize": 1,
    }
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    process = subprocess.Popen(**kwargs)
    output_lines = []
    if process.stdout is not None:
        for raw_line in process.stdout:
            line = raw_line.rstrip("\r\n")
            output_lines.append(line)
            if on_line is not None:
                on_line(line)
    return process.wait(), "\n".join(output_lines)


def find_msvc_build_tools() -> str | None:
    compiler = shutil.which("cl.exe")
    if compiler:
        return compiler
    program_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    vswhere = Path(program_files_x86) / "Microsoft Visual Studio" / "Installer" / "vswhere.exe"
    if not vswhere.is_file():
        return None
    try:
        result = subprocess.run(
            [
                str(vswhere),
                "-products",
                "*",
                "-requires",
                "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
                "-property",
                "installationPath",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    for installation in result.stdout.splitlines():
        root = Path(installation.strip())
        compiler_paths = root.glob("VC/Tools/MSVC/*/bin/Hostx64/x64/cl.exe")
        found = next((path for path in compiler_paths if path.is_file()), None)
        if found is not None:
            return str(found)
    return None


def model_file_path(name: str, cache: Path | None = None) -> Path:
    if cache is None:
        root = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        cache = root / "LocalAudioTranscriber" / "whisper-models"
    return cache / f"{name}.pt"


class SetupWizard(tk.Tk):
    STAGES = ("Welcome", "Dependencies", "Models", "Summary")

    def __init__(self, packages: Sequence[PackageSpec], all_models: bool = False):
        super().__init__()
        self.packages = tuple(packages)
        self.python_executable = console_python_executable()
        self.build_tools_path = find_msvc_build_tools()
        self.events: queue.Queue[tuple] = queue.Queue()
        self.failures: dict[str, SetupIssue] = {}
        self.import_failures: dict[str, SetupIssue] = {}
        self.verified_packages: set[str] = set()
        self.package_states: dict[str, str] = {}
        self.model_failures: dict[str, SetupIssue] = {}
        self.model_states: dict[str, str] = {}
        self.busy = False
        self.page_index = 0
        self._encoder_was_available = installed_version("resemblyzer") is not None
        self.model_vars = {
            name: tk.BooleanVar(value=all_models or name == "small.en")
            for name in MODEL_NAMES
        }
        self.speaker_encoder_var = tk.BooleanVar(value=True)
        self.title(f"TranscriptForge Setup Wizard v{__version__}")
        self.geometry("1000x760")
        self.minsize(900, 680)
        self.protocol("WM_DELETE_WINDOW", self._request_close)
        self._build_window()
        self._refresh_package_states()
        self._refresh_system_summary()
        self._show_page(0)
        self.after(100, self._drain_events)
        self.after(200, lambda: self._verify_installed_packages(show_empty_notice=False))

    def _build_window(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        outer = ttk.Frame(self, padding=14)
        outer.grid(row=0, column=0, sticky="nsew")
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(1, weight=1)

        header = ttk.Frame(outer)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        header.columnconfigure(0, weight=1)
        self.heading_var = tk.StringVar()
        ttk.Label(header, textvariable=self.heading_var, font=("Segoe UI", 16, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        self.stage_var = tk.StringVar()
        ttk.Label(header, textvariable=self.stage_var).grid(row=0, column=1, sticky="e")
        self.navigation_status = tk.StringVar()

        self.page_host = ttk.Frame(outer)
        self.page_host.grid(row=1, column=0, sticky="nsew")
        self.page_host.columnconfigure(0, weight=1)
        self.page_host.rowconfigure(0, weight=1)

        self.pages = [
            ttk.Frame(self.page_host),
            ttk.Frame(self.page_host),
            ttk.Frame(self.page_host),
            ttk.Frame(self.page_host),
        ]
        for page in self.pages:
            page.grid(row=0, column=0, sticky="nsew")
            page.columnconfigure(0, weight=1)
            page.rowconfigure(1, weight=1)
        self._build_welcome_page()
        self._build_dependencies_page()
        self._build_models_page()
        self._build_summary_page()

        activity_frame = ttk.LabelFrame(outer, text="Setup activity", padding=6)
        activity_frame.grid(row=2, column=0, sticky="nsew", pady=(10, 8))
        activity_frame.columnconfigure(0, weight=1)
        self.activity = scrolledtext.ScrolledText(activity_frame, height=8, wrap="word", state="disabled")
        self.activity.grid(row=0, column=0, sticky="nsew")
        self.progress = ttk.Progressbar(activity_frame, mode="indeterminate")
        self.progress.grid(row=1, column=0, sticky="ew", pady=(6, 0))

        footer = ttk.Frame(outer)
        footer.grid(row=3, column=0, sticky="ew")
        footer.columnconfigure(1, weight=1)
        self.back_button = ttk.Button(footer, text="Back", command=self._back)
        self.back_button.grid(row=0, column=0, sticky="w")
        ttk.Label(footer, textvariable=self.navigation_status).grid(row=0, column=1, padx=12, sticky="w")
        self.next_button = ttk.Button(footer, text="Next", command=self._next)
        self.next_button.grid(row=0, column=2, sticky="e")

    def _build_welcome_page(self) -> None:
        page = self.pages[0]
        ttk.Label(
            page,
            text="Welcome to TranscriptForge setup",
            font=("Segoe UI", 13, "bold"),
        ).grid(row=0, column=0, sticky="w", pady=(4, 8))
        ttk.Label(
            page,
            text=(
                "This wizard checks the current PC, installs available Python packages, and reports "
                "individual failures without stopping unrelated installs. Package downloads run in "
                "the background while this window remains responsive."
            ),
            wraplength=900,
            justify="left",
        ).grid(row=1, column=0, sticky="ew", pady=(0, 12))
        checks = ttk.LabelFrame(page, text="System checks", padding=12)
        checks.grid(row=2, column=0, sticky="ew")
        checks.columnconfigure(1, weight=1)
        self.system_values: dict[str, tk.StringVar] = {}
        for row, label in enumerate(("Python", "Python executable", "Tkinter", "pip", "C++ build tools")):
            ttk.Label(checks, text=f"{label}:").grid(row=row, column=0, sticky="nw", padx=(0, 12), pady=3)
            value = tk.StringVar()
            self.system_values[label] = value
            ttk.Label(checks, textvariable=value, wraplength=780, justify="left").grid(
                row=row, column=1, sticky="w", pady=3
            )
        pip_actions = ttk.Frame(page)
        pip_actions.grid(row=3, column=0, sticky="w", pady=(12, 0))
        self.repair_pip_button = ttk.Button(pip_actions, text="Repair pip", command=self._repair_pip)
        self.repair_pip_button.pack(side="left")
        self.build_tools_button = ttk.Button(
            pip_actions,
            text="Get Microsoft C++ Build Tools",
            command=self._open_build_tools_page,
        )
        self.build_tools_button.pack(side="left", padx=(8, 0))
        self.refresh_checks_button = ttk.Button(
            pip_actions,
            text="Refresh checks",
            command=self._refresh_system_checks,
        )
        self.refresh_checks_button.pack(side="left", padx=(8, 0))
        ttk.Label(
            page,
            text=(
                "C++ Build Tools are only needed when pip must compile a native package such as "
                "webrtcvad from source. A C++ compiler error is different from a firewall or download block."
            ),
            wraplength=900,
            justify="left",
        ).grid(row=4, column=0, sticky="ew", pady=(10, 0))

    def _build_dependencies_page(self) -> None:
        page = self.pages[1]
        ttk.Label(
            page,
            text="Python packages",
            font=("Segoe UI", 13, "bold"),
        ).grid(row=0, column=0, sticky="w", pady=(4, 6))
        ttk.Label(
            page,
            text=(
                "Required packages enable core transcription. Optional packages enable speaker identification, "
                "Outlook calendar integration, or live system-audio recording. Pip resolves each package's "
                "transitive dependencies. Each direct package is attempted separately so a failure does not "
                "stop the remaining installs."
            ),
            wraplength=900,
            justify="left",
        ).grid(row=1, column=0, sticky="ew", pady=(0, 8))
        table_frame = ttk.Frame(page)
        table_frame.grid(row=2, column=0, sticky="nsew")
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)
        self.dependency_tree = ttk.Treeview(
            table_frame,
            columns=("package", "purpose", "kind", "status"),
            show="headings",
            selectmode="extended",
            height=8,
        )
        for column, label, width in (
            ("package", "Package", 170),
            ("purpose", "Feature", 410),
            ("kind", "Type", 100),
            ("status", "Status", 230),
        ):
            self.dependency_tree.heading(column, text=label)
            self.dependency_tree.column(column, width=width, anchor="w")
        self.dependency_tree.grid(row=0, column=0, sticky="nsew")
        tree_scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.dependency_tree.yview)
        tree_scroll.grid(row=0, column=1, sticky="ns")
        self.dependency_tree.configure(yscrollcommand=tree_scroll.set)
        self._populate_dependency_rows()

        ttk.Label(
            page,
            text=(
                "Resemblyzer uses webrtcvad as a transitive dependency. If its installation reports "
                "“Microsoft Visual C++ 14.0 or greater is required,” use the C++ Build Tools link on the Welcome stage."
            ),
            wraplength=900,
            justify="left",
        ).grid(row=3, column=0, sticky="ew", pady=(8, 4))
        actions = ttk.Frame(page)
        actions.grid(row=4, column=0, sticky="ew", pady=(2, 0))
        self.install_all_button = ttk.Button(
            actions,
            text="Install missing packages",
            command=self._install_missing_packages,
        )
        self.install_all_button.pack(side="left")
        self.install_selected_button = ttk.Button(
            actions,
            text="Install selected",
            command=self._install_selected_packages,
        )
        self.install_selected_button.pack(side="left", padx=(8, 0))
        self.verify_button = ttk.Button(
            actions,
            text="Verify installed imports",
            command=self._verify_installed_packages,
        )
        self.verify_button.pack(side="left", padx=(8, 0))

    def _build_models_page(self) -> None:
        page = self.pages[2]
        ttk.Label(
            page,
            text="Models and local feature setup",
            font=("Segoe UI", 13, "bold"),
        ).grid(row=0, column=0, sticky="w", pady=(4, 6))
        ttk.Label(
            page,
            text=(
                "Whisper models are separate from Python packages. Downloading a model is optional during setup; "
                "the GUI can download one later. Failed model downloads do not stop other selected downloads."
            ),
            wraplength=900,
            justify="left",
        ).grid(row=1, column=0, sticky="ew", pady=(0, 10))
        model_frame = ttk.LabelFrame(page, text="Whisper models", padding=10)
        model_frame.grid(row=2, column=0, sticky="ew")
        self.model_status_labels: dict[str, tk.StringVar] = {}
        for row, name in enumerate(MODEL_NAMES):
            ttk.Checkbutton(model_frame, text=name, variable=self.model_vars[name]).grid(
                row=row, column=0, sticky="w", padx=(0, 12), pady=3
            )
            status = tk.StringVar()
            self.model_status_labels[name] = status
            ttk.Label(model_frame, textvariable=status).grid(row=row, column=1, sticky="w", pady=3)
        encoder_frame = ttk.LabelFrame(page, text="Speaker encoder", padding=10)
        encoder_frame.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        self.encoder_check = ttk.Checkbutton(
            encoder_frame,
            text="Download and initialize the local Resemblyzer speaker encoder",
            variable=self.speaker_encoder_var,
        )
        self.encoder_check.grid(row=0, column=0, sticky="w")
        self.encoder_status = tk.StringVar()
        ttk.Label(encoder_frame, textvariable=self.encoder_status, wraplength=850).grid(
            row=1, column=0, sticky="w", pady=(4, 0)
        )
        self.download_models_button = ttk.Button(
            page,
            text="Download selected items",
            command=self._download_selected_models,
        )
        self.download_models_button.grid(row=4, column=0, sticky="w", pady=(12, 0))

    def _build_summary_page(self) -> None:
        page = self.pages[3]
        page.rowconfigure(1, weight=0)
        ttk.Label(page, text="Setup summary", font=("Segoe UI", 13, "bold")).grid(
            row=0, column=0, sticky="w", pady=(4, 6)
        )
        self.summary_var = tk.StringVar()
        ttk.Label(page, textvariable=self.summary_var, wraplength=900, justify="left").grid(
            row=1, column=0, sticky="ew", pady=(0, 8)
        )
        ttk.Label(
            page,
            text="Copy or save this report when contacting IT. It lists the executable and hosts involved in failures.",
        ).grid(row=2, column=0, sticky="w", pady=(0, 4))
        self.report_text = scrolledtext.ScrolledText(page, height=13, wrap="word", state="disabled")
        self.report_text.grid(row=3, column=0, sticky="nsew")
        actions = ttk.Frame(page)
        actions.grid(row=4, column=0, sticky="ew", pady=(8, 0))
        self.copy_report_button = ttk.Button(actions, text="Copy IT report", command=self._copy_report)
        self.copy_report_button.pack(side="left")
        self.save_report_button = ttk.Button(actions, text="Save IT report", command=self._save_report)
        self.save_report_button.pack(side="left", padx=(8, 0))
        self.launch_button = ttk.Button(actions, text="Launch TranscriptForge", command=self._launch_app)
        self.launch_button.pack(side="right")

    def _populate_dependency_rows(self) -> None:
        for spec in self.packages:
            key = normalize_distribution_name(spec.distribution)
            self.dependency_tree.insert(
                "",
                "end",
                iid=key,
                values=(spec.distribution, spec.purpose, "Required" if spec.required else "Optional", ""),
            )
        self._refresh_package_states()

    def _refresh_package_states(self) -> None:
        for spec in self.packages:
            key = normalize_distribution_name(spec.distribution)
            version = installed_version(spec.distribution)
            if key in self.failures:
                state = f"Failed: {self.failures[key].summary}"
            elif version:
                if key in self.import_failures:
                    state = "Import failed (see IT report)"
                elif key in self.verified_packages:
                    state = f"Verified {version}"
                else:
                    state = f"Installed {version}"
            else:
                previous = self.package_states.get(key, "")
                state = previous if previous.startswith("Failed") else "Missing"
            self.package_states[key] = state
            if self.dependency_tree.exists(key):
                current_values = list(self.dependency_tree.item(key, "values"))
                current_values[-1] = state
                self.dependency_tree.item(key, values=current_values)
        self._refresh_system_summary()
        self._update_navigation_status()

    def _refresh_system_summary(self) -> None:
        version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        architecture = f"{8 * struct.calcsize('P')}-bit {platform.machine()}"
        self.system_values["Python"].set(f"{version}, {architecture}")
        if sys.version_info < (3, 11):
            self.system_values["Python"].set(f"{version}, unsupported; Python 3.11 or newer is required")
        self.system_values["Python executable"].set(self.python_executable)
        self.system_values["Tkinter"].set(f"Ready (Tk {tk.TkVersion:g})")
        pip_version = installed_version("pip")
        self.system_values["pip"].set(f"Available {pip_version}" if pip_version else "Missing")
        if self.build_tools_path:
            self.system_values["C++ build tools"].set(f"Detected: {self.build_tools_path}")
        else:
            self.system_values["C++ build tools"].set("Not detected (only needed for some native source builds)")
        self.repair_pip_button.configure(state="normal" if not importlib.util.find_spec("pip") else "disabled")

    def _refresh_system_checks(self) -> None:
        self.build_tools_path = find_msvc_build_tools()
        self._refresh_system_summary()
        self._refresh_package_states()
        self._append_activity("System and package checks refreshed.")

    def _build_issue(self, name: str, purpose: str, required: bool, command: Sequence[str], output: str) -> SetupIssue:
        return SetupIssue(
            name=name,
            purpose=purpose,
            required=required,
            command=tuple(command),
            output=output,
            summary=classify_install_failure(name, output),
        )

    def _issues(self) -> tuple[SetupIssue, ...]:
        package_issues = tuple(self.failures.values())
        import_issues = tuple(self.import_failures.values())
        return package_issues + import_issues + tuple(self.model_failures.values())

    def _support_report(self) -> str:
        return make_support_report(
            self._issues(),
            self.python_executable,
            self.build_tools_path is not None,
        )

    def _refresh_summary(self) -> None:
        required_missing = [
            spec.distribution
            for spec in self.packages
            if spec.required
            and (
                installed_version(spec.distribution) is None
                or normalize_distribution_name(spec.distribution) in self.failures
            )
        ]
        required_import_errors = [
            spec.distribution
            for spec in self.packages
            if spec.required and normalize_distribution_name(spec.distribution) in self.import_failures
        ]
        optional_missing = [
            spec.distribution
            for spec in self.packages
            if not spec.required
            and (
                installed_version(spec.distribution) is None
                or normalize_distribution_name(spec.distribution) in self.failures
            )
        ]
        optional_import_errors = [
            spec.distribution
            for spec in self.packages
            if not spec.required and normalize_distribution_name(spec.distribution) in self.import_failures
        ]
        if sys.version_info < (3, 11):
            readiness = "Core transcription is not ready. Python 3.11 or newer is required."
        elif required_missing:
            readiness = "Core transcription is not ready. Missing or failed required packages: " + ", ".join(required_missing) + "."
        elif required_import_errors:
            readiness = "Core transcription is not ready. These installed packages failed their import check: " + ", ".join(required_import_errors) + "."
        else:
            readiness = "Required packages are installed. TranscriptForge can be launched."
        if optional_missing:
            readiness += " Optional features unavailable until installed: " + ", ".join(optional_missing) + "."
        if optional_import_errors:
            readiness += " Optional package imports failed: " + ", ".join(optional_import_errors) + "."
        if "pip-update" in self.failures:
            readiness += " The pip update failed, but setup continued with package installation."
        cached_models = [name for name in MODEL_NAMES if model_file_path(name).is_file()]
        if cached_models:
            readiness += " Cached Whisper models: " + ", ".join(cached_models) + "."
        else:
            readiness += " No Whisper model is cached yet; download one in the wizard or from the app."
        self.summary_var.set(readiness)
        self.launch_button.configure(
            state=(
                "normal"
                if sys.version_info >= (3, 11) and not required_missing and not required_import_errors
                else "disabled"
            )
        )
        report = self._support_report()
        self.report_text.configure(state="normal")
        self.report_text.delete("1.0", "end")
        self.report_text.insert("1.0", report)
        self.report_text.configure(state="disabled")

    def _show_page(self, index: int) -> None:
        self.page_index = index
        self.pages[index].tkraise()
        self.heading_var.set(self.STAGES[index])
        self.stage_var.set(f"Stage {index + 1} of {len(self.STAGES)}")
        self.back_button.configure(state="normal" if index > 0 and not self.busy else "disabled")
        self.next_button.configure(
            text="Finish" if index == len(self.STAGES) - 1 else "Next",
            state="disabled" if self.busy else "normal",
        )
        if index == 2:
            self._refresh_model_states()
        if index == 3:
            self._refresh_summary()
        self._update_navigation_status()

    def _update_navigation_status(self) -> None:
        ready = all(
            installed_version(spec.distribution) is not None
            and normalize_distribution_name(spec.distribution) not in self.import_failures
            and normalize_distribution_name(spec.distribution) not in self.failures
            for spec in self.packages
            if spec.required
        )
        if sys.version_info < (3, 11):
            self.navigation_status.set("Python 3.11 or newer is required.")
        elif ready:
            self.navigation_status.set("Core transcription dependencies are installed.")
        else:
            self.navigation_status.set("Install required packages before launching transcription.")

    def _back(self) -> None:
        if not self.busy and self.page_index > 0:
            self._show_page(self.page_index - 1)

    def _next(self) -> None:
        if self.busy:
            return
        if self.page_index == len(self.STAGES) - 1:
            self.destroy()
            return
        self._show_page(self.page_index + 1)

    def _request_close(self) -> None:
        if self.busy:
            messagebox.showwarning(
                "Setup is still running",
                "Wait for the current installation or download to finish before closing this wizard.",
                parent=self,
            )
            return
        self.destroy()

    def _append_activity(self, message: str) -> None:
        self.activity.configure(state="normal")
        self.activity.insert("end", message + "\n")
        self.activity.see("end")
        self.activity.configure(state="disabled")

    def _set_busy(self, busy: bool, status: str = "") -> None:
        self.busy = busy
        if busy:
            self.progress.start(12)
        else:
            self.progress.stop()
        self.back_button.configure(state="disabled" if busy or self.page_index == 0 else "normal")
        self.next_button.configure(state="disabled" if busy else "normal")
        for button in (
            self.install_all_button,
            self.install_selected_button,
            self.verify_button,
            self.download_models_button,
            self.repair_pip_button,
            self.refresh_checks_button,
            self.copy_report_button,
            self.save_report_button,
            self.launch_button,
        ):
            button.configure(state="disabled" if busy else "normal")
        if status:
            self.navigation_status.set(status)

    def _start_worker(self, label: str, target: Callable[[], None]) -> None:
        if self.busy:
            return
        self._set_busy(True, label)

        def run() -> None:
            try:
                target()
            except Exception as exc:
                details = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
                self.events.put(("fatal", details))
            finally:
                self.events.put(("finished", label))

        threading.Thread(target=run, name="TranscriptForgeSetup", daemon=True).start()

    def _install_missing_packages(self) -> None:
        repair = frozenset(
            normalize_distribution_name(spec.distribution)
            for spec in self.packages
            if normalize_distribution_name(spec.distribution) in self.failures
            or normalize_distribution_name(spec.distribution) in self.import_failures
        )
        self._install_packages(
            tuple(
                spec for spec in self.packages
                if installed_version(spec.distribution) is None
                or normalize_distribution_name(spec.distribution) in repair
            ),
            force_reinstall=frozenset(
                key for key in repair
                if any(
                    normalize_distribution_name(spec.distribution) == key
                    and installed_version(spec.distribution) is not None
                    for spec in self.packages
                )
            ),
        )

    def _install_selected_packages(self) -> None:
        selected = {normalize_distribution_name(item) for item in self.dependency_tree.selection()}
        repair = frozenset(
            key for key in selected
            if key in self.import_failures or key in self.failures
        )
        self._install_packages(
            tuple(
                spec for spec in self.packages
                if normalize_distribution_name(spec.distribution) in selected
                and (
                    installed_version(spec.distribution) is None
                    or normalize_distribution_name(spec.distribution) in repair
                )
            ),
            force_reinstall=repair,
        )

    def _install_packages(
        self,
        packages: Sequence[PackageSpec],
        force_reinstall: frozenset[str] = frozenset(),
    ) -> None:
        if not packages:
            messagebox.showinfo("Packages are ready", "No selected packages are missing.", parent=self)
            return
        if sys.version_info < (3, 11):
            messagebox.showerror(
                "Unsupported Python version",
                "TranscriptForge setup requires Python 3.11 or newer.",
                parent=self,
            )
            return
        if importlib.util.find_spec("pip") is None:
            messagebox.showerror(
                "pip is unavailable",
                "Repair pip on the Welcome stage, then retry the package installation.",
                parent=self,
            )
            return
        self._append_activity(f"Starting individual package installs with {self.python_executable}.")

        def emit(event: str, spec: PackageSpec, payload: object | None) -> None:
            self.events.put(("package", event, spec, payload))

        def worker() -> None:
            pip_command = build_pip_install_command(
                self.python_executable,
                "pip",
                use_user_site(),
                upgrade=True,
            )
            try:
                pip_code, pip_output = run_command(
                    pip_command,
                    lambda line: self.events.put(("log", f"[pip update] {line}")),
                )
            except OSError as exc:
                pip_code, pip_output = None, str(exc)
            self.events.put(("pip_upgrade_result", pip_command, pip_code, pip_output))
            run_install_sequence(
                packages,
                self.python_executable,
                use_user_site(),
                run_command,
                emit,
                force_reinstall,
            )
            installed = tuple(
                spec for spec in self.packages
                if installed_version(spec.distribution) is not None and spec.import_name
            )
            run_import_check_sequence(
                installed,
                self.python_executable,
                run_command,
                emit,
            )
            self.events.put(("package_sequence_done",))

        self._start_worker("Installing Python packages...", worker)

    def _verify_installed_packages(self, show_empty_notice: bool = True) -> None:
        installed = tuple(
            spec for spec in self.packages
            if installed_version(spec.distribution) is not None and spec.import_name
        )
        if not installed:
            if show_empty_notice:
                messagebox.showinfo(
                    "No installed packages to verify",
                    "Install packages first, then verify their imports.",
                    parent=self,
                )
            return

        def emit(event: str, spec: PackageSpec, payload: object | None) -> None:
            self.events.put(("package", event, spec, payload))

        def worker() -> None:
            run_import_check_sequence(installed, self.python_executable, run_command, emit)
            self.events.put(("verification_done",))

        self._append_activity("Checking imports for installed Python packages.")
        self._start_worker("Verifying installed packages...", worker)

    def _repair_pip(self) -> None:
        if importlib.util.find_spec("pip") is not None:
            self._refresh_system_summary()
            return
        command = [self.python_executable, "-m", "ensurepip", "--upgrade"]
        if use_user_site():
            command.append("--user")
        self._append_activity("Repairing pip with Python's bundled ensurepip.")

        def worker() -> None:
            try:
                return_code, output = run_command(
                    command,
                    lambda line: self.events.put(("log", f"[pip] {line}")),
                )
            except OSError as exc:
                return_code, output = None, str(exc)
            self.events.put(("pip_result", tuple(command), return_code, output))

        self._start_worker("Repairing pip...", worker)

    def _refresh_model_states(self) -> None:
        for name in MODEL_NAMES:
            issue = self.model_failures.get(f"model:{name}")
            if issue:
                model_status = f"Failed: {issue.summary}"
            elif model_file_path(name).is_file():
                model_status = "Already downloaded"
            else:
                model_status = "Not downloaded"
            self.model_status_labels[name].set(model_status)
        resemblyzer_key = normalize_distribution_name("resemblyzer")
        resemblyzer_ready = (
            installed_version("resemblyzer") is not None
            and resemblyzer_key not in self.import_failures
        )
        if resemblyzer_ready:
            if not self._encoder_was_available:
                self.speaker_encoder_var.set(True)
            self._encoder_was_available = True
            if "speaker-encoder" in self.model_failures:
                self.encoder_status.set(f"Failed: {self.model_failures['speaker-encoder'].summary}")
            elif self.model_states.get("speaker-encoder") == "Ready":
                self.encoder_status.set("Speaker encoder is ready.")
            else:
                self.encoder_status.set("Ready to initialize after selecting Download.")
            self.encoder_check.configure(state="normal")
        else:
            self._encoder_was_available = False
            if installed_version("resemblyzer") is not None:
                self.encoder_status.set("Resemblyzer import failed; repair it on the Dependencies stage.")
            else:
                self.encoder_status.set("Resemblyzer is not installed; speaker identification will remain unavailable.")
            self.encoder_check.configure(state="disabled")
            self.speaker_encoder_var.set(False)
        core_ready = all(
            installed_version(spec.distribution) is not None
            and normalize_distribution_name(spec.distribution) not in self.import_failures
            and normalize_distribution_name(spec.distribution) not in self.failures
            for spec in self.packages
            if spec.required
        ) and sys.version_info >= (3, 11)
        if not core_ready:
            self.download_models_button.configure(state="disabled")
            self.navigation_status.set("Install required packages before downloading Whisper models.")
        else:
            self.download_models_button.configure(state="normal" if not self.busy else "disabled")

    def _download_selected_models(self) -> None:
        if not self.download_models_button.instate(["!disabled"]):
            return
        selected = [name for name in MODEL_NAMES if self.model_vars[name].get()]
        tasks = []
        for name in selected:
            if model_file_path(name).is_file():
                self.model_states[name] = "Already downloaded"
                self.model_failures.pop(f"model:{name}", None)
                self.model_status_labels[name].set("Already downloaded")
                continue
            tasks.append(
                (
                    f"model:{name}",
                    f"Whisper model {name}",
                    (
                        self.python_executable,
                        "-m",
                        "transcriptforge.cli",
                        "models",
                        "download",
                        name,
                    ),
                    False,
                )
            )
        if self.speaker_encoder_var.get() and installed_version("resemblyzer") is not None:
            tasks.append(
                (
                    "speaker-encoder",
                    "Resemblyzer speaker encoder",
                    (
                        self.python_executable,
                        "-c",
                        "from resemblyzer import VoiceEncoder; VoiceEncoder(device='cpu'); print('Speaker encoder model: ready')",
                    ),
                    False,
                )
            )
        if not tasks:
            messagebox.showinfo("Models are ready", "No selected model or speaker encoder needs setup.", parent=self)
            return
        self._append_activity("Starting selected model downloads and encoder initialization.")

        def worker() -> None:
            for key, label, command, required in tasks:
                self.events.put(("task_started", key, label))

                def on_line(line: str, task_label: str = label) -> None:
                    self.events.put(("log", f"[{task_label}] {line}"))

                try:
                    return_code, output = run_command(command, on_line)
                except OSError as exc:
                    return_code, output = None, str(exc)
                    on_line(output)
                if return_code != 0:
                    issue = self._build_issue(label, "Model or speaker-encoder download", required, command, output)
                    self.events.put(("task_failed", key, label, issue))
                else:
                    self.events.put(("task_succeeded", key, label))
            self.events.put(("model_sequence_done",))

        self._start_worker("Downloading selected models...", worker)

    def _drain_events(self) -> None:
        try:
            while True:
                event = self.events.get_nowait()
                kind = event[0]
                if kind == "log":
                    self._append_activity(event[1])
                elif kind == "package":
                    self._handle_package_event(event[1], event[2], event[3])
                elif kind == "package_sequence_done":
                    self._refresh_package_states()
                    self._append_activity("Finished attempting all selected Python packages.")
                elif kind == "verification_done":
                    self._refresh_package_states()
                    self._append_activity("Finished verifying installed package imports.")
                elif kind == "pip_result":
                    self._handle_pip_result(event[1], event[2], event[3])
                elif kind == "pip_upgrade_result":
                    self._handle_pip_upgrade_result(event[1], event[2], event[3])
                elif kind == "task_started":
                    self.model_states[event[1]] = "Installing"
                    self._append_activity(f"Starting {event[2]}.")
                    if event[1].startswith("model:"):
                        model_name = event[1].split(":", 1)[1]
                        self.model_status_labels[model_name].set("Downloading...")
                    elif event[1] == "speaker-encoder":
                        self.encoder_status.set("Downloading and initializing...")
                elif kind == "task_failed":
                    self.model_failures[event[1]] = event[3]
                    self.model_states[event[1]] = "Failed"
                    if event[1].startswith("model:"):
                        model_name = event[1].split(":", 1)[1]
                        self.model_status_labels[model_name].set(f"Failed: {event[3].summary}")
                    elif event[1] == "speaker-encoder":
                        self.encoder_status.set(f"Failed: {event[3].summary}")
                    self._append_activity(f"Failed: {event[2]}. The wizard will continue with other selected items.")
                elif kind == "task_succeeded":
                    self.model_failures.pop(event[1], None)
                    self.model_states[event[1]] = "Ready"
                    if event[1].startswith("model:"):
                        model_name = event[1].split(":", 1)[1]
                        self.model_status_labels[model_name].set("Downloaded")
                    elif event[1] == "speaker-encoder":
                        self.encoder_status.set("Speaker encoder is ready.")
                    self._append_activity(f"Completed: {event[2]}.")
                elif kind == "model_sequence_done":
                    self._refresh_model_states()
                    self._append_activity("Finished attempting all selected model and encoder tasks.")
                elif kind == "fatal":
                    self._append_activity("Unexpected setup error:")
                    self._append_activity(event[1])
                    messagebox.showerror("Setup error", event[1], parent=self)
                elif kind == "finished":
                    self._set_busy(False)
                    self._refresh_package_states()
                    self._refresh_model_states()
                    if self.page_index == 3:
                        self._refresh_summary()
        except queue.Empty:
            pass
        self.after(100, self._drain_events)

    def _handle_package_event(self, event: str, spec: PackageSpec, payload: object | None) -> None:
        key = normalize_distribution_name(spec.distribution)
        if event == "started":
            self.package_states[key] = "Installing"
            self._append_activity(f"Installing {spec.distribution}...")
        elif event == "output":
            self._append_activity(f"[{spec.distribution}] {payload}")
        elif event == "result":
            result = payload
            if not isinstance(result, InstallResult):
                self._append_activity(f"Unexpected result type for {spec.distribution}.")
                return
            if result.succeeded:
                self.failures.pop(key, None)
                version = installed_version(spec.distribution)
                if version:
                    self.verified_packages.discard(key)
                    self.package_states[key] = f"Installed {version}"
                    self._append_activity(f"Completed installation attempt for {spec.distribution}.")
                else:
                    issue = SetupIssue(
                        name=spec.distribution,
                        purpose=spec.purpose,
                        required=spec.required,
                        command=result.command,
                        output=result.output,
                        summary="Pip returned success, but the package is not visible to this Python interpreter.",
                    )
                    self.failures[key] = issue
                    self.package_states[key] = "Failed: package not found after install"
                    self._append_activity(f"Could not verify {spec.distribution} after installation.")
            else:
                issue = result.as_issue()
                self.failures[key] = issue
                self.package_states[key] = f"Failed: {issue.summary}"
                self._append_activity(f"Failed {spec.distribution}: {issue.summary}")
                self._append_activity("Continuing with the remaining selected packages.")
            if self.dependency_tree.exists(key):
                values = list(self.dependency_tree.item(key, "values"))
                values[-1] = self.package_states[key]
                self.dependency_tree.item(key, values=values)
        elif event == "verify_started":
            self.package_states[key] = "Checking import..."
            if self.dependency_tree.exists(key):
                values = list(self.dependency_tree.item(key, "values"))
                values[-1] = self.package_states[key]
                self.dependency_tree.item(key, values=values)
            self._append_activity(f"Verifying import for {spec.distribution}...")
        elif event == "verify_output":
            self._append_activity(f"[{spec.distribution} import] {payload}")
        elif event == "verify_result":
            result = payload
            if not isinstance(result, InstallResult):
                self._append_activity(f"Unexpected verification result for {spec.distribution}.")
                return
            if result.succeeded:
                self.import_failures.pop(key, None)
                self.verified_packages.add(key)
                version = installed_version(spec.distribution)
                self.package_states[key] = f"Verified {version}" if version else "Import verified"
                self._append_activity(f"Import verified for {spec.distribution}.")
            else:
                issue = result.as_issue()
                issue = SetupIssue(
                    name=f"{spec.distribution} import",
                    purpose=spec.purpose,
                    required=spec.required,
                    command=result.command,
                    output=result.output,
                    summary=f"Package is installed, but its import failed: {issue.summary}",
                )
                self.import_failures[key] = issue
                self.verified_packages.discard(key)
                self.package_states[key] = f"Import failed: {issue.summary}"
                self._append_activity(f"Import failed for {spec.distribution}: {issue.summary}")
            if self.dependency_tree.exists(key):
                values = list(self.dependency_tree.item(key, "values"))
                values[-1] = self.package_states[key]
                self.dependency_tree.item(key, values=values)

    def _handle_pip_result(self, command: tuple[str, ...], return_code: int | None, output: str) -> None:
        self._refresh_system_summary()
        if return_code == 0 and importlib.util.find_spec("pip") is not None:
            self.failures.pop("pip", None)
            self._append_activity("pip repair completed.")
            return
        issue = self._build_issue(
            "pip",
            "Python package installer",
            True,
            command,
            output,
        )
        self.failures["pip"] = issue
        self._append_activity(f"pip repair failed: {issue.summary}")

    def _handle_pip_upgrade_result(
        self,
        command: tuple[str, ...],
        return_code: int | None,
        output: str,
    ) -> None:
        if return_code == 0:
            self.failures.pop("pip-update", None)
            self._append_activity("pip update completed.")
            return
        issue = self._build_issue(
            "pip update",
            "Optional Python package-installer update",
            False,
            command,
            output,
        )
        self.failures["pip-update"] = issue
        self._append_activity(f"pip update failed: {issue.summary}")
        self._append_activity("Continuing with the selected package installs.")

    def _open_build_tools_page(self) -> None:
        try:
            opened = webbrowser.open(BUILD_TOOLS_URL)
        except (OSError, webbrowser.Error) as exc:
            messagebox.showerror("Could not open Microsoft C++ Build Tools", f"{exc}\n\n{BUILD_TOOLS_URL}", parent=self)
            return
        if not opened:
            messagebox.showinfo("Microsoft C++ Build Tools", BUILD_TOOLS_URL, parent=self)

    def _copy_report(self) -> None:
        try:
            self.clipboard_clear()
            self.clipboard_append(self._support_report())
            self.update_idletasks()
        except tk.TclError as exc:
            messagebox.showerror("Could not copy report", str(exc), parent=self)
            return
        messagebox.showinfo("Report copied", "The IT support report is on the clipboard.", parent=self)

    def _save_report(self) -> None:
        path = filedialog.asksaveasfilename(
            parent=self,
            title="Save TranscriptForge setup report",
            defaultextension=".txt",
            initialfile="TranscriptForge-setup-report.txt",
            filetypes=(("Text files", "*.txt"), ("All files", "*.*")),
        )
        if not path:
            return
        try:
            Path(path).write_text(self._support_report() + "\n", encoding="utf-8")
        except OSError as exc:
            messagebox.showerror("Could not save report", str(exc), parent=self)
            return
        messagebox.showinfo("Report saved", f"Saved setup report to:\n{path}", parent=self)

    def _launch_app(self) -> None:
        missing = [
            spec.distribution
            for spec in self.packages
            if spec.required
            and (
                installed_version(spec.distribution) is None
                or normalize_distribution_name(spec.distribution) in self.import_failures
                or normalize_distribution_name(spec.distribution) in self.failures
            )
        ]
        if missing:
            messagebox.showerror(
                "Required packages are missing",
                "Install these required packages before launching: " + ", ".join(missing),
                parent=self,
            )
            return
        pythonw = Path(self.python_executable).with_name("pythonw.exe")
        executable = str(pythonw) if pythonw.is_file() else self.python_executable
        try:
            kwargs = {"cwd": str(PROJECT_ROOT), "stdin": subprocess.DEVNULL}
            if not pythonw.is_file() and hasattr(subprocess, "CREATE_NO_WINDOW"):
                kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
            subprocess.Popen([executable, "-m", "transcriptforge"], **kwargs)
        except OSError as exc:
            self._append_activity(f"Could not launch TranscriptForge: {exc}")
            messagebox.showerror("Could not launch TranscriptForge", str(exc), parent=self)
            return
        self._append_activity("TranscriptForge was launched.")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Guided TranscriptForge setup")
    parser.add_argument("--all-models", action="store_true", help="Select every supported Whisper model initially")
    args = parser.parse_args(argv)
    try:
        packages = load_package_specs()
    except (OSError, ValueError) as exc:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("TranscriptForge setup could not start", str(exc), parent=root)
        root.destroy()
        return 1
    wizard = SetupWizard(packages, all_models=args.all_models)
    wizard.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
