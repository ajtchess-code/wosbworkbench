"""Validate an extracted catalog: python Verify-Export.py path/to/WOSB-Catalog-folder"""
import json,sys
from pathlib import Path
from PIL import Image
p=Path(sys.argv[1]);d=json.loads((p/'catalog.json').read_text(encoding='utf-8'))
ids={x['ImageID'] for x in d['Images']}
assert len(ids)==len(d['Images']), 'Duplicate image IDs'
assert len({x['PNGPath'] for x in d['Images']})==len(d['Images']), 'Duplicate output paths'
for row in d['Images']:
    with Image.open(p/row['PNGPath']) as im:
        assert im.size==(row['Width'],row['Height']), row['PNGPath']
for row in d['Entity_Images']:
    assert row['ImageID'] in ids and (p/row['PNGPath']).is_file(),row
for row in d.get('Market_Price_Limits',[]):
    if row.get('ClientMinUnitPrice') is not None:
        assert row['ClientMinUnitPrice']<=row['ClientMaxUnitPrice'],row
recipeids={x['RecipeID'] for x in d.get('Crafting_Recipes',[])}
assert all(x['RecipeID'] in recipeids for x in d.get('Recipe_Ingredients',[]))
shipids={x['ID'] for x in d.get('ShipsToPlay',[])}
assert all(x['ShipID'] in shipids for x in d.get('Ship_Materials',[]))
print('Verified images:',len(ids),'entity/image links:',len(d['Entity_Images']))
print('Catalog rows and references are consistent.')
