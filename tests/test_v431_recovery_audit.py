"""Source-based regression checks for audit fixes derived from two client scans."""
import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'engine'))
from engine.full_recovery import Recovery,asset_class,root_reader_name
from engine.xnb_images import spritefont_atlas,effect_blob
from engine.xnb_geometry import parse_model_header,parse_geometry


def seven(n):
    o=[]
    while n>=128:o.append((n&127)|128);n>>=7
    return bytes(o+[n])


def xnb(readers,root,body,shared=0):
    blob=seven(len(readers))
    for name in readers:
        b=name.encode('utf-8');blob+=seven(len(b))+b+struct.pack('<i',0)
    blob+=seven(shared)+seven(root)+body
    return b'XNBw'+bytes((5,0))+struct.pack('<I',10+len(blob))+blob


class RecoveryAuditTests(unittest.TestCase):
    def test_sprite_font_nested_texture_not_top_level_texture(self):
        names=['Microsoft.Xna.Framework.Content.SpriteFontReader',
               'Microsoft.Xna.Framework.Content.Texture2DReader']
        self.assertEqual(asset_class(names,'fonts/Test.xnb',1),'font')
        self.assertEqual(asset_class(names,'textures/Test.xnb',2),'texture')
        self.assertEqual(root_reader_name(names,99),'')

    def test_sprite_font_glyph_atlas_recovery(self):
        readers=['Microsoft.Xna.Framework.Content.SpriteFontReader',
                 'Microsoft.Xna.Framework.Content.Texture2DReader']
        # Nested object ID 2 then a 2x2, four-channel uncompressed atlas.
        body=seven(2)+struct.pack('<iiiii',0,2,2,1,16)+bytes([10,20,30,255]*4)
        blob=xnb(readers,1,body)
        image,info=spritefont_atlas(blob)
        self.assertEqual(image.size,(2,2))
        self.assertEqual(info['asset_type'],'SpriteFont')
        self.assertTrue(info['atlas_only'])
        with tempfile.TemporaryDirectory() as td:
            g=Path(td)/'game';g.mkdir();x=(g/'font.xnb');x.write_bytes(blob)
            result=Recovery(g,Path(td)/'out',catalog=False,code=False,payloads=False).run()
            self.assertEqual(result['asset_status_counts'][0]['kind'],'font')
            self.assertEqual(result['assets']['counts']['decoded'],1)

    def test_effect_archive_keeps_compiled_blob_distinct_from_shader_source(self):
        readers=['Microsoft.Xna.Framework.Content.EffectReader']
        original=b'MGFX-testing-no-source'
        blob=xnb(readers,1,struct.pack('<i',len(original))+original)
        binary,info=effect_blob(blob)
        self.assertEqual(binary,original)
        self.assertFalse(info['shader_source_reconstructed'])
        with tempfile.TemporaryDirectory() as td:
            game=Path(td)/'game';game.mkdir();(game/'test_effect.xnb').write_bytes(blob)
            out=Path(td)/'out'
            report=Recovery(game,out,catalog=False,code=False,payloads=False).run()
            self.assertEqual(report['assets']['counts']['unsupported'],1)
            asset=json.loads((out/'Reports/AssetLedger.jsonl').read_text().strip())
            self.assertTrue((out/asset['compiled_effect_export']).exists())

    def test_optional_null_effect_reference_is_allowed_in_model_header(self):
        readers=['Microsoft.Xna.Framework.Content.ModelReader',
            'Microsoft.Xna.Framework.Content.StringReader',
            'UWModelMeshPartTag','SegmentTextureInfoTag',
            'Microsoft.Xna.Framework.Content.VertexBufferReader',
            'Microsoft.Xna.Framework.Content.IndexBufferReader']
        def name(text):
            value=text.encode('utf-8');return seven(2)+seven(len(value))+value
        identity=(1.,0,0,0, 0,1.,0,0, 0,0,1.,0, 0,0,0,1.)
        body=struct.pack('<I',1)+name('root')+struct.pack('<16f',*identity)
        body+=seven(0)+struct.pack('<I',0)
        body+=struct.pack('<i',1)+name('frame')+seven(0)
        body+=struct.pack('<4f',0,0,0,1)+seven(0)+struct.pack('<i',1)
        body+=struct.pack('<iiii',0,3,0,1)+seven(0)+seven(1)+seven(2)+seven(0)
        metadata=parse_model_header(xnb(readers,1,body,shared=3)[10:])
        self.assertEqual(metadata['parts'][0]['effects_ref'],0)
        self.assertEqual(metadata['parts'][0]['triangle_count'],1)
        # A complete, bounded vertex/index buffer should still parse despite
        # the absent optional effect object.
        vtx=seven(5)+struct.pack('<II',12,1)+struct.pack('<IIII',0,2,0,0)
        vtx+=struct.pack('<I',3)+struct.pack('<9f',0,0,0, 1,0,0, 0,1,0)
        idx=seven(6)+bytes((1,))+struct.pack('<I',6)+struct.pack('<3H',0,1,2)
        parsed=parse_geometry(xnb(readers,1,body+vtx+idx,shared=3)[10:])
        self.assertEqual(parsed['buffer']['vertices'],3)
        self.assertEqual(parsed['buffer']['indices'],3)

    def test_material_link_audit_excludes_generic_texture_slots(self):
        with tempfile.TemporaryDirectory() as td:
            game=Path(td)/'game';game.mkdir();out=Path(td)/'output'
            recovery=Recovery(game,out,code=False,catalog=False)
            (out/'Reports').mkdir(exist_ok=True)
            parts=[{'mesh':'ShipCorpus','part':0,'segment_label':'Vasa_hull','texture_label':'Texture'},
                   {'mesh':'Land','part':1,'segment_label':'TERRAIN1','texture_label':'Texture'}]
            (out/'meta.json').write_text(json.dumps({'parts':parts}),encoding='utf-8')
            records=[{'kind':'texture','status':'decoded','path':'Data/ModelTextures/Lod0/Ships/Vasa_hull.xnb'},
                     {'kind':'model','status':'decoded','path':'CommonData/Models/Ships/Ship_62_Vasa.xnb','geometry_report':'meta.json'}]
            (out/'Reports/AssetLedger.jsonl').write_text(''.join(json.dumps(x)+'\n' for x in records))
            recovery.links()
            self.assertEqual(recovery.report['links']['generic_placeholder_labels_ignored'],2)
            self.assertEqual(recovery.report['links']['matched'],1)
            self.assertEqual(recovery.report['links']['unmatched'],1)
            rows=[json.loads(x) for x in (out/'Reports/ModelTextureLinks.jsonl').read_text().splitlines()]
            self.assertEqual([r['material_label'] for r in rows],['Vasa_hull','TERRAIN1'])
            recovery.db.close()

    def test_selective_resume_only_reuses_previous_successes(self):
        from engine.full_recovery import REUSABLE_SUCCESS_REVISIONS
        with tempfile.TemporaryDirectory() as td:
            game=Path(td)/'game';game.mkdir();out=Path(td)/'out'
            source=game/'Ship.xnb';source.write_bytes(b'example contents')
            recovery=Recovery(game,out,code=False,catalog=False)
            output=out/'Recovered/model/Ship.obj'
            output.parent.mkdir(parents=True)
            output.write_text('# decoded ship')
            stat=source.stat()
            recovery.persist('Ship.xnb',stat,'examplehash','model','decoded',
                             'Recovered/model/Ship.obj')
            recovery.db.execute('UPDATE assets SET details=? WHERE path=?',
                (json.dumps({'decoder_revision':'4.1.0-asset-reader-2'}),'Ship.xnb'))
            recovery.db.commit()
            self.assertIsNotNone(recovery.cached('Ship.xnb',stat))
            # Failed and formerly unsupported assets must be retried by the fix.
            recovery.db.execute('UPDATE assets SET status=?,kind=? WHERE path=?',
                                ('unsupported','effect','Ship.xnb'))
            recovery.db.commit()
            self.assertIsNone(recovery.cached('Ship.xnb',stat))
            recovery.db.close()

    def test_non_xnb_named_files_are_not_misreported_as_bad_textures(self):
        with tempfile.TemporaryDirectory() as td:
            game=Path(td)/'game';game.mkdir();(game/'authors.xnb').write_bytes(b'NOT_A_STANDARD_XNB'+b'\x00'*60)
            result=Recovery(game,Path(td)/'out',catalog=False,code=False,payloads=False).run()
            self.assertEqual(result['assets']['counts']['unsupported'],1)
            row=json.loads((Path(td)/'out/Reports/AssetLedger.jsonl').read_text().strip())
            self.assertEqual(row['reason'],'unrecognized_xnb_header')
            self.assertEqual(row['kind'],'unknown_binary')

if __name__=='__main__':unittest.main()
