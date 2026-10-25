# usage: python3 render.py [pet ...]   -- renders app/voice/<pet>/<id>.ogg from app/lines.json using voices.json
# engine "edge" (edge-tts), "kokoro" (voice, speed), "piper" (model path, length_scale), or "file" (dir of pre-rendered <id>.wav/mp3)
import asyncio, json, os, sys, subprocess, hashlib, shutil
H=os.path.dirname(os.path.abspath(__file__)); APP=os.path.join(H,'..','app'); CACHE=os.path.join(H,'cache')
V=json.load(open(os.path.join(H,'voices.json'))); LINES=json.load(open(os.path.join(APP,'lines.json')))
pets=sys.argv[1:] or list(V)
def dur(f):
    return float(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','csv=p=0',f]).strip())
def post(raw,out,cfg):
    subprocess.run(['ffmpeg','-y','-loglevel','error','-i',raw,'-af',cfg['post'],'-ar','44100','-ac','1','-c:a','libvorbis','-q:a','4',out],check=True)
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
    jobs=[]
    for ln in LINES[pet]:
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
        out=os.path.join(od,ln['id']+'.ogg'); keep.add(os.path.basename(out))
        post(ln['_raw'],out,cfg); idx[ln['id']]=round(dur(out),2)
    for f in os.listdir(od):
        if f.endswith('.ogg') and f not in keep: os.remove(os.path.join(od,f))
    json.dump({'voice':{k:cfg[k] for k in cfg if k!='post'},'durations':idx},open(os.path.join(od,'index.json'),'w'),indent=0)
    print(pet,'done',len(idx),'files, total s',round(sum(idx.values())))
