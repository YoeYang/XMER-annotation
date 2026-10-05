import copy
import json
import tempfile
import unittest
from pathlib import Path

from server import ANNOTATORS, SCHEMA, connect, initialize, save_record, validate


def valid_payload():
    return {
        'schema_version': SCHEMA, 'anchor_version': SCHEMA,
        'subject_id': 'CPM-S0001:subject-1', 'event_id': 'CPM-S0001:event-1', 'modality': 'audiovisual',
        'card': {'subject': '队长', 'event': '比赛失利', 'goal': '', 'role': ''},
        'checks': {'subject': 'confirmed', 'event': 'confirmed', 'goal': 'unknown', 'role': 'unknown'},
        'event_location': 'outside', 'score_window': [0, 12],
        'evidence': [{'id': 'E01', 'modality': 'text', 'span': [1, 8], 'observation': '下一场调整战术', 'verified': True}],
        'ratings': {dim: {'state': 'unknown', 'value': None, 'evidence_ids': [], 'mixed': False, 'note': ''} for dim in 'RICN'},
        'conflict': {'status': 'uncertain', 'candidate_window': [2.4, 4.8], 'candidate_source': 'mock-candidate-v1'},
        'constraint': {'status': 'unknown'}, 'dynamic': {'status': 'unchanged'},
        'revision_reason': '',
    }


class CPMTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'cpm.sqlite3'
        initialize(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def test_same_360_samples_assigned_to_both_annotators(self):
        with connect(self.path) as db:
            clips = [set(r[0] for r in db.execute('SELECT clip_id FROM assignments WHERE annotator_id=?', (a,))) for a in ANNOTATORS]
            self.assertEqual(len(clips[0]), 360)
            self.assertEqual(clips[0], clips[1])
            self.assertEqual(db.execute('SELECT COUNT(*) FROM assignments').fetchone()[0], 720)

    def test_seed_is_idempotent(self):
        initialize(self.path)
        with connect(self.path) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM samples').fetchone()[0], 360)

    def test_unknown_is_null_and_zero_is_known(self):
        p = valid_payload()
        self.assertEqual(validate(p, 12), [])
        p['ratings']['I'] = {'state': 'known', 'value': 0, 'evidence_ids': ['E01']}
        self.assertEqual(validate(p, 12), [])
        p['ratings']['I'] = {'state': 'unknown', 'value': 0}
        self.assertTrue(validate(p, 12))

    def test_numerical_scores_require_verified_evidence(self):
        p = valid_payload()
        p['ratings']['C'] = {'state': 'known', 'value': 2, 'evidence_ids': ['E01']}
        p['evidence'][0]['verified'] = False
        self.assertTrue(validate(p, 12))

    def test_unset_ratings_and_invalid_windows_rejected(self):
        for interval in ([-1, 12], [4, 3], [0, 13], [0, 0], [0, float('nan')]):
            p = valid_payload()
            p['score_window'] = interval
            self.assertTrue(validate(p, 12))
        p = valid_payload()
        p['ratings']['R']['state'] = 'unset'
        self.assertTrue(validate(p, 12))

    def test_conflict_requires_two_verified_modalities(self):
        p = valid_payload()
        p['conflict'] |= {'status': 'confirmed', 'modalities': ['text', 'face'], 'reviewed_window': [2, 5]}
        self.assertTrue(validate(p, 12))
        p['evidence'].append({'id': 'E02', 'modality': 'face', 'span': [2, 5], 'observation': '嘴角下垂', 'verified': True})
        self.assertEqual(validate(p, 12), [])

    def test_mixed_evaluation_needs_note(self):
        p = valid_payload()
        p['ratings']['I']['mixed'] = True
        self.assertTrue(validate(p, 12))

    def test_dynamic_and_post_change_window(self):
        p = valid_payload()
        p['dynamic'] = {'status': 'changed', 'time': 5, 'modalities': ['face'], 'description': '表情改变', 'updated_ratings': copy.deepcopy(p['ratings']), 'score_window': [3, 12]}
        self.assertTrue(validate(p, 12))
        p['dynamic']['score_window'] = [5, 12]
        self.assertEqual(validate(p, 12), [])

    def test_records_are_append_only_and_annotators_independent(self):
        p = valid_payload()
        with connect(self.path) as db:
            save_record(db, 'CPM-01', 'CPM-S0001', 'draft', p)
            save_record(db, 'CPM-01', 'CPM-S0001', 'submitted', p)
            save_record(db, 'CPM-02', 'CPM-S0001', 'submitted', p)
            rows = db.execute('SELECT * FROM records ORDER BY id').fetchall()
            self.assertEqual([r['attempt_no'] for r in rows], [1, 2, 1])
            self.assertEqual(json.loads(rows[0]['payload']), p)

    def test_submitted_revision_requires_reason(self):
        p = valid_payload()
        with connect(self.path) as db:
            save_record(db, 'CPM-01', 'CPM-S0001', 'submitted', p)
            with self.assertRaises(ValueError):
                save_record(db, 'CPM-01', 'CPM-S0001', 'draft', p)
            db.rollback()
            p['revision_reason'] = '重新核对时间证据'
            save_record(db, 'CPM-01', 'CPM-S0001', 'submitted', p)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM records').fetchone()[0], 2)

    def test_invalid_submission_never_persisted(self):
        with connect(self.path) as db:
            with self.assertRaises(ValueError):
                save_record(db, 'CPM-01', 'CPM-S0001', 'submitted', {})
            self.assertEqual(db.execute('SELECT COUNT(*) FROM records').fetchone()[0], 0)

    def test_unassigned_task_rejected(self):
        with connect(self.path) as db:
            with self.assertRaises(ValueError):
                save_record(db, 'CPM-03', 'CPM-S0001', 'draft', {})
            with self.assertRaises(ValueError):
                save_record(db, 'CPM-01', 'MISSING', 'draft', {})

    def test_original_candidate_and_schema_cannot_be_replaced(self):
        for field in ('candidate_window', 'candidate_source'):
            p = valid_payload()
            p['conflict'][field] = [1, 2] if field == 'candidate_window' else 'changed'
            with connect(self.path) as db:
                with self.assertRaises(ValueError):
                    save_record(db, 'CPM-01', 'CPM-S0001', 'draft', p)
        p = valid_payload()
        p['schema_version'] = 'other'
        with connect(self.path) as db:
            with self.assertRaises(ValueError):
                save_record(db, 'CPM-01', 'CPM-S0001', 'draft', p)

    def test_empty_dynamic_window_returns_validation_error(self):
        p = valid_payload()
        p['dynamic'] = {'status': 'changed', 'time': 5, 'modalities': ['face'], 'description': '改变', 'updated_ratings': copy.deepcopy(p['ratings']), 'score_window': []}
        self.assertTrue(validate(p, 12))


if __name__ == '__main__':
    unittest.main()
