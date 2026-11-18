"""Update package safety, backup and rollback tests; synthetic fixture only."""
import importlib.util
import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import offline_updates as updates

spec=importlib.util.spec_from_file_location('make_update',ROOT/'packaging'/'Make-Offline-Update.py')
maker=importlib.util.module_from_spec(spec)
spec.loader.exec_module(maker)

class OfflineUpdatesTests(unittest.TestCase):
    def setup_fixture(self, folder):
        root=Path(folder)
        install=root/'Install'; install.mkdir()
        (install/'desktop_main.py').write_text('old',encoding='utf8')
        (install/'workbench_db.py').write_text('old db code',encoding='utf8')
        data=root/'UserData';data.mkdir()
        (data/'Workbench.sqlite3').write_bytes(b'user wiki must survive')
        new=root/'New';new.mkdir()
        (new/'desktop_main.py').write_text('new',encoding='utf8')
        (new/'workbench_db.py').write_text('new db code',encoding='utf8')
        zipfile_path=root/'WoSB-Update.zip'
        maker.make_archive(new,zipfile_path,'3.2.1','3.2.0')
        return root,install,data,new,zipfile_path

    def test_apply_and_back_up_preserves_wiki(self):
        with tempfile.TemporaryDirectory() as td:
            root,install,data,new,zipfile_path=self.setup_fixture(td)
            info=updates.inspect_update_zip(zipfile_path,'3.2.0')
            self.assertEqual(info.version,'3.2.1')
            self.assertEqual(len(info.files),2)
            backup=root/'Backup'
            updates.apply_verified_update(zipfile_path,install,backup,'3.2.0')
            self.assertEqual((install/'desktop_main.py').read_text(),'new')
            self.assertEqual((backup/'original'/'desktop_main.py').read_text(),'old')
            self.assertEqual((data/'Workbench.sqlite3').read_bytes(),b'user wiki must survive')

    def test_reject_downgrade_and_missing_minimum(self):
        with tempfile.TemporaryDirectory() as td:
            root,install,data,new,zipfile_path=self.setup_fixture(td)
            with self.assertRaisesRegex(ValueError,'newer'):
                updates.inspect_update_zip(zipfile_path,'3.2.2')
            with self.assertRaisesRegex(ValueError,'requires'):
                updates.inspect_update_zip(zipfile_path,'3.1.9')

    def test_reject_invalid_contents(self):
        with tempfile.TemporaryDirectory() as td:
            root,install,data,new,zipfile_path=self.setup_fixture(td)
            with zipfile.ZipFile(zipfile_path,'a') as z:
                z.writestr('payload/../../etc/something',b'bad')
            with self.assertRaisesRegex(ValueError,'Unsafe'):
                updates.inspect_update_zip(zipfile_path,'3.2.0')

    def test_reject_tampered_hash(self):
        with tempfile.TemporaryDirectory() as td:
            root,install,data,new,zipfile_path=self.setup_fixture(td)
            with zipfile.ZipFile(zipfile_path,'r') as z:
                contents={item.filename:z.read(item.filename) for item in z.infolist()}
            manifest=json.loads(contents['wosb-update.json'])
            manifest['files'][0]['sha256']='0'*64
            contents['wosb-update.json']=json.dumps(manifest).encode()
            with zipfile.ZipFile(zipfile_path,'w') as z:
                for name,blob in contents.items():z.writestr(name,blob)
            with self.assertRaisesRegex(ValueError,'SHA-256'):
                updates.inspect_update_zip(zipfile_path,'3.2.0')

    def test_rollback_if_replace_fails(self):
        with tempfile.TemporaryDirectory() as td:
            root,install,data,new,zipfile_path=self.setup_fixture(td)
            original_replace=updates.os.replace
            calls=[0]
            def fail_after_one(source,target):
                calls[0]+=1
                if calls[0]==2:raise OSError('simulated locked DLL')
                return original_replace(source,target)
            with patch.object(updates.os,'replace',side_effect=fail_after_one):
                with self.assertRaisesRegex(OSError,'simulated locked'):
                    updates.apply_verified_update(zipfile_path,install,root/'Backup','3.2.0')
            self.assertEqual((install/'desktop_main.py').read_text(),'old')
            self.assertEqual((install/'workbench_db.py').read_text(),'old db code')
            self.assertEqual((data/'Workbench.sqlite3').read_bytes(),b'user wiki must survive')

    def test_changed_only_release(self):
        with tempfile.TemporaryDirectory() as td:
            root,install,data,new,zipfile_path=self.setup_fixture(td)
            (install/'desktop_main.py').write_text('new',encoding='utf8')
            incremental=root/'Incremental.zip'
            maker.make_archive(new,incremental,'3.2.1','3.2.0',previous=install)
            info=updates.inspect_update_zip(incremental,'3.2.0')
            self.assertEqual([row[0] for row in info.files],['workbench_db.py'])

if __name__=='__main__':unittest.main()
