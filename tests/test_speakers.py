import tempfile
import unittest
import math
from pathlib import Path

from transcriptforge.models import Segment
from transcriptforge.speakers import SpeakerAnalysis, SpeakerCluster, SpeakerProfileStore, apply_speaker_names, cosine_similarity, fill_unknown_speakers_from_neighbors, refine_unresolved_clusters, remove_review_sample


class SpeakerTests(unittest.TestCase):
    def test_profile_round_trip_and_match(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SpeakerProfileStore(Path(directory) / "profiles.json")
            store.add_confirmed_embedding("Alex", [1.0, 0.0, 0.0]); store.save()
            loaded = SpeakerProfileStore(store.path)
            name, score = loaded.best_match([0.99, 0.01, 0.0])
            self.assertEqual(name, "Alex"); self.assertGreater(score, .99)

    def test_profile_metadata_is_saved_with_embedding(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SpeakerProfileStore(Path(directory) / "profiles.json")
            store.add_confirmed_embedding("Alex", [1.0, 0.0], metadata={"source": "meeting.wav", "quality": 0.8})
            loaded = SpeakerProfileStore(store.path)
            store.save()
            loaded = SpeakerProfileStore(store.path)
            self.assertEqual(loaded.embedding_metadata["Alex"][0]["source"], "meeting.wav")

    def test_match_margin_can_reject_ambiguous_speakers(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SpeakerProfileStore(Path(directory) / "profiles.json")
            store.add_confirmed_embedding("Alex", [1.0, 0.0]); store.add_confirmed_embedding("Blair", [0.99, 0.1])
            name, score, margin = store.best_match_with_margin([1.0, 0.05], threshold=0.0)
            self.assertIsNotNone(name); self.assertIsNotNone(score); self.assertLess(margin, 0.04)

    def test_confirmed_profile_keeps_distinct_samples_past_twenty(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SpeakerProfileStore(Path(directory) / "profiles.json")
            for index in range(21):
                angle = index * 0.2
                store.add_confirmed_embedding("Alex", [math.cos(angle), math.sin(angle), 0.0])
            self.assertGreaterEqual(len(store.profiles["Alex"]), 21)

    def test_training_embeddings_include_all_detected_cluster_samples(self):
        with tempfile.TemporaryDirectory() as directory:
            from transcriptforge.speakers import save_confirmed_profiles
            store = SpeakerProfileStore(Path(directory) / "profiles.json")
            cluster = SpeakerCluster("SPEAKER_01", [1.0, 0.0], [(0, 2), (3, 5), (6, 8)], [(0, 2)], None, None, [[1.0, 0.0]], [[1.0, 0.0], [0.99, 0.1], [0.98, 0.2]])
            save_confirmed_profiles(SpeakerAnalysis([cluster], []), {"SPEAKER_01": "Alex"}, store)
            self.assertEqual(len(store.profiles["Alex"]), 3)

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

    def test_removed_sample_keeps_training_quality_alignment(self):
        cluster = SpeakerCluster("SPEAKER_01", [1.0, 0.0], [(0, 2), (2, 4)], [(0, 2)], None, None, [[1.0, 0.0]], [[1.0, 0.0], [0.9, 0.1]], [0.8, 0.4])
        analysis = SpeakerAnalysis([cluster], [])
        remove_review_sample(analysis, cluster, 0)
        self.assertEqual(cluster.training_qualities, [0.4])

    def test_unknown_is_filled_only_when_neighbors_agree(self):
        segments = [Segment(0, 1, "one", speaker="Alex"), Segment(1, 2, "yes", speaker="Unknown"), Segment(2, 3, "two", speaker="Alex"), Segment(3, 4, "no", speaker="Unknown"), Segment(4, 5, "three", speaker="Blair")]
        self.assertEqual(fill_unknown_speakers_from_neighbors(segments), 1)
        self.assertEqual([segment.speaker for segment in segments], ["Alex", "Alex", "Alex", "Unknown", "Blair"])

    def test_cluster_without_remaining_samples_is_not_unresolved(self):
        cluster = SpeakerCluster("SPEAKER_01", [], [(0, 2)], [], None, None, [], [])
        path = Path(tempfile.mkdtemp()) / "profiles.json"
        names, unresolved, _ = refine_unresolved_clusters(SpeakerAnalysis([cluster], []), {}, SpeakerProfileStore(path))
        self.assertEqual(names, {})
        self.assertEqual(unresolved, [])
