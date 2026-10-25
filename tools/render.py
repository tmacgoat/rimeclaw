# usage: python3 render.py [pet ...]   -- renders app/voice/<pet>/<id>.ogg from app/lines.json using voices.json
# engine "edge" (edge-tts), "kokoro" (voice, speed), "piper" (model path, length_scale), or
# "elevenlabs" (voice_id, model). ElevenLabs takes are read from tools/cache/el/<voice_id>/<line id>.wav|mp3
# (drop clips there by hand or from any ElevenLabs export). Lines with no take are left PENDING: no ogg is written,
# the app shows them as text-only bubbles (never a fallback voice), and index.json lists them under "pending".
#   PENDING=1  with ELEVENLABS_API_KEY set: synthesize just the pending lines through the ElevenLabs API (costs credits)
#   FORCE=1    re-run post-processing for every line that has audio
import asyncio, json, os, sys, subprocess, hashlib, shutil
H=os.path.dirname(os.path.abspath(__file__)); APP=os.path.join(H,'..','app'); CACHE=os.path.join(H,'cache')
V=json.load(open(os.path.join(H,'voices.json'))); LINES=json.load(open(os.path.join(APP,'lines.json')))
pets=sys.argv[1:] or list(V)
def dur(f):
    return float(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','csv=p=0',f]).strip())
def post(raw,out,cfg):
    af=cfg['post']
    if cfg.get('two_pass'):   # 2-pass loudnorm (same chain as voicetest post.sh, no reverb)
        r=subprocess.run(['ffmpeg','-hide_banner','-i',raw,'-af',af+',loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json','-f','null','-'],capture_output=True,text=True).stderr
        m=json.loads(r[r.rindex('{'):r.rindex('}')+1])
        af+=(',loudnorm=I=-16:TP=-1.5:LRA=11:measured_I=%s:measured_TP=%s:measured_LRA=%s:measured_thresh=%s:offset=%s:linear=true'
             %(m['input_i'],m['input_tp'],m['input_lra'],m['input_thresh'],m['target_offset']))
    subprocess.run(['ffmpeg','-y','-loglevel','error','-i',raw,'-af',af,'-ar','44100','-ac','1','-c:a','libvorbis','-q:a','4',out],check=True)
def el_api(cfg,text,raw):
    import urllib.request, time
    req=urllib.request.Request('https://api.elevenlabs.io/v1/text-to-speech/%s?output_format=mp3_44100_128'%cfg['voice_id'],
        data=json.dumps({'text':text,'model_id':cfg.get('api_model',cfg['model'])}).encode(),
        headers={'xi-api-key':os.environ['ELEVENLABS_API_KEY'],'Content-Type':'application/json'})
    for i in range(6):
        try:
            open(raw+'.tmp','wb').write(urllib.request.urlopen(req,timeout=120).read()); os.replace(raw+'.tmp',raw); return True
        except Exception as e:
            code=getattr(e,'code',0); print('elevenlabs error',code,e)
            if code in (400,401,402,403,422): return False   # quota, auth or bad request: stop, leave pending
            time.sleep(10*(i+1))                          # 429 / 5xx: back off slowly
    return False
async def edge_one(sem,cfg,text,raw):
    import edge_tts
    async with sem:
        for i in range(5):
            try:
                await edge_tts.Communicate(text,cfg['voice'],rate=cfg['rate'],pitch=cfg['pitch']).save(raw+'.tmp'); os.replace(raw+'.tmp',raw); return
            except Exception as e:
                print('retry',i,e); await asyncio.sleep(2+i*2)
        raise RuntimeError('edge failed: '+text[:40])
for pet in pets:
    cfg=V[pet]; od=os.path.join(APP,'voice',pet); os.makedirs(od,exist_ok=True); os.makedirs(CACHE,exist_ok=True)
    key=lambda t: hashlib.md5((json.dumps({k:cfg[k] for k in cfg if k!='post'},sort_keys=True)+t).encode()).hexdigest()
    jobs=[]; pending=[]
    if cfg['engine']=='elevenlabs':
        td=os.path.join(CACHE,'el',cfg['voice_id']); os.makedirs(td,exist_ok=True)
        api=os.environ.get('PENDING') and os.environ.get('ELEVENLABS_API_KEY')
        for ln in LINES[pet]:
            hit=[os.path.join(td,ln['id']+e) for e in ('.wav','.mp3') if os.path.exists(os.path.join(td,ln['id']+e))]
            if not hit and api:
                tgt=os.path.join(td,ln['id']+'.mp3')
                if el_api(cfg,cfg.get('tags',{}).get(ln['cat'],'')+ln['text'],tgt): hit=[tgt]
                else: api=None
            if hit: ln['_raw']=hit[0]
            else: ln['_raw']=None; pending.append(ln['id'])
    for ln in (LINES[pet] if cfg['engine']!='elevenlabs' else []):
        ext='.mp3' if cfg['engine']=='edge' else '.wav'
        raw=os.path.join(CACHE,key(ln['text'])+ext); ln['_raw']=raw
        if not os.path.exists(raw): jobs.append((ln['text'],raw))
    print(pet,'to synth',len(jobs))
    if cfg['engine']=='edge':
        async def go():
            sem=asyncio.Semaphore(6); await asyncio.gather(*[edge_one(sem,cfg,t,r) for t,r in jobs])
        asyncio.run(go())
    elif cfg['engine']=='kokoro':
        from kokoro_onnx import Kokoro; import soundfile as sf
        k=Kokoro('/workspace/tts/kokoro-v1.0.onnx','/workspace/tts/voices-v1.0.bin')
        for t,r in jobs:
            a,sr=k.create(t,voice=cfg['voice'],speed=cfg.get('speed',1.0),lang='en-us'); sf.write(r,a,sr)
    elif cfg['engine']=='piper':
        import wave; from piper import PiperVoice, SynthesisConfig
        pv=PiperVoice.load(cfg['voice'])
        for t,r in jobs:
            with wave.open(r,'wb') as w: pv.synthesize_wav(t,w,syn_config=SynthesisConfig(length_scale=cfg.get('length_scale',1.0)))
    idx={}
    keep=set()
    for ln in LINES[pet]:
        if not ln['_raw']: continue                       # pending: text-only until voiced
        out=os.path.join(od,ln['id']+'.ogg'); keep.add(os.path.basename(out))
        stale=os.path.exists(out) and os.path.getmtime(out)<os.path.getmtime(ln['_raw'])
        if not os.path.exists(out) or stale or os.environ.get('FORCE'): post(ln['_raw'],out,cfg); print('rendered',pet,ln['id'])
        idx[ln['id']]=round(dur(out),2)
    for f in os.listdir(od):
        if f.endswith('.ogg') and f not in keep: os.remove(os.path.join(od,f))
    json.dump({'voice':{k:cfg[k] for k in cfg if k not in ('post','tags')},'durations':idx,'pending':pending},open(os.path.join(od,'index.json'),'w'),indent=0)
    print(pet,'done',len(idx),'voiced, total s',round(sum(idx.values())),'| pending',len(pending),'chars',sum(len(l['text']) for l in LINES[pet] if l['id'] in pending))
