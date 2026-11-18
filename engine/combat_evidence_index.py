"""Build a reproducible client-method research queue, not a guessed damage model.

The index names concrete methods from scanned managed assemblies and records
which required links are still absent. It does not decompile or execute them.
"""
from __future__ import annotations
import json
from pathlib import Path

FOCUS = {
    'projectile': ('cannonball','projectile','shell','bullet','mortar','penetration'),
    'damage': ('damage','armor','deflect','ricochet','crit','hitbox','collision','burning','fire','flood'),
    'sailing': ('wind','speed','sail','mobility','turn','rudder'),
    'protocol': ('packet','network','serialize','deserialize','message','rpc','clientaction'),
}

def build_index(methods_path, output, *, max_results=5000):
    path=Path(methods_path);output=Path(output)
    results=[];by_domain={name:0 for name in FOCUS};scanned=0
    with path.open(encoding='utf-8') as source:
        for line in source:
            if not line.strip():continue
            try:record=json.loads(line)
            except json.JSONDecodeError:continue
            scanned+=1
            name=str(record.get('name',''))
            domains=[key for key,words in FOCUS.items() if any(word in name.casefold() for word in words)]
            if not domains:continue
            for domain in domains:by_domain[domain]+=1
            if len(results)<max_results:
                results.append({'assembly':record.get('assembly'),'name':name,'token':record.get('token'),
                                'domains':domains,'body_present':record.get('has_body',False),
                                'il_status':record.get('il_status','not independently validated')})
    results.sort(key=lambda x:('damage' not in x['domains'],'projectile' not in x['domains'],x['name']))
    data={'format':'wosb-client-method-evidence-1','scanned_methods':scanned,'matched_by_topic':by_domain,
          'sample_limit':max_results,'methods':results,
          'research_questions':['Where does projectile collision become DamageData.HealthDamage?',
             'Which calculations run exclusively on the game server?',
             'Are penetration and angle thresholds in a different assembly or game build?',
             'Which sailing methods calculate real ship speed after wind/skill effects?',
             'Which protocol schemas can be observed from owned, passive recordings?'],
          'caution':'Method names are candidates. They do not prove behavior or a complete formula.'}
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(data,indent=2,ensure_ascii=False),encoding='utf-8')
    return data
