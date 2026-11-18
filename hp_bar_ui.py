"""Optional local video HP-bar study popup: human-calibrated ROI, no OCR.

All frame extraction is opt-in. No screen capture happens in this window;
it reads only a user-selected file. A measured bar percentage is not game HP.
"""
from __future__ import annotations
import csv
import hashlib
import io
import threading
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
from datetime import datetime,timezone
from pathlib import Path

from video_evidence import frame_png,measure_bar
from workbench_db import home


def open_hp_video_tool(parent):
    from PIL import Image,ImageTk
    window=tk.Toplevel(parent);window.title('WoSB · Video HP-bar Measurement')
    window.geometry('1040x880');window.minsize(820,680)
    frame=ttk.Frame(window,padding=18);frame.pack(fill='both',expand=True)
    ttk.Label(frame,text='Measure target HP-bar fill from your recording',font=('Segoe UI Semibold',17)).pack(anchor='w')
    ttk.Label(frame,text='Choose a gameplay MP4, seek to a frame, drag a rectangle around the colored HP bar. Right-click the bar to sample its actual color. Relative fill is not an exact HP value.\nYour video stays on your PC.',wraplength=960).pack(anchor='w',pady=(5,12))
    filevar=tk.StringVar(value='No video selected');timevar=tk.StringVar(value='0')
    colorvar=tk.StringVar(value='#d54348');status=tk.StringVar(value='Choose a video file to begin')
    preview=tk.Canvas(frame,width=950,height=490,bg='#111d2b',highlightthickness=0)
    tools=ttk.Frame(frame);tools.pack(fill='x',pady=(2,10))
    ttk.Label(tools,textvariable=filevar,width=53).pack(side='left')
    ttk.Label(tools,text='At second').pack(side='left',padx=(10,4))
    ttk.Entry(tools,textvariable=timevar,width=8).pack(side='left')
    ttk.Label(tools,text='Bar color').pack(side='left',padx=(12,4))
    ttk.Entry(tools,textvariable=colorvar,width=10).pack(side='left')
    ttk.Label(frame,textvariable=status,wraplength=950).pack(anchor='w',pady=8)
    preview.pack(fill='x',pady=(0,9))
    state={'video':None,'image':None,'photo':None,'scale':1.,'roi':None,'drag':None,'rect':None,'at':0.}
    def rgb():
        value=colorvar.get().strip().lstrip('#')
        if len(value)!=6:raise ValueError('Enter six-digit RGB hex, such as #dd3c4f')
        return tuple(int(value[i:i+2],16) for i in (0,2,4))
    def choose():
        filename=filedialog.askopenfilename(parent=window,title='Choose your gameplay video',filetypes=[('MP4 videos','*.mp4'),('All files','*.*')])
        if filename:state['video']=Path(filename);filevar.set(state['video'].name)
    def render(data):
        image=Image.open(io.BytesIO(data)).convert('RGB')
        state['image']=image
        iw,ih=image.size;scale=min(950/iw,490/ih,1.)
        state['scale']=scale
        tiny=image.resize((max(1,int(iw*scale)),max(1,int(ih*scale))))
        state['photo']=ImageTk.PhotoImage(tiny,master=window)
        preview.delete('all');preview.config(width=tiny.width,height=tiny.height)
        preview.create_image(0,0,image=state['photo'],anchor='nw')
        state['roi']=None;status.set(f'Frame {iw}×{ih}. Drag over the HP bar; right-click a colored part to sample its RGB.')
    def seek():
        if not state['video']:return messagebox.showwarning('Choose video','Select an MP4 first',parent=window)
        try:seconds=float(timevar.get())
        except ValueError:return messagebox.showerror('Invalid time','Enter seconds from start',parent=window)
        status.set('Extracting chosen frame locally…');seek_button.configure(state='disabled')
        def work():
            try:data=frame_png(state['video'],seconds)
            # Bind the message now: Python deletes ``exc`` when the except block ends,
            # so a lambda that referenced it later raised NameError in the Tk thread.
            except Exception as exc:window.after(0,lambda message='Could not extract frame: '+str(exc):status.set(message))
            else:window.after(0,lambda:render(data))
            finally:window.after(0,lambda:seek_button.configure(state='normal'))
        threading.Thread(target=work,daemon=True).start()
        state['at']=seconds
    ttk.Button(tools,text='Choose MP4',command=choose).pack(side='left',padx=(15,0))
    seek_button=ttk.Button(tools,text='Show frame',command=seek);seek_button.pack(side='left',padx=5)
    def down(e):
        if not state['image']:return
        state['drag']=(e.x,e.y)
        if state['rect']:preview.delete(state['rect'])
    def move(e):
        if state['drag']:
            if state['rect']:preview.delete(state['rect'])
            x,y=state['drag'];state['rect']=preview.create_rectangle(x,y,e.x,e.y,outline='#f6c471',width=3)
    def up(e):
        if not state['drag']:return
        x,y=state['drag'];state['drag']=None
        scale=state['scale'];iw,ih=state['image'].size
        l,r=sorted((round(x/scale),round(e.x/scale)));t,b=sorted((round(y/scale),round(e.y/scale)))
        l=max(0,min(iw,l));r=max(0,min(iw,r));t=max(0,min(ih,t));b=max(0,min(ih,b))
        if r-l>=10 and b-t>=2:state['roi']=[l,t,r,b];status.set(f'HP region: {l},{t} to {r},{b}. Right-click sample color or edit color hex, then measure.')
    def sample_color(e):
        if not state['image']:return
        x=min(max(0,round(e.x/state['scale'])),state['image'].width-1)
        y=min(max(0,round(e.y/state['scale'])),state['image'].height-1)
        color=state['image'].getpixel((x,y));colorvar.set('#%02x%02x%02x'%color)
        status.set('Selected pixel RGB '+colorvar.get()+'; measure the selected HP bar region.')
    preview.bind('<ButtonPress-1>',down);preview.bind('<B1-Motion>',move);preview.bind('<ButtonRelease-1>',up)
    preview.bind('<Button-3>',sample_color)
    maxvar=tk.StringVar(value='');result=tk.StringVar(value='No measurement yet')
    row=ttk.Frame(frame);row.pack(fill='x',pady=6)
    ttk.Label(row,text='Known maximum HP (optional)').pack(side='left');ttk.Entry(row,textvariable=maxvar,width=12).pack(side='left',padx=10)
    ttk.Label(frame,textvariable=result,wraplength=980).pack(anchor='w',pady=10)
    def measure():
        if not state['image'] or not state['roi']:return status.set('Choose a frame and draw the health bar rectangle first.')
        try:
            record=measure_bar(state['image'],state['roi'],bar_color=rgb())
            hp=maxvar.get().strip();hypothesis=float(hp)*record['fraction'] if hp else None
            if hp and float(hp)<=0:raise ValueError('Maximum HP must be positive')
            desc=f"Observed bar fill {record['bar_fill_percent']}% · color confidence {record['confidence']}. "
            if hypothesis is not None:desc+=f"Linear max-HP assumption: {hypothesis:.1f} HP (not independently verified). "
            result.set(desc+'Empty/faded bars and UI effects need manual review.')
            state['last']={**record,'time_second':state['at'],'linear_hp_assumption':hypothesis,
                 'video_sha256_filename_only':hashlib.sha256(state['video'].name.encode()).hexdigest()[:16],
                 'measured_utc':datetime.now(timezone.utc).isoformat()}
        except (ValueError,TypeError) as exc:status.set('Cannot measure that region: '+str(exc))
    def save():
        if 'last' not in state:return status.set('Measure a frame first')
        output=home()/'GameplayEvidence'/'HP-Bar-Measurements.csv';output.parent.mkdir(parents=True,exist_ok=True)
        record=state['last'];cols=['measured_utc','video_sha256_filename_only','time_second','bar_fill_percent',
             'confidence','sampled_region','linear_hp_assumption','verified_hp']
        create=not output.exists()
        with output.open('a',encoding='utf-8-sig',newline='') as f:
            w=csv.DictWriter(f,fieldnames=cols,extrasaction='ignore')
            if create:w.writeheader()
            w.writerow(record)
        status.set('Measurement saved locally: '+str(output)+' · video not copied')
    buttons=ttk.Frame(frame);buttons.pack(anchor='w')
    ttk.Button(buttons,text='Measure selected HP bar',command=measure).pack(side='left',padx=(0,9))
    ttk.Button(buttons,text='Save reading to CSV',command=save).pack(side='left')
    return window
