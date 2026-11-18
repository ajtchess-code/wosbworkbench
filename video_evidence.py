"""Opt-in HP-bar color measurements from *user-owned* gameplay video.

Uses a manually selected screen region and color; no OCR, face recognition,
background screen access, game injection, or automatic uploading. Frames are
extracted from an existing MP4 with ffmpeg when requested by the user.
"""
from __future__ import annotations
from pathlib import Path
import csv
import io
import math
import shutil
import subprocess

MAX_VIDEO_SIZE=50*1024**3
MAX_IMAGE_BYTES=30*1024**2


def frame_png(video,seconds,*,ffmpeg=None):
    src=Path(video)
    if not src.is_file() or src.stat().st_size>MAX_VIDEO_SIZE:raise ValueError('Missing or oversized local video')
    t=float(seconds)
    if not math.isfinite(t) or not 0<=t<=14400:raise ValueError('Invalid video timestamp')
    exe=ffmpeg or shutil.which('ffmpeg')
    if not exe:raise FileNotFoundError('FFmpeg needed for extracting video frames')
    # Avoid shell=True and avoid reading unbounded output into UI.
    cmd=[str(exe),'-hide_banner','-loglevel','error','-ss',f'{t:.3f}','-i',str(src),
         '-frames:v','1','-f','image2pipe','-vcodec','png','pipe:1']
    output=subprocess.run(cmd,capture_output=True,timeout=25)
    if output.returncode or not output.stdout:raise RuntimeError('Could not extract the requested frame')
    if len(output.stdout)>MAX_IMAGE_BYTES:raise ValueError('Extracted video frame is too large')
    return output.stdout


def _rgb_distance(a,b):
    return sum((int(a[i])-int(b[i]))**2 for i in range(3))**.5


def measure_bar(image, box, *, bar_color, tolerance=65, orientation='left_to_right',
                min_columns=10, alpha_weight=1.0):
    """Estimate colored health bar fill from a manually calibrated rectangle.

    A bar can have icons/labels/shadows. We measure color-consistent column
    occupancy; confidence must be reviewed by a human. This is not direct HP.
    """
    from PIL import Image
    if isinstance(image,(bytes,bytearray)):
        if len(image)>MAX_IMAGE_BYTES:raise ValueError('Image too large')
        image=Image.open(io.BytesIO(image))
    if not isinstance(image,Image.Image):raise TypeError('Expected PIL image or image bytes')
    if image.width*image.height>24_000_000:raise ValueError('Image pixel budget exceeded')
    if not isinstance(box,(list,tuple)) or len(box)!=4:raise ValueError('Box [left,top,right,bottom] required')
    left,top,right,bottom=(int(i) for i in box)
    if not (0<=left<right<=image.width and 0<=top<bottom<=image.height):raise ValueError('Box outside image')
    if not isinstance(bar_color,(tuple,list)) or len(bar_color)<3:raise ValueError('RGB target color required')
    tol=float(tolerance)
    if not 1<=tol<=300:raise ValueError('Invalid color tolerance')
    crop=image.convert('RGB').crop((left,top,right,bottom))
    width,height=crop.size
    if width<min_columns or height<2:raise ValueError('Region too small')
    pixel=crop.load(); occupancy=[]
    # Sample the middle 60% of height to avoid UI strokes and shadows.
    start=max(0,int(height*.2));end=min(height,max(start+1,int(height*.8)))
    for x in range(width):
        fraction=sum(_rgb_distance(pixel[x,y],bar_color)<=tol for y in range(start,end))/(end-start)
        occupancy.append(fraction)
    active=[frac>=.5 for frac in occupancy]
    if orientation=='right_to_left':active.reverse();occupancy.reverse()
    elif orientation!='left_to_right':raise ValueError('Unknown bar orientation')
    # Noise-tolerant 1-D sliding median of neighboring columns.
    smoothed=[]
    for i in range(width):
        neighbors=active[max(0,i-2):min(width,i+3)]
        smoothed.append(sum(neighbors)>=int(len(neighbors)/2)+1)
    last_active=max((i for i,a in enumerate(smoothed) if a),default=-1)
    fraction=(last_active+1)/width
    if last_active<0:fraction=0.
    if last_active>=0:
        start_active=smoothed[:last_active+1]
        consistency=sum(start_active)/len(start_active)
    else:consistency=0
    outside=smoothed[last_active+1:]
    noise=1.-sum(outside)/len(outside) if outside else 1.
    # An empty bar cannot be confirmed from no detected color alone.
    confidence=round(min(consistency,noise),3) if last_active>=0 else 0.
    return {'fraction':round(fraction,4),'bar_fill_percent':round(fraction*100,2),
            'confidence':confidence,'empty_bar_ambiguous':last_active<0,
            'method':'manual_ROI_color_segmentation','verified_hp':False,
            'sampled_region':[left,top,right,bottom],
            'note':'A relative fill observation, not an authoritative HP value. Recheck overlays, color changes and UI scaling.'}


def hp_estimate(measurement,*,known_max_hp=None,known_current_hp=None):
    """Map a relative colored bar fraction to a user-known HP scale, if given."""
    fraction=float(measurement['fraction'])
    if not 0<=fraction<=1:raise ValueError('Invalid bar fraction')
    result={'fill_fraction':fraction,'source':'video_color_bar_observation','in_game_hp_confirmed':False}
    if known_max_hp is not None:
        hp=float(known_max_hp)
        if not math.isfinite(hp) or hp<=0:raise ValueError('Invalid max HP')
        result['hp_from_linear_bar_assumption']=round(hp*fraction,2)
        result['assumption']='Linear bar mapping; inspect UI for non-linear/protected HP representations'
    if known_current_hp is not None:result['user_verified_hp']=float(known_current_hp)
    return result


def batch_video_measure(video,times,box,color,output,*,max_frames=500,ffmpeg=None):
    if len(times)>max_frames:raise ValueError('Too many frames to sample')
    records=[]
    for value in times:
        raw=frame_png(video,value,ffmpeg=ffmpeg)
        rec=measure_bar(raw,box,bar_color=color)
        rec['video_second']=float(value);records.append(rec)
    dest=Path(output);dest.parent.mkdir(parents=True,exist_ok=True)
    with dest.open('w',encoding='utf-8',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=('video_second','fill_fraction','bar_fill_percent','confidence','empty_bar_ambiguous','method','verified_hp','sampled_region','note'),extrasaction='ignore')
        writer.writeheader()
        for row in records:writer.writerow({'video_second':row['video_second'],'fill_fraction':row['fraction'],**row})
    return {'output':str(dest),'frames':len(records),'method':'relative_HUD_fill_only','confidence_needs_manual_review':True}


def correlate_markers(markers, timeline, *, window=2.5,offset_seconds=0):
    """Correlate UTC event markers to packet timeline bins without classifying IDs."""
    win=float(window);offset=float(offset_seconds)
    if not 0<win<=30 or not -120<=offset<=120:raise ValueError('Invalid window or clock correction')
    from datetime import datetime
    def when(s):
        if isinstance(s,(int,float)):return float(s)
        return datetime.fromisoformat(str(s).replace('Z','+00:00')).timestamp()
    data=[]
    for marker in markers:
        t=when(marker.get('utc') or marker.get('timestamp_utc') or marker.get('time'))+offset
        nearby=[]
        for item in timeline:
            candidate=item.get('time') or item.get('utc') or item.get('timestamp_utc')
            if candidate is None:continue
            try:delta=round(when(candidate)-t,3)
            except (TypeError,ValueError):continue
            if abs(delta)<=win:
                nearby.append({'delta_seconds':delta,'bytes':item.get('bytes'),
                               'size':item.get('size'),'direction':item.get('direction')})
        data.append({'marker_kind':str(marker.get('kind') or marker.get('type') or 'note')[:50],
                     'candidate_segments_nearby':len(nearby),
                     'closest':sorted(nearby,key=lambda x:abs(x['delta_seconds']))[:12],
                     'classification':'temporal_correlation_only_unverified'})
    return {'format':'wosb-gameplay-packet-correlation-v43','events':data,
            'warning':'Temporal proximity cannot establish message semantics, HP damage or packet identity.'}
