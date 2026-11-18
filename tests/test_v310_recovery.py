"""One-button recovery, original research ZIP images, and sourced combat getters."""
import json
import struct
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from io import BytesIO
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'engine'))
from PIL import Image
from appearance_lab import scan_assets,prepare_appearance
from ship_viewer import export_viewer,read_obj
from gltf_export import export_glb
from mechanics_verified import client_armor,EVIDENCE
from engine.full_recovery import Recovery


def seven(n):
    out=[]
    while n>=128:
        out.append((n&127)|128);n>>=7
    return bytes(out+[n])


def tiny_xnb():
    reader=b'Microsoft.Xna.Framework.Content.Texture2DReader'
    p=seven(1)+seven(len(reader))+reader+struct.pack('<i',0)+seven(0)+seven(1)
    p+=struct.pack('<iiiii',0,2,2,1,16)+bytes([255,0,0,255]*4)
    return b'XNBw'+bytes([5,0])+struct.pack('<I',10+len(p))+p


class V310Tests(unittest.TestCase):
    def test_verified_client_armor_uses_raw_fractional_bonuses(self):
        v=client_armor(10,all_stat_fine=0.1,p_armor=0.2,m_armor=1.5)
        self.assertAlmostEqual(v['basic_armor'],9)
        self.assertAlmostEqual(v['client_armor'],12.3)
        self.assertFalse(v['authoritative_damage'])
        self.assertEqual(EVIDENCE['armor']['token'],'0x06001f6f')
        with self.assertRaises(ValueError):client_armor(10,all_stat_fine=1.5)

    def test_research_zip_images_are_not_extracted(self):
        with tempfile.TemporaryDirectory() as td:
            d=Path(td);archive=d/'WOSB-Research-Part-030.zip'
            img=BytesIO();Image.new('RGBA',(4,4),(50,90,130,255)).save(img,format='PNG')
            with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
                z.writestr('WOSB-AI-Handoff/Images/LooseFiles/Data/ModelTextures/Lod0/Ships/Vasa_hull.png',img.getvalue())
                z.writestr('WOSB-AI-Handoff/Images/LooseFiles/Data/ModelTextures/Lod0/Ships/Vasa_hull_hist.png',img.getvalue())
            matched=scan_assets(d)
            self.assertIn('vasa_hull',matched)
            self.assertIn('vasa_hull_hist',matched)
            mesh={'groups':[{'material':'Vasa_hull','name':'ShipCorpus_part0'}]}
            ship={'ID':70,'EnglishName':'Vasa'}
            result=prepare_appearance(ship,mesh,game_assets_root=d)
            self.assertIn('Vasa_hull',result['textures'])
            self.assertIn('Vasa_hull_hist',result['textures'])
            self.assertTrue(result['textures']['Vasa_hull']['data_uri'].startswith('data:image/png;base64,'))
            self.assertIn('WOSB-Research-Part-',result['textures']['Vasa_hull']['asset_source'])
            self.assertEqual(list(d.glob('*.png')),[])

    def test_viewer_exports_offline_texture_sidecar(self):
        with tempfile.TemporaryDirectory() as td:
            base=Path(td);archive=base/'WOSB-Research-Part-001.zip'
            buf=BytesIO();Image.new('RGB',(8,8),(0,120,200)).save(buf,format='PNG')
            with zipfile.ZipFile(archive,'w') as z:
                z.writestr('WOSB-AI-Handoff/Images/Data/ModelTextures/Lod0/Ships/Vasa_hull.png',buf.getvalue())
            obj=base/'tiny.obj'
            obj.write_text('v 0 0 0\nv 1 0 0\nv 0 1 0\nvt 0 0\nvt 1 0\nvt 0 1\n'
                           'o ShipCorpus_part0\nusemtl Vasa_hull\nf 1/1 2/2 3/3\n',encoding='utf-8')
            html=base/'Vasa.html'
            export_viewer(html,{'ID':70,'EnglishName':'Vasa'},obj,game_assets_root=base)
            content=html.read_text('utf-8')
            self.assertIn('Vasa-assets/',content)
            self.assertEqual(len(list((base/'Vasa-assets').glob('*.png'))),1)
            self.assertNotIn('data:image/png;base64,',content)

    def test_textured_glb_contains_gltf2_mesh_and_image(self):
        with tempfile.TemporaryDirectory() as td:
            base=Path(td)
            obj=base/'mesh.obj'
            obj.write_text('v 0 0 0\nv 1 0 0\nv 0 1 0\nvt 0 0\nvt 1 0\nvt 0 1\n'
                           'o ShipCorpus_part0\nusemtl Vasa_hull\nf 1/1 2/2 3/3\n',encoding='utf-8')
            png=base/'Vasa_hull.png'
            Image.new('RGBA',(4,4),(21,91,101,255)).save(png)
            mesh=read_obj(obj)
            out=base/'test.glb'
            appearance={'textures':{'Vasa_hull':{'data_uri':'Vasa_hull.png'}},'designs':[]}
            report=export_glb(mesh,appearance,out,asset_dir=base)
            raw=out.read_bytes()
            magic,version,declared=struct.unpack_from('<4sII',raw,0)
            self.assertEqual(magic,b'glTF')
            self.assertEqual(version,2)
            self.assertEqual(declared,len(raw))
            json_size,jtype=struct.unpack_from('<I4s',raw,12)
            self.assertEqual(jtype,b'JSON')
            parsed=json.loads(raw[20:20+json_size])
            self.assertEqual(len(parsed['images']),1)
            self.assertEqual(parsed['meshes'][0]['primitives'][0]['mode'],4)
            self.assertEqual(report['visual_triangles'],1)
            self.assertEqual(report['embedded_textures'],1)

    def test_synthetic_xnb_decodes_and_resumes(self):
        with tempfile.TemporaryDirectory() as td:
            base=Path(td);game=base/'game';game.mkdir()
            out=base/'output';xnb=game/'Data/ModelTextures/Lod0/Test.xnb'
            xnb.parent.mkdir(parents=True);xnb.write_bytes(tiny_xnb())
            recovery=Recovery(game,out,catalog=False,code=False,preserve=False,payloads=True)
            result=recovery.run()
            self.assertEqual(result['result'],'completed')
            row=json.loads((out/'Reports/AssetLedger.jsonl').read_text().strip())
            self.assertEqual(row['status'],'decoded')
            self.assertEqual(row['kind'],'texture')
            self.assertTrue((out/row['output']).exists())
            with Image.open(out/row['output']) as image:self.assertEqual(image.size,(2,2))
            recovery=Recovery(game,out,catalog=False,code=False,preserve=False,payloads=True)
            again=recovery.run()
            self.assertEqual(again['result'],'completed')
            self.assertEqual(json.loads((out/'Reports/AssetLedger.jsonl').read_text().strip())['sha256'],row['sha256'])

    def test_output_inside_game_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            base=Path(td);game=base/'game';game.mkdir()
            with self.assertRaisesRegex(ValueError,'outside'):
                Recovery(game,game/'out',catalog=False,code=False)

    def test_research_zip_does_not_trust_arbitrary_image_entries(self):
        with tempfile.TemporaryDirectory() as td:
            archive=Path(td)/'WOSB-Research-Part-001.zip'
            with zipfile.ZipFile(archive,'w') as z:
                z.writestr('../outside.png',b'foo')
                z.writestr('WOSB-AI-Handoff/Images/../../bad.png',b'foo')
            assets=scan_assets(td)
            self.assertNotIn('outside',assets)
            self.assertNotIn('bad',assets)

if __name__=='__main__':unittest.main()
