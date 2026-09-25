import tempfile
import unittest
from pathlib import Path

from transcriptforge.configuration import export_configuration, import_configuration
from transcriptforge.settings import SampleRejectionStore
from transcriptforge.speakers import SpeakerProfileStore


class ConfigurationTests(unittest.TestCase):
    def test_export_import_transfers_portable_data_and_merges_profiles(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root / "source"; target = root / "target"; source.mkdir(); target.mkdir()
            profiles = SpeakerProfileStore(source / "speaker-profiles.json")
            self.assertTrue(profiles.add_confirmed_embedding("Alex", [1.0, 0.0], metadata={"source": "old-pc"})); profiles.save()
            rejections = SampleRejectionStore(source / "speaker-sample-rejections.json")
            rejections.add([0.0, 1.0], "Too noisy or unclear", "note", "meeting.wav")
            package = root / "transfer.tfconfig"
            export_configuration(package, {"identify_speakers": True, "language": "en"}, ["Standup"], profiles, rejections)
            destination_profiles = SpeakerProfileStore(target / "speaker-profiles.json")
            self.assertTrue(destination_profiles.add_confirmed_embedding("Alex", [0.0, 1.0], metadata={"source": "new-pc"})); destination_profiles.save()
            result = import_configuration(package, target)
            imported = SpeakerProfileStore(target / "speaker-profiles.json")
            self.assertEqual(result["templates"], 1); self.assertEqual(result["profiles"], 1); self.assertEqual(result["rejections"], 1)
            self.assertEqual(len(imported.profiles["Alex"]), 2)
            self.assertEqual(result["preferences"]["identify_speakers"], True)

    def test_export_import_preserves_confirmed_outlook_name_aliases(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            target = root / "target"
            source.mkdir()
            target.mkdir()
            profiles = SpeakerProfileStore(source / "speaker-profiles.json")
            profiles.add_confirmed_embedding("Alexander Yu", [1.0, 0.0])
            profiles.confirm_name_alias("Alexander Yu", "Alex Yu")
            package = root / "transfer.tfconfig"
            rejections = SampleRejectionStore(source / "speaker-sample-rejections.json")
            export_configuration(package, {}, [], profiles, rejections)

            destination = SpeakerProfileStore(target / "speaker-profiles.json")
            destination.add_confirmed_embedding("Alexander Yu", [0.0, 1.0])
            destination.save()
            import_configuration(package, target)

            imported = SpeakerProfileStore(target / "speaker-profiles.json")
            self.assertEqual(set(imported.profiles), {"Alex Yu"})
            self.assertEqual(len(imported.profiles["Alex Yu"]), 2)
            self.assertEqual(imported.canonical_name("Alexander Yu"), "Alex Yu")
