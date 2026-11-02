"""Robot-local relay to existing authenticated robot_console; never opens chassis serial.
Explicit preparation starts bounded existing services. No automatic obstacle reset or authority retry.
"""
import asyncio,json,secrets,time,sys,pathlib,urllib.request,http.cookiejar
from websockets.legacy.client import connect
H={'Host':'127.0.0.1:18090','Origin':'http://127.0.0.1:18090','Content-Type':'application/json'}
jar=http.cookiejar.CookieJar();http=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
def req(path,data=None):
 r=urllib.request.Request('http://127.0.0.1:8090'+path,data=None if data is None else json.dumps(data).encode(),headers=H)
 return json.load(http.open(r,timeout=.4))
async def main():
 req('/login',{'password':pathlib.Path('<ROBOT_HOME>/robot_console/access.code').read_text().strip()})
 async with connect('ws://127.0.0.1:8091',extra_headers={'Origin':H['Origin'],'Cookie':'; '.join(c.name+'='+c.value for c in jar)}) as ws:
  hello=json.loads(await ws.recv());ticket=hello['ticket'];seq=0
  async def command(action,**kw):
   nonlocal ticket,seq
   seq+=1;await ws.send(json.dumps(dict(action=action,seq=seq,ticket=ticket,source='eeg',**kw)))
   r=json.loads(await asyncio.wait_for(ws.recv(),6 if action=='service' else .35))
   if not r.get('ok'):raise RuntimeError(r.get('error','Robot rejected command'))
   ticket=r['ticket']
  await command('mode',mode='eeg')
  for name in ['lidar','chassis']:
   s=req('/api/status')
   if not s['services'][name]['running']:await command('service',name=name,operation='start')
  reader=asyncio.StreamReader();protocol=asyncio.StreamReaderProtocol(reader)
  await asyncio.get_running_loop().connect_read_pipe(lambda:protocol,sys.stdin)
  enabled=False;pulse_end=0;last_seq=0;zero_since=time.monotonic()
  try:
   while True:
    s=await asyncio.to_thread(req,'/api/status') if hasattr(asyncio,'to_thread') else req('/api/status')
    nonce=secrets.token_hex(16);issued=time.monotonic()
    print(json.dumps(dict(nonce=nonce,ready=s['ready'],safety=s['safety'],safety_age=s['safety_age'],services=s['services'],reason=s.get('reason'),mode=s['mode'])),flush=True)
    try:line=await asyncio.wait_for(reader.readline(),.12)
    except asyncio.TimeoutError:
     if enabled:await command('stop');enabled=False
     else:await command('ping')
     continue
    if not line:break
    p=json.loads(line);now=time.monotonic()
    if p.get('nonce')!=nonce or now-issued>.2 or type(p.get('seq'))is not int or p['seq']<=last_seq:raise RuntimeError('Stale/replayed relay command')
    last_seq=p['seq'];turn=p.get('turn')
    if type(turn)not in (int,float) or not -.1<=turn<=.1:raise RuntimeError('Turn outside bound')
    if p.get('reset'):
     if enabled:raise RuntimeError('Cannot reset while enabled')
     await command('reset_obstacle');continue
    if turn:
     if not enabled:
      if now-zero_since<.5:raise RuntimeError('Pulse cooldown')
      await command('enable');enabled=True;pulse_end=now+.25
     if now>=pulse_end:raise RuntimeError('Local pulse duration exhausted')
     await command('drive',forward=0.,turn=turn)
    else:
     if enabled:await command('stop');enabled=False;zero_since=now
     else:await command('ping')
    await asyncio.sleep(.02)
  finally:
   if ws.open:
    try:await command('stop')
    except Exception:pass
asyncio.run(main())

