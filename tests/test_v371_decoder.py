"""Regression tests for the Windows CAB output finder. Run with: py -3.13 -m unittest discover -s tests -p test_v371_decoder.py"""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, mock
import os
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine import xnb_payload

class TestWindowsDecoder(TestCase):
    def test_detects_unexpected_member_filename(self):
        def extract(cmd, **kwargs):
            out = Path(cmd[-1]); (out / 'DATA').write_bytes(b'abcd')
            return subprocess.CompletedProcess(cmd, 0, '1 file expanded', '')
        with mock.patch.object(xnb_payload.Path, 'exists', return_value=True), \
             mock.patch.object(xnb_payload.subprocess, 'run', side_effect=extract):
            self.assertEqual(xnb_payload._windows_decode(b'MSCF', 4), b'abcd')

    def test_rejects_wrong_payload_size(self):
        def extract(cmd, **kwargs):
            out = Path(cmd[-1]); (out / 'data').write_bytes(b'wrong')
            return subprocess.CompletedProcess(cmd, 0, 'expanded', '')
        with mock.patch.object(xnb_payload.Path, 'exists', return_value=True), \
             mock.patch.object(xnb_payload.subprocess, 'run', side_effect=extract):
            with self.assertRaisesRegex(xnb_payload.XNBError, 'expected=4'):
                xnb_payload._windows_decode(b'MSCF', 4)
