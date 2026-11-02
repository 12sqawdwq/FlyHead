"""Authenticated same-origin EEG console; original navigation API stays separate and locked."""
import asyncio,json,pathlib,secrets,time,os,signal,collections,hmac
from aiohttp import web,ClientSession,ClientTimeout
ROOT=pathlib.Path(__file__).resolve().parents[1]
WEB=ROOT/'web-console';ORIGIN='http://127.0.0.1:18093'
FLYPY='<SERVER_ROOT>/inference_service/deployments/flywire_lif_001/env/bin/python'
class Console:
 def __init__(self):
  self.navigation_locked=False;self.sessions={};self.owner=None;self.job=None;self.task=None;self.events=collections.deque(maxlen=800);self.serial=0
  self.phase='等待选择 EEG 数据';self.latest=None;self.latest_at=0;self.hold_until=0;self.pulse_until=0;self.pulse_w=0;self.used=set();self.relay=None;self.relay_status={};self.relay_at=0;self.relay_nonce=None;self.relay_seq=0;self.reset_requested=False
 def emit(self,row):
  self.serial+=1;self.events.append(dict(row,id=self.serial))
 def release(self):self.hold_until=0;self.pulse_until=0;self.pulse_w=0
 async def stop(self):
  self.release()
  if self.task and not self.task.done() and self.job is None:
   self.task.cancel()
   try:await self.task
   except asyncio.CancelledError:pass
  if self.job and self.job.returncode is None:
   os.killpg(self.job.pid,signal.SIGTERM)
   try:await asyncio.wait_for(self.job.wait(),5)
   except asyncio.TimeoutError:os.killpg(self.job.pid,signal.SIGKILL);await self.job.wait()
  self.phase='已停止推理；运动使能已撤销'
 async def run(self,cfg):
  self.phase='正在启动推理';self.latest=None;self.used.clear()
  try:
   self.job=await asyncio.create_subprocess_exec(FLYPY,'-u',str(ROOT/'live-console/worker.py'),json.dumps(cfg),stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,start_new_session=True,env=dict(os.environ,TRITON_CACHE_DIR=str(ROOT/'triton_cache'),OPENBLAS_NUM_THREADS='4',OMP_NUM_THREADS='4'))
   async def errors():
    out=bytearray()
    while True:
     b=await self.job.stderr.read(4096)
     if not b:break
     out.extend(b);out[:max(0,len(out)-12000)]=b''
    return out.decode(errors='replace')
   err=asyncio.create_task(errors())
   while True:
    line=await self.job.stdout.readline()
    if not line:break
    row=json.loads(line);self.emit(row)
    if row['type']=='phase':self.phase=row['phase']
    if row['type']=='window':
     self.latest=row;self.latest_at=time.monotonic()
     # Parent/child are on one host: reject buffered neural output before execution.
     if time.monotonic()-row['generated_mono']>.25:continue
     trial=row['trial'];w=row['intent']['w']
     if self.hold_until>time.monotonic() and row['gate']=='accepted' and row['phase']=='stimulus' and trial not in self.used and abs(w)>.001 and self.relay_status.get('ready') and time.monotonic()-self.relay_at<.3:
      self.used.add(trial);self.pulse_until=time.monotonic()+.20;self.pulse_w=max(-.1,min(.1,w));self.emit(dict(type='execution',message='请求短时转向；等待机器人确认',turn=self.pulse_w))
   rc=await self.job.wait();error=await err
   self.phase='回放完成' if rc==0 else '推理中止/失败：'+error[-900:]
  except Exception as e:self.phase='推理失败：'+str(e)
  finally:self.release();self.emit(dict(type='phase',phase=self.phase));self.job=None
 async def prepare(self):
  self.release()
  if not self.navigation_locked:raise ValueError('原导航服务未确认运动锁定，拒绝连接底盘')
  if self.relay and self.relay.returncode is None:raise ValueError('机器人通道已打开；请先结束再重新准备')
  self.relay_status={'error':'正在连接机器人'}
  self.relay=await asyncio.create_subprocess_exec('ssh','-T','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','ConnectTimeout=5','<robot-ssh-alias>','PYTHONPATH=<ROBOT_HOME>/eeg_robot_bridge/vendor python3 -u <ROBOT_HOME>/robot_console/eeg_relay.py',stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
  asyncio.create_task(self.read_relay(self.relay))
 async def read_relay(self,p):
  async def errtail():return (await p.stderr.read(8192)).decode(errors='replace')
  errors=asyncio.create_task(errtail())
  try:
   while True:
    line=await p.stdout.readline()
    if not line:break
    row=json.loads(line);self.relay_status=row;self.relay_at=time.monotonic();self.relay_nonce=row.get('nonce')
   await p.wait();self.relay_status={'error':(await errors)[-700:] or '机器人通道已断开'}
  except Exception as e:self.relay_status={'error':str(e)}
  finally:self.release();self.relay_nonce=None
 async def watchdog(self):
  while True:
   await asyncio.sleep(.05);now=time.monotonic()
   active=self.navigation_locked and now<self.hold_until and now<self.pulse_until and now-self.latest_at<.25
   if self.relay and self.relay.returncode is None and self.relay_nonce:
    nonce=self.relay_nonce;self.relay_nonce=None;self.relay_seq+=1
    try:
     self.relay.stdin.write((json.dumps(dict(nonce=nonce,seq=self.relay_seq,turn=self.pulse_w if active else 0.0,reset=c.reset_requested))+'\n').encode());await asyncio.wait_for(self.relay.stdin.drain(),.1);self.reset_requested=False
    except Exception:self.release()
c=Console();codepath=ROOT/'console-access.code'
if not codepath.exists():codepath.write_text(secrets.token_urlsafe(24));codepath.chmod(0o600)
password=codepath.read_text().strip()
@web.middleware
async def security(request,handler):
 if request.host!='127.0.0.1:18093':raise web.HTTPForbidden(text='Host rejected')
 if request.method!='GET' and request.headers.get('Origin')!=ORIGIN:raise web.HTTPForbidden(text='Origin rejected')
 if request.path.startswith('/eeg/') and request.path!='/eeg/login':
  sid=request.cookies.get('eeg_session');s=c.sessions.get(sid)
  if not s or s['expiry']<time.monotonic():raise web.HTTPUnauthorized(text='请先输入访问码')
  request['sid']=sid
  if request.method=='POST':
   d=await request.json();request['data']=d
   if request.path not in ('/eeg/stop','/eeg/release'):
    if d.get('ticket')!=s['ticket'] or time.monotonic()-s['issued']>.6:raise web.HTTPConflict(text='请求过期，请重新操作')
    s['ticket']=secrets.token_hex(16);s['issued']=time.monotonic()
 try:return await handler(request)
 except ValueError as e:raise web.HTTPBadRequest(text=str(e))
async def login(r):
 d=await r.json()
 if not hmac.compare_digest(str(d.get('password','')),password):raise web.HTTPForbidden(text='访问码错误')
 sid=secrets.token_urlsafe(32);c.sessions[sid]=dict(expiry=time.monotonic()+28800,ticket=secrets.token_hex(16),issued=time.monotonic())
 response=web.json_response({'ok':True});response.set_cookie('eeg_session',sid,httponly=True,samesite='Strict',max_age=28800);return response
async def status(r):
 s=c.sessions[r['sid']];s['issued']=time.monotonic();s['ticket']=secrets.token_hex(16)
 return web.json_response(dict(ticket=s['ticket'],phase=c.phase,busy=bool(c.job or c.task and not c.task.done()),events=[e for e in c.events if e['id']>int(r.query.get('after','0'))],robot=c.relay_status,robot_age=time.monotonic()-c.relay_at,held=time.monotonic()<c.hold_until,owner=c.owner==r['sid'],datasets=[{'id':'bcic4_2b','name':'BCI IV 2b · 官方测试集','subjects':list(range(1,10))}]))
async def action(r):
 d=r['data'];a=r.match_info['action'];sid=r['sid']
 if a in ('stop','release'):
  for session in c.sessions.values():session['ticket']=secrets.token_hex(16)
  c.release()
  if a=='stop':await c.stop()
  return web.json_response({'ok':True})
 if c.owner not in (None,sid) and (c.job or time.monotonic()<c.hold_until):raise ValueError('另一个页面持有回放控制权')
 if a=='start':
  if c.job or c.task and not c.task.done():raise ValueError('已有推理任务')
  if d.get('dataset')!='bcic4_2b':raise ValueError('不支持的数据集')
  sub=d.get('subject');start=d.get('start');count=d.get('count')
  if any(type(x)is not int for x in [sub,start,count]) or not 1<=sub<=9 or not 0<=start<280 or not 1<=count<=10:raise ValueError('数据选择范围错误')
  c.release();c.owner=sid;c.task=asyncio.create_task(c.run(dict(subject=sub,start=start,count=count)))
 elif a=='prepare':c.owner=sid;await c.prepare()
 elif a=='hold':
  if not c.navigation_locked or not c.relay_status.get('ready') or time.monotonic()-c.relay_at>.3:raise ValueError('机器人未就绪，不能使能')
  if c.owner!=sid:raise ValueError('请先取得当前回放会话')
  c.hold_until=time.monotonic()+.25
 elif a=='reset_obstacle':
  c.release();c.reset_requested=True
 elif a=='end_robot':
  c.release()
  if c.relay and c.relay.returncode is None:c.relay.stdin.close()
 else:raise ValueError('未知操作')
 return web.json_response({'ok':True})
async def navigation_guard():
 async with ClientSession(timeout=ClientTimeout(total=.25)) as client:
  while True:
   try:
    async with client.get('http://127.0.0.1:8091/diagnostics') as r:
     d=await r.json();c.navigation_locked=d['status']['chassis_disabled'] and not d['session_running']
   except Exception:c.navigation_locked=False
   if not c.navigation_locked:c.release()
   await asyncio.sleep(.2)
async def startup(app):
 app['watchdog']=asyncio.create_task(c.watchdog());app['navigation_guard']=asyncio.create_task(navigation_guard())
async def cleanup(app):await c.stop();app['watchdog'].cancel();app['navigation_guard'].cancel()
app=web.Application(middlewares=[security],client_max_size=4096)
app.router.add_post('/eeg/login',login);app.router.add_get('/eeg/status',status);app.router.add_post('/eeg/{action}',action)
app.router.add_get('/',lambda r:web.FileResponse(WEB/'index.html',headers={'Cache-Control':'no-store'}));app.router.add_static('/vendor/',(WEB/'vendor').resolve());app.router.add_static('/navigation/',(WEB/'navigation').resolve());app.router.add_static('/',WEB)
app.on_startup.append(startup);app.on_cleanup.append(cleanup)
if __name__=='__main__':web.run_app(app,host='127.0.0.1',port=8093)





