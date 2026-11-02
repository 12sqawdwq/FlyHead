"""HTTP negative tests and start/cancel; no robot prepare/hold or movement requests."""
import json,pathlib,time,urllib.request,urllib.error,http.cookiejar
ROOT=pathlib.Path(__file__).resolve().parents[1];BASE='http://127.0.0.1:8093'
H={'Host':'127.0.0.1:18093','Origin':'http://127.0.0.1:18093','Content-Type':'application/json'}
def client():return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
def req(c,path,d=None,headers=H):
 try:
  r=c.open(urllib.request.Request(BASE+path,headers=headers,data=None if d is None else json.dumps(d).encode()),timeout=8)
  return r.status,json.load(r)
 except urllib.error.HTTPError as e:return e.code,e.read().decode()
def login(c):assert req(c,'/eeg/login',{'password':(ROOT/'console-access.code').read_text().strip()})[0]==200
a,b=client(),client();results={}
results['unauthenticated']=req(a,'/eeg/status')[0]==401
results['wrong_origin']=req(a,'/eeg/login',{},dict(H,Origin='http://evil.invalid'))[0]==403
login(a);login(b)
s=req(a,'/eeg/status')[1];old=s['ticket'];req(a,'/eeg/release',{})
results['released_ticket_rejected']=req(a,'/eeg/start',dict(ticket=old,dataset='bcic4_2b',subject=1,start=0,count=1))[0]==409
s=req(a,'/eeg/status')[1]
results['unknown_dataset_rejected']=req(a,'/eeg/start',dict(ticket=s['ticket'],dataset='fake',subject=1,start=0,count=1))[0]==400
s=req(a,'/eeg/status')[1]
assert not s['busy'],'Wait for operator job to finish before tests'
assert req(a,'/eeg/start',dict(ticket=s['ticket'],dataset='bcic4_2b',subject=1,start=0,count=1))[0]==200
s=req(b,'/eeg/status')[1]
results['second_page_rejected']=req(b,'/eeg/start',dict(ticket=s['ticket'],dataset='bcic4_2b',subject=1,start=0,count=1))[0]==400
results['stop_accepted']=req(a,'/eeg/stop',{})[0]==200
time.sleep(.5);s=req(a,'/eeg/status')[1];results['job_stopped']=not s['busy'] and not s['held']
(ROOT/'http-test.json').write_text(json.dumps(results,indent=2));print(results);assert all(results.values())
