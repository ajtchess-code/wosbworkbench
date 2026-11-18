"""Read-only and opt-in local advanced research workflows for WoSB Workbench.

To see supported commands: python advanced_research_cli.py --help
"""
from __future__ import annotations
import argparse,json,sys
from contextlib import closing
from pathlib import Path


def _json(path):return json.loads(Path(path).read_text(encoding='utf-8'))

def main(argv=None):
    p=argparse.ArgumentParser(description='WoSB Workbench Advanced Research (offline)')
    sub=p.add_subparsers(dest='task',required=True)
    x=sub.add_parser('geometry',help='Inspect OBJ mesh, optional raycast and research heatmap')
    x.add_argument('obj');x.add_argument('--out',required=True);x.add_argument('--rays',help='JSON list of ray requests')
    x.add_argument('--armor',type=float);x.add_argument('--cannon',default='42-pdr Carronade');x.add_argument('--ammo',default='Round Shot');x.add_argument('--resolution',type=int,default=16)
    x=sub.add_parser('video',help='Find frame-change candidates, not confirmed hits')
    x.add_argument('video');x.add_argument('--out',required=True);x.add_argument('--fps',type=float,default=2)
    x=sub.add_parser('benchmark',help='CPU geometry benchmark, not real-game FPS')
    x.add_argument('--out',required=True);x.add_argument('--grid',type=int,default=55)
    x=sub.add_parser('network',help='Offline stream continuity (no raw payload export)')
    x.add_argument('pcap');x.add_argument('--out',required=True)
    x=sub.add_parser('recovery',help='Classify current recovery ledger failures')
    x.add_argument('ledger');x.add_argument('--out',required=True)
    x=sub.add_parser('snapshot',help='Hash bounded local user-owned asset tree')
    x.add_argument('folder');x.add_argument('--out',required=True)
    x=sub.add_parser('diff',help='Compare asset/catalog snapshots')
    x.add_argument('old');x.add_argument('new');x.add_argument('--out',required=True);x.add_argument('--catalog',action='store_true')
    x=sub.add_parser('outfit',help='Apply user-configured ship-stat hypotheses')
    x.add_argument('stats');x.add_argument('modifiers');x.add_argument('--out',required=True)
    x=sub.add_parser('gunports',help='Audit only candidate gun-related mesh names, not confirmed slots')
    x.add_argument('obj');x.add_argument('--out',required=True)
    x=sub.add_parser('sails',help='Study observed sail-health versus speed association')
    x.add_argument('observations');x.add_argument('--out',required=True)
    x=sub.add_parser('sailing',help='Estimate maneuverability from observed time/x/y samples')
    x.add_argument('points');x.add_argument('--out',required=True)
    x=sub.add_parser('trajectory',help='Classical trajectory sandbox, not game-specific')
    x.add_argument('--speed',type=float,required=True);x.add_argument('--angle',type=float,required=True);x.add_argument('--out',required=True)
    x=sub.add_parser('sync',help='Fit capture UTC/video seconds time anchors')
    x.add_argument('pairs');x.add_argument('--out',required=True)
    x=sub.add_parser('targets',help='Assign privacy-preserving IDs to explicitly identified targets')
    x.add_argument('events');x.add_argument('--out',required=True)
    x=sub.add_parser('catalog',help='Export only hashes and source references from local catalog')
    x.add_argument('database');x.add_argument('--build',default='Game');x.add_argument('--out',required=True)
    x=sub.add_parser('experiment',help='Insert a controlled, auditable HP observation')
    x.add_argument('database');x.add_argument('--ship',required=True);x.add_argument('--target',required=True)
    x.add_argument('--weapon',required=True);x.add_argument('--ammo',required=True)
    x.add_argument('--hp-before',type=float,required=True);x.add_argument('--hp-after',type=float,required=True)
    x.add_argument('--hits',type=int,default=1);x.add_argument('--source',default='manual')
    x.add_argument('--armor',type=float);x.add_argument('--angle',type=float)
    x=sub.add_parser('experiments-report',help='Export aggregate experiment statistics and evidence ZIP')
    x.add_argument('database');x.add_argument('--out',required=True)
    x=sub.add_parser('release',help='Run offline source checks and output SHA-256 inventory')
    x.add_argument('--root',default=str(Path(__file__).resolve().parent));x.add_argument('--out',required=True)
    x=sub.add_parser('protocol',help='Reassemble TCP, detect framing, catalog message types (your own captures)')
    x.add_argument('captures',nargs='+');x.add_argument('--port',type=int);x.add_argument('--markers')
    x.add_argument('--definitions');x.add_argument('--out',required=True)
    x=sub.add_parser('protocol-extract',help='Static message classes, wire order and opcode enums from client/launcher DLLs')
    x.add_argument('root');x.add_argument('--label',default='');x.add_argument('--out',required=True)
    x=sub.add_parser('protocol-diff',help='Compare two protocol-definition JSON files (e.g. Game vs Steam)')
    x.add_argument('old');x.add_argument('new');x.add_argument('--out',required=True)
    args=p.parse_args(argv)
    if args.task in ('protocol-extract','protocol-diff'):
        engine=str(Path(__file__).resolve().parent/'engine')
        if engine not in sys.path:sys.path.insert(0,engine)
    if args.task=='protocol':
        import protocol_lab
        defs=_json(args.definitions) if args.definitions else None
        if len(args.captures)==1 and Path(args.captures[0]).is_dir():
            result=protocol_lab.analyze_session_folder(args.captures[0],definitions=defs)
        else:
            result=protocol_lab.analyze(args.captures,server_port=args.port,definitions=defs,
                                        markers=protocol_lab.load_markers(args.markers) if args.markers else None)
    elif args.task=='protocol-extract':
        from protocol_extract import extract
        result=extract(args.root,label=args.label)
    elif args.task=='protocol-diff':
        from protocol_extract import diff_definitions
        result=diff_definitions(_json(args.old),_json(args.new))
    elif args.task=='geometry':
        from advanced_geometry import analyze_obj
        cannon=ammo=None
        if args.armor is not None:
            from damage_hypotheses import CATALOG,lookup
            data=_json(CATALOG)['datasets'];cannon=lookup(data['Cannons'],args.cannon);ammo=lookup(data['CannonBalls'],args.ammo)
        result=analyze_obj(args.obj,args.out,rays=_json(args.rays) if args.rays else None,
                           cannon=cannon,ammo=ammo,armor=args.armor,samples=args.resolution)
    elif args.task=='video':
        from advanced_video import candidate_events
        result=candidate_events(args.video,fps=args.fps)
    elif args.task=='benchmark':
        from advanced_performance import benchmark_geometry
        result=benchmark_geometry(grid=args.grid)
    elif args.task=='network':
        from advanced_network import analyze_stream_continuity
        result=analyze_stream_continuity(args.pcap)
    elif args.task=='recovery':
        from advanced_assets import recovery_triage
        result=recovery_triage(args.ledger)
    elif args.task=='snapshot':
        from advanced_assets import inventory_tree
        result=inventory_tree(args.folder)
    elif args.task=='diff':
        if args.catalog:
            from advanced_catalog import compare_catalogs
            result=compare_catalogs(_json(args.old),_json(args.new))
        else:
            from advanced_assets import diff_inventories
            result=diff_inventories(_json(args.old),_json(args.new))
    elif args.task=='outfit':
        from advanced_ship_config import outfit_hypothesis
        result=outfit_hypothesis(_json(args.stats),_json(args.modifiers))
    elif args.task=='gunports':
        from advanced_ship_config import mount_candidates
        from ship_viewer import read_obj
        result=mount_candidates(read_obj(args.obj))
    elif args.task=='sails':
        from advanced_ship_config import sail_condition_observations
        result=sail_condition_observations(_json(args.observations))
    elif args.task=='sailing':
        from advanced_sailing import evaluate_maneuver
        result=evaluate_maneuver(_json(args.points))
    elif args.task=='trajectory':
        from advanced_sailing import trajectory
        result=trajectory(initial_speed=args.speed,launch_angle_deg=args.angle)
    elif args.task=='sync':
        from advanced_network import fit_clocks
        result=fit_clocks(_json(args.pairs))
    elif args.task=='targets':
        from advanced_network import assign_target_ids
        result=assign_target_ids(_json(args.events))
    elif args.task=='catalog':
        import sqlite3
        from advanced_catalog import dataset_snapshot
        with closing(sqlite3.connect('file:'+str(Path(args.database).resolve())+'?mode=ro',uri=True)) as db:
            db.row_factory=sqlite3.Row;result=dataset_snapshot(db,args.build)
    elif args.task in ('experiment','experiments-report'):
        from advanced_experiments import open_db, add_experiment, add_observation, export_experiments
        with closing(open_db(args.database)) as db:
            if args.task=='experiment':
                eid=add_experiment(db,ship=args.ship,target=args.target,weapon=args.weapon,ammunition=args.ammo,
                                   impact_angle_deg=args.angle,target_armor=args.armor)
                oid=add_observation(db,eid,hp_before=args.hp_before,hp_after=args.hp_after,hits=args.hits,source=args.source)
                result={'experiment_id':eid,'observation_id':oid,'measured_hp_per_hit':(args.hp_before-args.hp_after)/args.hits}
            else:result=export_experiments(db,args.out)
    else:
        from advanced_release import make_manifest
        result=make_manifest(args.root)
    if hasattr(args,'out') and args.out and args.task not in ('geometry','experiments-report'):
        path=Path(args.out);path.parent.mkdir(parents=True,exist_ok=True)
        from advanced_io import write_json_atomic
        write_json_atomic(path,result)
    print(json.dumps(result,indent=2,ensure_ascii=False))
    return 0

if __name__=='__main__':raise SystemExit(main())
