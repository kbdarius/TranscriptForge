import tempfile
import unittest
from pathlib import Path

from transcriptforge.setup_wizard import (
    PackageSpec,
    SetupIssue,
    build_pip_install_command,
    classify_install_failure,
    extract_hosts,
    load_package_specs,
    make_support_report,
    model_file_path,
    parse_requirement_name,
    run_import_check_sequence,
    run_install_sequence,
    use_user_site,
)


class SetupWizardTests(unittest.TestCase):
    def test_requirements_inventory_classifies_core_and_optional_features(self):
        specs = load_package_specs()
        by_name = {spec.distribution: spec for spec in specs}

        self.assertEqual(
            {name for name, spec in by_name.items() if spec.required},
            {"openai-whisper", "torch", "numpy", "imageio-ffmpeg"},
        )
        self.assertEqual(
            {name for name, spec in by_name.items() if not spec.required},
            {"resemblyzer", "pywin32", "soundcard"},
        )
        self.assertEqual(by_name["resemblyzer"].import_name, "resemblyzer")

    def test_requirement_name_parser_handles_extras_and_markers(self):
        self.assertEqual(parse_requirement_name("sample_package[extra]>=1.2; python_version > '3.10'"), "sample_package")

    def test_user_site_install_is_disabled_inside_a_virtual_environment(self):
        self.assertTrue(use_user_site("C:/Python", "C:/Python"))
        self.assertFalse(use_user_site("C:/project/.venv", "C:/Python"))

    def test_pip_install_command_supports_user_site_and_repair(self):
        command = build_pip_install_command("python.exe", "sample>=1", True, force_reinstall=True)

        self.assertIn("--user", command)
        self.assertIn("--force-reinstall", command)
        self.assertEqual(command[-1], "sample>=1")

    def test_model_path_uses_given_cache_without_creating_files(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "models"
            path = model_file_path("small.en", cache)

            self.assertEqual(path, cache / "small.en.pt")
            self.assertFalse(cache.exists())

    def test_install_sequence_continues_after_a_package_failure(self):
        specs = (
            PackageSpec("first-package", "first-package>=1", "First feature", True),
            PackageSpec("second-package", "second-package>=1", "Second feature", False),
        )
        attempted = []
        events = []

        def fake_run(command, on_line):
            package = command[-1]
            attempted.append(package)
            on_line(f"attempted {package}")
            if package == "first-package>=1":
                return 1, "Could not fetch URL https://pypi.org/simple/first-package"
            return 0, "Successfully installed second-package"

        results = run_install_sequence(
            specs,
            "python.exe",
            True,
            fake_run,
            lambda event, spec, payload: events.append((event, spec.distribution, payload)),
        )

        self.assertEqual(attempted, ["first-package>=1", "second-package>=1"])
        self.assertFalse(results[0].succeeded)
        self.assertTrue(results[1].succeeded)
        self.assertEqual([event[0] for event in events].count("result"), 2)

    def test_import_checks_continue_after_a_failed_import(self):
        specs = (
            PackageSpec("first-package", "first-package>=1", "First feature", True, "first_package"),
            PackageSpec("second-package", "second-package>=1", "Second feature", False, "second_package"),
        )
        attempted = []

        def fake_run(command, _on_line):
            attempted.append(command[-1])
            return (1, "ImportError: missing module") if "first_package" in command[-1] else (0, "")

        results = run_import_check_sequence(
            specs,
            "python.exe",
            fake_run,
            lambda *_args: None,
        )

        self.assertEqual(len(attempted), 2)
        self.assertFalse(results[0].succeeded)
        self.assertTrue(results[1].succeeded)

    def test_msvc_failure_is_not_misreported_as_a_network_block(self):
        output = "error: Microsoft Visual C++ 14.0 or greater is required.\nwebrtcvad"

        summary = classify_install_failure("resemblyzer", output)

        self.assertIn("webrtcvad", summary)
        self.assertIn("not a network block", summary)
        issue = SetupIssue(
            name="resemblyzer",
            purpose="Speaker identification",
            required=False,
            command=("python.exe", "-m", "pip", "install", "resemblyzer"),
            output=output,
            summary=summary,
        )
        report = make_support_report((issue,), "C:\\Python\\python.exe", False)

        self.assertIn("Microsoft C++ Build Tools", report)
        self.assertIn("MSVC 14+", report)
        self.assertNotIn("Hosts seen in the installer output", report)

    def test_network_support_report_names_executable_hosts_and_package(self):
        output = (
            "Could not fetch URL https://pypi.org/simple/sample-package "
            "HTTPConnectionPool(host='files.pythonhosted.org', port=443)"
        )
        issue = SetupIssue(
            name="sample-package",
            purpose="Example feature",
            required=True,
            command=("C:\\Python\\python.exe", "-m", "pip", "install", "sample-package"),
            output=output,
            summary=classify_install_failure("sample-package", output),
        )

        report = make_support_report((issue,), "C:\\Python\\python.exe", False, "0.27.0")

        self.assertIn("Software: TranscriptForge setup, version 0.27.0", report)
        self.assertIn("Failed item: sample-package (required)", report)
        self.assertIn("C:\\Python\\python.exe", report)
        self.assertIn("files.pythonhosted.org", report)
        self.assertIn("pypi.org", report)

    def test_support_report_does_not_copy_credentials_from_download_urls(self):
        output = "ReadTimeout from https://alice:secret@packages.example/simple"
        issue = SetupIssue(
            name="sample-package",
            purpose="Example feature",
            required=False,
            command=("python.exe", "-m", "pip", "install", "sample-package"),
            output=output,
            summary=classify_install_failure("sample-package", output),
        )

        report = make_support_report((issue,), "C:\\Python\\python.exe", True)

        self.assertIn("packages.example", report)
        self.assertNotIn("alice", report)
        self.assertNotIn("secret", report)
        self.assertEqual(extract_hosts(output), ("packages.example",))

    def test_generic_failure_summary_redacts_credentials(self):
        summary = classify_install_failure(
            "sample-package",
            "Pip could not complete request https://alice:secret@packages.example/simple",
        )

        self.assertIn("[credentials-redacted]", summary)
        self.assertNotIn("alice", summary)
        self.assertNotIn("secret", summary)


if __name__ == "__main__":
    unittest.main()
