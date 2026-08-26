import tempfile
import unittest
from pathlib import Path

from transcriptforge.models import Segment
from transcriptforge.speakers import SpeakerAnalysis, SpeakerCluster, SpeakerProfileStore, apply_speaker_names, cosine_similarity, refine_unresolved_clusters, remove_review_sample


class SpeakerTests(unittest.TestCase):
    def test_profile_round_trip_and_match(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SpeakerProfileStore(Path(directory) / "profiles.json")
            store.add_confirmed_embedding("Alex", [1.0, 0.0, 0.0]); store.save()
            loaded = SpeakerProfileStore(store.path)
            name, score = loaded.best_match([0.99, 0.01, 0.0])
            self.assertEqual(name, "Alex"); self.assertGreater(score, .99)

    def test_confirmed_name_is_applied_to_overlapping_segment(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SpeakerProfileStore(Path(directory) / "profiles.json")
            analysis = SpeakerAnalysis([SpeakerCluster("SPEAKER_01", [1.0, 0.0], [(0.0, 4.0)], [(0.0, 3.0)])], [(0.0, 4.0, "SPEAKER_01")])
            segments = [Segment(1.0, 2.0, "Hello")]
            apply_speaker_names(segments, analysis, {"SPEAKER_01": "Alex"}, store)
            self.assertEqual(segments[0].speaker, "Alex")
            self.assertEqual(SpeakerProfileStore(store.path).best_match([1.0, 0.0])[0], "Alex")

    def test_cosine_similarity_handles_orthogonal_vectors(self):
        self.assertEqual(cosine_similarity([1, 0], [0, 1]), 0.0)

    def test_refinement_resolves_blank_cluster_from_confirmed_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SpeakerProfileStore(Path(directory) / "profiles.json")
            store.add_confirmed_embedding("Alex", [1.0, 0.0]); store.save()
            analysis = SpeakerAnalysis([
                SpeakerCluster("SPEAKER_01", [1.0, 0.0], [(0, 2)], [(0, 2)]),
                SpeakerCluster("SPEAKER_02", [0.99, 0.1], [(3, 5)], [(3, 5)]),
            ], [])
            names, unresolved, _ = refine_unresolved_clusters(analysis, {"SPEAKER_01": "Alex", "SPEAKER_02": ""}, store)
            self.assertEqual(names["SPEAKER_02"], "Alex")
            self.assertEqual(unresolved, [])

    def test_unknown_is_not_auto_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SpeakerProfileStore(Path(directory) / "profiles.json")
            store.add_confirmed_embedding("Alex", [1.0, 0.0]); store.save()
            analysis = SpeakerAnalysis([SpeakerCluster("SPEAKER_01", [1.0, 0.0], [(0, 2)], [(0, 2)])], [])
            names, unresolved, _ = refine_unresolved_clusters(analysis, {"SPEAKER_01": "Unknown"}, store)
            self.assertEqual(names["SPEAKER_01"], "Unknown")
            self.assertEqual(unresolved, [])

    def test_removed_sample_embedding_is_not_saved_to_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SpeakerProfileStore(Path(directory) / "profiles.json")
            cluster = SpeakerCluster("SPEAKER_01", [1.0, 0.0], [(0, 4)], [(0, 2), (2, 4)], None, None, [[1.0, 0.0], [0.0, 1.0]])
            cluster.samples.pop(1); cluster.sample_embeddings.pop(1)
            save_store = SpeakerProfileStore(store.path)
            from transcriptforge.speakers import save_confirmed_profiles
            save_confirmed_profiles(SpeakerAnalysis([cluster], []), {"SPEAKER_01": "Alex"}, save_store)
            self.assertEqual(len(SpeakerProfileStore(store.path).profiles["Alex"]), 1)
            self.assertEqual(SpeakerProfileStore(store.path).profiles["Alex"][0], [1.0, 0.0])

    def test_removed_sample_is_removed_from_current_speaker_intervals(self):
        cluster = SpeakerCluster("SPEAKER_01", [1.0, 0.0], [(0, 2), (2, 4)], [(0, 2), (2, 4)], None, None, [[1.0, 0.0], [0.9, 0.1]])
        analysis = SpeakerAnalysis([cluster], [(0, 2, "SPEAKER_01"), (2, 4, "SPEAKER_01")])
        self.assertEqual(remove_review_sample(analysis, cluster, 0), (0, 2))
        self.assertEqual(cluster.intervals, [(2, 4)])
        self.assertEqual(analysis.interval_labels, [(2, 4, "SPEAKER_01")])
