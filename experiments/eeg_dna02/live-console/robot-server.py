import argparse
import asyncio
import functools
import hmac
import http.cookies
import json
import logging
from logging.handlers import RotatingFileHandler
import pathlib
import secrets
import signal
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
from websockets.legacy.server import serve
from policy import Arbiter, FreshSession
from services import Services, ROOT
from robot import Sensors
from map_archive import MapArchive

class Core:
    def __init__(self, dry=False):
        self.lock = threading.RLock()
        self.arbiter = Arbiter()
        self.services = Services(dry)
        self.sensors = Sensors(self,dry)
        self.sessions = {}
        self.connections = set()
        self.dry = dry
        self.managing = False
        self.map_archive = MapArchive()

    def cookie(self, header):
        try:
            c = http.cookies.SimpleCookie(); c.load(header or '')
            token = c['console_session'].value
            return token if self.sessions.get(token,0)>time.monotonic() else None
        except (KeyError, http.cookies.CookieError):
            return None

    def snapshot(self):
        with self.lock:
            now=time.monotonic()
            f,t=self.arbiter.output(now)
            return dict(self.sensors.snapshot(now), dry=self.dry, mode=self.arbiter.mode,
                enabled=self.arbiter.owner is not None, target=[f,t], reason=self.arbiter.reason,
                generation=self.arbiter.generation, services=self.services.snapshot(),
                events=self.services.events[-15:], locked=self.services.blocked)

def handler_class(core, password, origin):
    host=urlsplit(origin).netloc
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):
            pass # Never log URLs, cookies, passwords or commands.
        def setup(self):
            super().setup()
            self.connection.settimeout(2)
        def reply(self,code,body,kind='application/json',cookie=None):
            if not isinstance(body,bytes):body=json.dumps(body,ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header('Content-Type',kind)
            self.send_header('Content-Length',str(len(body)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('X-Frame-Options','DENY')
            self.send_header('Referrer-Policy','no-referrer')
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob:; connect-src 'self' ws://127.0.0.1:18091; frame-ancestors 'none'")
            if cookie:self.send_header('Set-Cookie',cookie)
            self.end_headers()
            self.wfile.write(body)
        def do_GET(self):
            if self.headers.get('Host') != host:
                return self.reply(403,{'error':'Host rejected'})
            path=urlsplit(self.path).path
            if path in ('/','/app.js','/mapview.js','/style.css'):
                name={'/':'index.html','/app.js':'app.js','/mapview.js':'mapview.js','/style.css':'style.css'}[path]
                kind={'/':'text/html; charset=utf-8','/app.js':'text/javascript; charset=utf-8','/mapview.js':'text/javascript; charset=utf-8','/style.css':'text/css; charset=utf-8'}[path]
                return self.reply(200,(ROOT/name).read_bytes(),kind)
            with core.lock:
                if not core.cookie(self.headers.get('Cookie')):
                    return self.reply(401,{'error':'请先登录'})
            if path=='/api/status':
                return self.reply(200,core.snapshot())
            if path=='/api/map/meta':
                return self.reply(200,core.map_archive.metadata)
            if path=='/api/map/points':
                if core.map_archive.payload is None:return self.reply(503,{'error':'地图不可用'})
                return self.reply(200,core.map_archive.payload,'application/octet-stream')
            if path=='/camera.jpg':
                with core.lock:
                    jpeg=core.sensors.jpeg
                    fresh=time.monotonic()-core.sensors.camera['at']<.6
                if jpeg and fresh:
                    return self.reply(200,jpeg,'image/jpeg')
                return self.reply(503,{'error':'无新鲜相机帧'})
            self.reply(404,{'error':'不存在'})
        def do_POST(self):
            if self.headers.get('Host')!=host or self.headers.get('Origin')!=origin:
                return self.reply(403,{'error':'Origin rejected'})
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<2048:raise ValueError()
                data=json.loads(self.rfile.read(size))
            except Exception:
                return self.reply(400,{'error':'无效请求'})
            if self.path=='/login':
                if not hmac.compare_digest(str(data.get('password','')),password):
                    time.sleep(.3)
                    return self.reply(403,{'error':'访问码不正确'})
                with core.lock:
                    core.sessions={k:v for k,v in core.sessions.items() if v>time.monotonic()}
                    if len(core.sessions)>=16:return self.reply(429,{'error':'会话过多'})
                    session=secrets.token_urlsafe(32)
                    core.sessions[session]=time.monotonic()+28800
                return self.reply(200,{'ok':True},cookie='console_session='+session+'; HttpOnly; SameSite=Strict; Path=/; Max-Age=28800')
            with core.lock:
                if not core.cookie(self.headers.get('Cookie')):
                    return self.reply(401,{'error':'未登录'})
                if self.path=='/stop':
                    core.arbiter.stop('网页停止')
                    return self.reply(200,{'ok':True})
            self.reply(404,{'error':'不存在'})
    return Handler

async def websocket(core, origin, ws, path):
    if ws.request_headers.get('Origin')!=origin:
        await ws.close(1008,'Origin rejected');return
    with core.lock:
        authenticated=core.cookie(ws.request_headers.get('Cookie'))
        if not authenticated or len(core.connections)>=4:
            authenticated=None
        else:
            core.connections.add(ws)
    if not authenticated:
        await ws.close(1008,'Authentication required');return
    owner=secrets.token_hex(16)
    session=FreshSession(time.monotonic())
    try:
        await ws.send(json.dumps({'type':'hello','ticket':session.ticket}))
        async for raw in ws:
            try:
                p=json.loads(raw,parse_constant=lambda x: (_ for _ in ()).throw(ValueError('Nonfinite')))
                with core.lock:
                    if not core.cookie(ws.request_headers.get('Cookie')):raise ValueError('登录过期')
                    session.accept(p,time.monotonic())
                    action=p.get('action')
                    if action=='stop':core.arbiter.stop('操作者停止')
                    elif action=='enable':core.arbiter.enable(owner,time.monotonic(),core.sensors.ready(time.monotonic()),source=p.get('source','manual'))
                    elif action=='drive':core.arbiter.drive(owner,time.monotonic(),p.get('forward'),p.get('turn'),core.sensors.ready(time.monotonic()),source=p.get('source','manual'))
                    elif action=='mode':core.arbiter.switch(p.get('mode'))
                    elif action=='reset_obstacle':
                        s=core.sensors
                        if (core.arbiter.owner or time.monotonic()-s.safety_at>.3 or not s.safety.get('radar_reset_ready')
                            or not s.safety.get('measured_wheel_stationary') or s.safety.get('authority_attempted')):
                            raise ValueError('仅允许新会话静止且雷达清空后手动复位障碍锁存')
                        s.reset_requested=True
                    elif action not in ('ping','service'):
                        raise ValueError('未知动作')
                    if action=='service':
                        if core.arbiter.owner:raise ValueError('请先停止并撤销使能')
                        if core.managing:raise ValueError('服务操作进行中')
                        name=p.get('name');op=p.get('operation')
                        if name not in ('camera','lidar','chassis'):raise ValueError('未知服务')
                        if op not in ('start','stop'):raise ValueError('未知操作')
                        if name=='chassis' and op=='start':
                            if core.services.alive('chassis'):raise ValueError('运动会话已经打开')
                            if core.services.blocked:raise ValueError('底盘已锁定，请现场检查')
                            core.sensors.safety_at=0
                        core.managing=True
                if action=='service':
                    try:
                        await asyncio.get_running_loop().run_in_executor(None,getattr(core.services,op),name)
                    finally:
                        with core.lock:core.managing=False
                session.issued=time.monotonic()
                await ws.send(json.dumps({'type':'ack','seq':session.seq,'ticket':session.ticket,'ok':True}))
            except (ValueError,KeyError,TypeError) as exc:
                with core.lock:
                    if core.arbiter.owner==owner:core.arbiter.stop(str(exc))
                # A failed freshness check invalidates the connection. Other validation errors
                # also close it, requiring an explicit fresh operator enable after reconnect.
                await ws.send(json.dumps({'type':'error','error':str(exc)},ensure_ascii=False))
                await ws.close(1008,'Rejected');break
    finally:
        with core.lock:
            if core.arbiter.owner==owner:core.arbiter.stop('控制连接断开')
            core.connections.discard(ws)

async def main(args):
    (ROOT/'logs').mkdir(exist_ok=True)
    (ROOT/'run').mkdir(exist_ok=True,mode=0o700)
    password_path=ROOT/'access.code'
    if not password_path.exists():
        password_path.write_text(secrets.token_urlsafe(18))
        password_path.chmod(0o600)
    core=Core(args.dry)
    core.map_archive.load()
    server=ThreadingHTTPServer(('127.0.0.1',args.http_port),handler_class(core,password_path.read_text().strip(),args.origin))
    threading.Thread(target=server.serve_forever,daemon=True).start()
    for fn in (core.sensors.ros_loop,core.sensors.camera_loop):
        threading.Thread(target=fn,daemon=True).start()
    stop=asyncio.Event()
    loop=asyncio.get_running_loop()
    for sig in (signal.SIGINT,signal.SIGTERM):loop.add_signal_handler(sig,stop.set)
    async with serve(functools.partial(websocket,core,args.origin),'127.0.0.1',args.ws_port,
            max_size=2048,max_queue=1,ping_interval=10,close_timeout=1):
        logging.info('Console ready; dry=%s',args.dry)
        await stop.wait()
        with core.lock:core.arbiter.stop('服务关闭')
        await asyncio.sleep(.4)
        for name in ('chassis','camera','lidar'):
            try:await loop.run_in_executor(None,core.services.stop,name)
            except Exception:logging.exception('Child stop failed')
    core.sensors.running=False
    server.shutdown()

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--dry',action='store_true')
    p.add_argument('--http-port',type=int,default=8090)
    p.add_argument('--ws-port',type=int,default=8091)
    p.add_argument('--origin',default='http://127.0.0.1:18090')
    args=p.parse_args()
    (ROOT/'logs').mkdir(exist_ok=True)
    logging.basicConfig(level=logging.INFO,handlers=[RotatingFileHandler(str(ROOT/'logs'/'console.log'),maxBytes=1000000,backupCount=2)])
    asyncio.run(main(args))

