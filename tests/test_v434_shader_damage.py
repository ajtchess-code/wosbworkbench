"""v4.3.4: read-only compiled FX audit and evidence-labeled damage proxies."""
import json
import math
import struct
import tempfile
import unittest
from pathlib import Path
from damage_hypotheses import lookup,calculate
from shader_recovery import inspect_effect_bytes,inspect_shader_file,audit_effects


def seven(value):
    out=bytearray()
    while value>=128:
        out.append((value&127)|128)
        value>>=7
    out.append(value)
    return bytes(out)


def effect_xnb(bytecode):
    name=b'Microsoft.Xna.Framework.Content.EffectReader, Microsoft.Xna.Framework.Graphics'
    body=seven(1)+seven(len(name))+name+struct.pack('<i',0)+seven(0)+seven(1)
    body+=struct.pack('<i',len(bytecode))+bytecode
    return b'XNBw'+bytes([5,0])+struct.pack('<I',10+len(body))+body


class TestEffectAudit(unittest.TestCase):
    def test_fake_fx_not_accepted_as_reconstructed(self):
        result=inspect_effect_bytes(b'ABCD-CTAB-TextureDiffuse-MGFX')
        self.assertIn('CTAB',[x['marker'] for x in result['binary_markers']])
        self.assertFalse(result['runnable_shader_recovered'])
        self.assertFalse(result['parameters_parsed'])

    def test_effect_xnb_with_export(self):
        with tempfile.TemporaryDirectory() as t:
            base=Path(t)/'game';shaders=base/'Data'/'Shaders';shaders.mkdir(parents=True)
            (shaders/'Test.xnb').write_bytes(effect_xnb(b'FX-CTAB-FakeTest'))
            out=Path(t)/'diagnostics'
            filename,report=audit_effects(base,out,export_compiled=True)
            self.assertTrue(filename.exists())
            self.assertEqual(report['status_counts']['compiled_blob_extracted'],1)
            self.assertEqual((out/'CompiledEffects/Data/Shaders/Test.fxb').read_bytes(),b'FX-CTAB-FakeTest')
            self.assertTrue(report['effects'][0]['candidate_strings'])
            self.assertNotIn('raw_bytecode',report['effects'][0])

    def test_invalid_xnb_unmarked(self):
        with tempfile.TemporaryDirectory() as t:
            base=Path(t)/'Shaders';base.mkdir()
            bad=base/'broken.xnb';bad.write_bytes(b'not xnb')
            report=inspect_shader_file(bad,base)
            self.assertEqual(report['status'],'unsupported_or_failed')


class TestCombatProxy(unittest.TestCase):
    def test_catalog_fields(self):
        d=json.loads((Path(__file__).resolve().parents[1]/'Research-Ballistics-Catalog.json').read_text(encoding='utf-8'))['datasets']
        cannon=lookup(d['Cannons'],'42-pdr Carronade')
        ammo=lookup(d['CannonBalls'],'Round Shot')
        self.assertEqual(cannon['Penetration'],26.5)
        self.assertEqual(ammo['DamageFactor'],1)
        result=calculate(cannon,ammo,target_armor=12,angle_deg=0)
        self.assertEqual(result['hypotheses']['total_penetration_additive'],26.5)
        self.assertEqual(result['hypotheses']['relative_poundage_damage_index'],42)
        self.assertNotIn('calibrated_alternatives_hp',result)
        self.assertEqual(result['confidence']['poundage_to_HP'],'unknown')

    def test_obliquity_hypotheses_only(self):
        cannon={'Penetration':26.5,'Poundage':42};ammo={'Penetration':0,'DamageFactor':1}
        straight=calculate(cannon,ammo,target_armor=12)
        angled=calculate(cannon,ammo,target_armor=12,angle_deg=70)
        self.assertGreater(angled['hypotheses']['effective_armor_cosine'],straight['hypotheses']['effective_armor_cosine'])
        self.assertEqual(straight['hypotheses']['threshold_penetration_gate'],1)
        self.assertEqual(angled['hypotheses']['threshold_penetration_gate'],0)
        self.assertEqual(angled['confidence']['obliquity_penetration_laws'],'speculative — both alternatives unvalidated')

    def test_reference_and_invalid(self):
        cannon={'Penetration':26.5,'Poundage':42};ammo={'Penetration':0,'DamageFactor':1}
        r=calculate(cannon,ammo,target_armor=12,measured_reference_hp_per_hit=100,
                    direction='bow',bow_protection_percent=20,hit_count=2)
        self.assertEqual(r['calibrated_alternatives_hp']['threshold'],160)
        with self.assertRaises(ValueError):calculate(cannon,ammo,target_armor=12,angle_deg=90)
        with self.assertRaises(ValueError):calculate(cannon,ammo,target_armor=12,hit_count=0)

if __name__=='__main__':unittest.main()
