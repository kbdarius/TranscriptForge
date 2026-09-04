import tempfile
import unittest
import math
from pathlib import Path

import numpy as np

from transcriptforge.models import Segment
from transcriptforge.speakers import SpeakerAnalysis, SpeakerCluster, SpeakerProfileStore, _cluster_observations, apply_speaker_names, cosine_similarity, fill_unknown_speakers_from_neighbors, refine_unresolved_clusters, remove_review_sample


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

    def test_profile_migration_keeps_archive_and_creates_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profiles.json"
            path.write_text('{"version": 2, "profiles": {"Alex": [[1.0, 0.0]]}, "embedding_metadata": {}}', encoding="utf-8")
            store = SpeakerProfileStore(path)
            self.assertEqual(store.schema_version, 2)
            store.save()
            loaded = SpeakerProfileStore(path)
            self.assertEqual(loaded.schema_version, 3)
            self.assertEqual(len(loaded.profiles["Alex"]), 1)
            self.assertTrue(path.with_name("profiles.json.v2.bak").is_file())

    def test_active_profile_is_bounded_without_dropping_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SpeakerProfileStore(Path(directory) / "profiles.json")
            for index in range(25):
                angle = index * 0.25
                store.add_confirmed_embedding("Alex", [math.cos(angle), math.sin(angle)], metadata={"source": "one-meeting", "quality": 0.8})
            store.save()
            loaded = SpeakerProfileStore(store.path)
            self.assertEqual(len(loaded.profiles["Alex"]), 25)
            self.assertLessEqual(len(loaded.active_vectors("Alex")), 12)

    def test_match_margin_can_reject_ambiguous_speakers(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SpeakerProfileStore(Path(directory) / "profiles.json")
            store.add_confirmed_embedding("Alex", [1.0, 0.0]); store.add_confirmed_embedding("Blair", [0.99, 0.1])
            name, score, margin = store.best_match_with_margin([1.0, 0.05], threshold=0.0)
            self.assertIsNotNone(name); self.assertIsNotNone(score); self.assertLess(margin, 0.04)

    def test_matching_uses_robust_profile_score_instead_of_one_outlier(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SpeakerProfileStore(Path(directory) / "profiles.json")
            store.profiles = {"Alex": [[1.0, 0.0]] * 8 + [[0.0, 1.0]], "Blair": [[0.7, 0.7]]}
            store.embedding_metadata = {"Alex": [{"quality": 0.8}] * 9, "Blair": [{"quality": 0.8}]}
            store.rebuild_active_indices()
            self.assertEqual(store.best_match([1.0, 0.0], threshold=0.78)[0], "Alex")

    def test_confirmed_profile_keeps_distinct_samples_past_twenty(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SpeakerProfileStore(Path(directory) / "profiles.json")
            for index in range(21):
                angle = index * 0.2
                store.add_confirmed_embedding("Alex", [math.cos(angle), math.sin(angle), 0.0])
            self.assertGreaterEqual(len(store.profiles["Alex"]), 21)

    def test_training_uses_only_samples_the_user_reviewed(self):
        with tempfile.TemporaryDirectory() as directory:
            from transcriptforge.speakers import save_confirmed_profiles
            store = SpeakerProfileStore(Path(directory) / "profiles.json")
            cluster = SpeakerCluster("SPEAKER_01", [1.0, 0.0], [(0, 2), (3, 5), (6, 8)], [(0, 2)], None, None, [[1.0, 0.0]], [[1.0, 0.0], [0.99, 0.1], [0.98, 0.2]])
            save_confirmed_profiles(SpeakerAnalysis([cluster], []), {"SPEAKER_01": "Alex"}, store)
            self.assertEqual(len(store.profiles["Alex"]), 1)
            self.assertTrue(store.embedding_metadata["Alex"][0]["reviewed"])

    def test_profile_guided_clustering_keeps_known_speakers_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SpeakerProfileStore(Path(directory) / "profiles.json")
            store.profiles = {
                "Alex": [[1.0, 0.0, 0.0], [0.99, 0.05, 0.0]],
                "Blair": [[0.0, 1.0, 0.0], [0.05, 0.99, 0.0]],
            }
            store.embedding_metadata = {"Alex": [{}, {}], "Blair": [{}, {}]}
            store.rebuild_active_indices()
            observations = [
                (0.0, 2.0, np.array([1.0, 0.01, 0.0]), 0.8),
                (2.0, 4.0, np.array([0.98, 0.08, 0.0]), 0.7),
                (4.0, 6.0, np.array([0.01, 1.0, 0.0]), 0.8),
                (6.0, 8.0, np.array([0.08, 0.98, 0.0]), 0.7),
            ]
            clusters = _cluster_observations(observations, store)
            self.assertEqual({cluster.get("profile_name") for cluster in clusters}, {"Alex", "Blair"})
            self.assertEqual(sorted(len(cluster["intervals"]) for cluster in clusters), [2, 2])

    def test_current_source_can_be_excluded_and_quarantined(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profiles.json"
            store = SpeakerProfileStore(path)
            store.add_confirmed_embedding("Alex", [1.0, 0.0], metadata={"source": "bad-meeting.mp4", "quality": 0.9})
            store.add_confirmed_embedding("Alex", [0.0, 1.0], metadata={"source": "good-meeting.mp4", "quality": 0.8})
            store.save()
            self.assertEqual(len(store.active_vectors("Alex", ["bad-meeting.mp4"])), 1)
            self.assertEqual(store.quarantine_source("bad-meeting.mp4", ["Alex"], "mixed cluster"), 1)
            loaded = SpeakerProfileStore(path)
            self.assertEqual(len(loaded.profiles["Alex"]), 2)
            self.assertEqual(len(loaded.active_vectors("Alex")), 1)
            self.assertEqual(loaded.embedding_metadata["Alex"][0]["exclusion_reason"], "mixed cluster")

    def test_cluster_can_be_labeled_without_learning_samples(self):
        with tempfile.TemporaryDirectory() as directory:
            from transcriptforge.speakers import save_confirmed_profiles
            store = SpeakerProfileStore(Path(directory) / "profiles.json")
            cluster = SpeakerCluster("SPEAKER_01", [1.0, 0.0], [(0, 2)], [(0, 2)], None, None, [[1.0, 0.0]], [[1.0, 0.0]])
            save_confirmed_profiles(SpeakerAnalysis([cluster], []), {"SPEAKER_01": "Alex"}, store, learn={"SPEAKER_01": False})
            self.assertNotIn("Alex", store.profiles)

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
