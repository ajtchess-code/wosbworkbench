"""Offline video transient candidates, not automatic WoSB hit identification.

Captures only bounded luminance frame differences. FFmpeg must be installed.
Raw frames and game video are neither uploaded nor included in exports.
"""
from __future__ import annotations
from pathlib import Path
import shutil,statistics,subprocess


def candidate_events(video_path,*,ffmpeg=None,fps=2.0,max_seconds=900,width=160,height=90,
                     threshold_sigma=2.5,min_interval_seconds=1.0,region=None):
    if not 0.5<=fps<=12 or not 10<=max_seconds<=3600:raise ValueError('Unsupported frame sampling settings')
    if not 32<=width<=400 or not 32<=height<=300:raise ValueError('Invalid frame dimensions')
    src=Path(video_path).resolve(strict=True)
    if src.stat().st_size>10*1024**3:raise ValueError('Video size over 10 GiB import cap')
    tool=ffmpeg or shutil.which('ffmpeg')
    if not tool:raise RuntimeError('FFmpeg is not installed or not on PATH')
    if region is not None:
        x0,y0,x1,y1=region
        if not all(0<=x<=1 for x in (x0,y0,x1,y1)) or x0>=x1 or y0>=y1:raise ValueError('Invalid relative region')
        bounds=(int(width*x0),int(height*y0),int(width*x1),int(height*y1))
    else:bounds=(0,0,width,height)
    frames=int(max_seconds*fps)
    if frames*width*height>128*1024*1024:
        raise ValueError('Frame sampling would exceed 128 MiB: reduce --fps, window or frame dimensions')
    command=[str(tool),'-hide_banner','-loglevel','error','-nostdin','-i',str(src),'-vf',
             f'fps={fps},scale={width}:{height},format=gray','-frames:v',str(frames),
             '-f','rawvideo','-pix_fmt','gray','pipe:1']
    try:
        result=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=min(180,max(30,max_seconds/8)))
    except subprocess.TimeoutExpired as exc:raise RuntimeError('FFmpeg analysis reached time limit') from exc
    if result.returncode:raise RuntimeError('FFmpeg could not read video: '+result.stderr[:300].decode('utf-8','replace'))
    raw=result.stdout;frame_bytes=width*height
    if len(raw)%frame_bytes:raise RuntimeError('Partial raw-frame result')
    count=len(raw)//frame_bytes
    if count<3:return {'format':'wosb-video-event-candidates-v1','frames':count,'events':[],
                         'warning':'Not enough frames to identify transient changes'}
    scores=[];previous=memoryview(raw)[:frame_bytes]
    x0,y0,x1,y1=bounds
    for i in range(1,count):
        current=memoryview(raw)[i*frame_bytes:(i+1)*frame_bytes]
        total=0;n=0
        for y in range(y0,y1):
            a=y*width
            for x in range(x0,x1):total+=abs(current[a+x]-previous[a+x]);n+=1
        scores.append(total/max(1,n))
        previous=current
    # High-activity frames should not raise the noise baseline and hide a
    # short bright flash; calibrate against the lower-motion frame population.
    quiet=sorted(scores)[:max(1,int(len(scores)*.60))]
    baseline=statistics.median(quiet)
    robust_sigma=1.4826*statistics.median(abs(x-baseline) for x in quiet)
    cutoff=baseline+max(2.0,threshold_sigma*robust_sigma)
    suggestions=[];last=-1e9
    for i,score in enumerate(scores,1):
        elapsed=i/fps
        if score>=cutoff and elapsed-last>=min_interval_seconds:
            suggestions.append({'video_second':round(elapsed,3),
                                'luminance_difference':round(score,4),'kind':'visual-transient-candidate',
                                'requires_manual_review':True})
            last=elapsed
    return {'format':'wosb-video-event-candidates-v1','frames':count,'fps':fps,
            'region_relative':region,'events':suggestions[:1500],
            'median_frame_difference':baseline,'threshold':cutoff,
            'notes':'Motion, zoom, UI changes and lighting can cause false positives. A visual transient does NOT identify a shot, a hit, or HP damage.',
            'payloads_saved':False}
