"""Image-side-by-side WoSB client vs Workbench render comparison.

This is a visual QA tool, not evidence that the custom game shader was decoded.
The screenshots need matching camera, zoom, lighting and animation to make the
numerical pixel difference meaningful. Never extracts hidden content.
"""
from __future__ import annotations
from pathlib import Path


def compare_screenshots(game_image,viewer_image,destination,*,alpha=0.5):
    from PIL import Image, ImageChops, ImageEnhance, ImageDraw
    if not 0<=alpha<=1:raise ValueError('Invalid blend ratio')
    left=Path(game_image);right=Path(viewer_image)
    for p in (left,right):
        if p.stat().st_size>40*1024*1024:raise ValueError('Screenshot exceeds 40 MiB')
    with Image.open(left) as a, Image.open(right) as b:
        x=a.convert('RGB');y=b.convert('RGB')
    mismatched=x.size!=y.size
    if mismatched:y=y.resize(x.size,Image.Resampling.LANCZOS)
    diff=ImageChops.difference(x,y)
    diff=ImageEnhance.Contrast(diff).enhance(2)
    over=Image.blend(x,y,alpha)
    w,h=x.size
    output=Image.new('RGB',(w*2,h*2+48),(12,24,38))
    output.paste(x,(0,48));output.paste(y,(w,48))
    output.paste(over,(0,h+48));output.paste(diff,(w,h+48))
    d=ImageDraw.Draw(output)
    for px,label in ((0,'ACTUAL GAME SCREENSHOT'),(w,'WORKBENCH RENDER'),
                     (0,'BLENDED COMPARISON'),(w,'AMPLIFIED PIXEL DIFFERENCE')):
        yp=14 if label.startswith(('ACTUAL','WORKBENCH')) else h+24
        d.text((px+14,yp),label,fill=(230,245,250))
    dst=Path(destination);dst.parent.mkdir(parents=True,exist_ok=True)
    output.save(dst,format='PNG',optimize=True)
    return {'output':str(dst),'resolution':list(x.size),'resized_workbench':mismatched,
        'alignment_warning':'Only compare pixel differences after matching angle, zoom, environment and animation states. Resizing changes pixel statistics.'}
