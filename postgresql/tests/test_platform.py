import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch
s=importlib.util.spec_from_file_location('platform_db',Path(__file__).parents[1]/'scripts/platform.py')
p=importlib.util.module_from_spec(s);s.loader.exec_module(p)
class Tests(unittest.TestCase):
    def test_identifiers_cannot_escape_sql(self):
        for value in ['a;DROP DATABASE postgres', 'x"', 'a'*64, 'production-db', '', '1abc']:
            with self.assertRaises(ValueError): p.identifier(value)
    def test_preview_recreation_has_different_identity(self):
        a=p.preview_identity('hkh-pr-123','11111111-1111-1111-1111-111111111111')[1]
        b=p.preview_identity('hkh-pr-123','22222222-2222-2222-2222-222222222222')[1]
        self.assertNotEqual(a,b)
        for ns in ['hkh','hkh-acceptance','postgres-production','hkh-pr-123-other','unknown-pr-1']:
            with self.assertRaises(ValueError): p.preview_identity(ns,'11111111-1111-1111-1111-111111111111')
    def test_newsfeed_preview_is_separate(self):
        app,db=p.preview_identity('pnf-pr-1','11111111-1111-1111-1111-111111111111')
        self.assertEqual('pnf',app)
        self.assertTrue(db.startswith('pnf_pr_1_'))
    def test_retention_keeps_last_good_and_recent_points(self):
        now=1800000000
        items=[{'run':str(n),'epoch':now-n*86400} for n in range(500)]
        keep=p.select_retained(items,now)
        self.assertTrue({str(n) for n in range(31)} <= keep)
        self.assertLess(len(keep),60)
        self.assertEqual({'old'},p.select_retained([{'run':'old','epoch':1}],now))
    def test_secret_is_stable_per_uid_and_different_after_reopen(self):
        self.assertEqual(p.preview_password('key','a'),p.preview_password('key','a'))
        self.assertNotEqual(p.preview_password('key','a'),p.preview_password('key','b'))
    def test_errors_never_expose_stderr(self):
        import subprocess
        with patch.object(p.subprocess,'run',return_value=subprocess.CompletedProcess([],1,b'',b'PASSWORD secret_personal_data')):
            with self.assertRaisesRegex(RuntimeError,r'^psql failed \(exit 1\)$'): p.run(['psql'])
if __name__=='__main__': unittest.main()
