"""Observed maneuver telemetry and non-authoritative sailing/ballistics sandboxes."""
from __future__ import annotations
import math, statistics
from sailing_lab import wind_speed_component


def _num(value):
    v=float(value)
    if not math.isfinite(v):raise ValueError('Invalid nonfinite telemetry')
    return v


def trajectory(*,initial_speed,launch_angle_deg,gravity=9.81,origin_height=0,
               shooter_vx=0,wind_ax=0,wind_ay=0,dt=.05,max_seconds=90):
    """Classical projectile illustrative sandbox; NOT WoSB game trajectory."""
    speed=_num(initial_speed);angle=_num(launch_angle_deg);g=_num(gravity)
    if speed<0 or g<=0 or dt<=0 or dt>.5 or not 0<max_seconds<=600:raise ValueError('Invalid trajectory setup')
    if not -90<=angle<=90:raise ValueError('Invalid launch angle')
    vx=speed*math.cos(math.radians(angle))+_num(shooter_vx)
    vy=speed*math.sin(math.radians(angle));y0=_num(origin_height)
    samples=[];t=0.
    while t<=max_seconds+1e-8:
        x=vx*t+.5*_num(wind_ax)*t*t
        y=y0+vy*t+.5*(_num(wind_ay)-g)*t*t
        if y<0 and t>0:break
        samples.append({'time_s':round(t,4),'x_model_units':round(x,4),'height_model_units':round(y,4)})
        t+=dt
    return {'format':'wosb-projectile-sandbox-v1','samples':samples,
            'final_sample':samples[-1] if samples else None,'model':'classical ballistic toy model; units/parameters user-configurable',
            'game_physics_verified':False,'game_collision_verified':False}


def evaluate_maneuver(points):
    """Compute speed, angular turn and turning radius from actual xy/time samples."""
    if len(points)<3:raise ValueError('At least 3 observation samples required')
    cleaned=[]
    for row in points:
        record={'t':_num(row['time_s']),'x':_num(row['x']),'y':_num(row['y'])}
        if cleaned and record['t']<=cleaned[-1]['t']:raise ValueError('Times must strictly increase')
        cleaned.append(record)
    segments=[];heading=[]
    for a,b in zip(cleaned,cleaned[1:]):
        dt=b['t']-a['t'];dx=b['x']-a['x'];dy=b['y']-a['y'];length=math.hypot(dx,dy)
        segments.append({'speed':length/dt,'dt':dt, 'distance':length})
        heading.append(math.atan2(dy,dx) if length>1e-9 else None)
    turns=[]
    for i in range(1,len(heading)):
        if heading[i] is None or heading[i-1] is None:continue
        delta=math.atan2(math.sin(heading[i]-heading[i-1]),math.cos(heading[i]-heading[i-1]))
        dt=(segments[i]['dt']+segments[i-1]['dt'])/2
        angular=delta/dt;speed=(segments[i]['speed']+segments[i-1]['speed'])/2
        turns.append({'time_s':cleaned[i]['t'],'turn_deg_per_s':math.degrees(angular),
                      'radius_model_units':abs(speed/angular) if abs(angular)>1e-9 else None})
    spd=[s['speed'] for s in segments];accel=[]
    for a,b in zip(segments,segments[1:]):accel.append((b['speed']-a['speed'])/((a['dt']+b['dt'])/2))
    return {'format':'wosb-observed-maneuver-v1', 'sample_count':len(points),
            'distance_model_units':sum(s['distance'] for s in segments),
            'mean_speed_model_units_per_s':statistics.mean(spd),
            'max_speed_model_units_per_s':max(spd),
            'max_abs_acceleration_model_units_per_s2':max((abs(x) for x in accel),default=0),
            'turns':turns,'evidence':'calculated from supplied time-position samples; position scale must be validated'}


def compare_wind_profiles(profiles,*,increment_degrees=15):
    if not 1<=increment_degrees<=90 or 360%increment_degrees:raise ValueError('Angular increment must divide 360')
    points=[]
    for angle in range(0,361,increment_degrees):
        common=wind_speed_component(angle)
        # Per-ship coefficients MUST be supplied as hypotheses; never convert to knots.
        record={'angle_deg':angle,'recovered_component':common}
        for name,profile in profiles.items():
            if not isinstance(profile,dict):raise ValueError('Expected profile dict')
            base=_num(profile.get('base_index',1));factor=_num(profile.get('wind_coefficient',1))
            record[name]=base*common*factor
        points.append(record)
    return {'format':'wosb-sailing-profile-comparison-v1','profiles':profiles,'samples':points,
            'warning':'Only recovered shared wind component is client-grounded; base_index/wind_coefficient are manually configured, not verified ship speeds.'}
