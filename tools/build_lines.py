import json, re, sys, hashlib
sys.path.insert(0, '.')
import lines_src as L
PROF = re.compile(r"\b(\w*fuck\w*|\w*shit\w*|ass|asses|dumbass|bastard\w*|piss\w*|grown-ass|goddamn|damn\w*)\b", re.I)
GOB = [(r"\bRimeclaw\b","Skarn"),(r"\bdragons\b","goblins"),(r"\bDragons\b","Goblins"),(r"\bdragon\b","goblin"),
       (r"\bscales\b","warts"),(r"\bfreeze your\b","bite your"),(r"\bfreezing your\b","biting your")]
cats = {'roast':L.ROASTS,'rant':L.RANTS,'poke':L.POKE,'pickup':L.PICKUP,'land':L.LAND,'wake':L.WAKE,'sleep':L.SLEEP,
        'greet_morning':L.GREET_MORNING,'greet_day':L.GREET_DAY,'greet_night':L.GREET_NIGHT,'late':L.LATE,
        'battery':L.BATTERY,'staring':L.STARING}
out = {'dragon':[], 'goblin':[]}
for pet in out:
    n=0
    for cat, arr in list(cats.items())+[('roast', L.CLEAN_EXTRA)]:
        for t in arr:
            extra = arr is L.CLEAN_EXTRA
            txt = t
            if pet=='goblin':
                for a,b in GOB: txt = re.sub(a,b,txt)
            vulgar = bool(PROF.search(txt))
            mode = 'clean_only' if extra else ('vulgar' if vulgar else 'both')
            lid = f"{cat}_{hashlib.md5(txt.encode()).hexdigest()[:8]}"
            out[pet].append({'id':lid,'cat':cat,'text':txt,'mode':mode})
json.dump(out, open('../app/lines.json','w'), indent=1)
for pet in out:
    a=out[pet]
    r=[x for x in a if x['cat']=='roast']; ra=[x for x in a if x['cat']=='rant']
    print(pet, len(a), 'roasts vulgar-mode', sum(x['mode']!='clean_only' for x in r), 'clean-mode', sum(x['mode']!='vulgar' for x in r),
          'rants', len(ra), 'clean rants', sum(x['mode']!='vulgar' for x in ra))
    print(' rant words', sorted(len(x['text'].split()) for x in ra))
# blocked terms check
bad = re.compile(r"blazer|moda|rip city|targaryen|westeros|valyria|iron throne|colour|honour|favour|bloody|bollocks|arse|wanker|mate\b|knackered|rubbish|cheers", re.I)
for x in out['dragon']:
    if bad.search(x['text']): print('BAD', x['text'])
for x in out['dragon']:
    if x['mode']!='vulgar' and PROF.search(x['text']): print('LEAK',x)
