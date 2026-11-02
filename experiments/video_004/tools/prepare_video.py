"""Causal 10Hz sampling of genuine publisher RGB video; no neural inference."""
from pathlib import Path
from fractions import Fraction
import hashlib,json,shutil,subprocess
import av
import numpy as np
from PIL import Image,ImageOps
ROOT=Path(__file__).resolve().parents[1]
if (ROOT/'protocol_lock.json').exists():raise RuntimeError('REFUSE_LOCKED_INPUT_REGENERATION')
for d in ['inputs','config','vendor/fly_mapping']:(ROOT/d).mkdir(parents=True,exist_ok=True)
for name in ['vision.py','commands.py','__init__.py']:
 shutil.copyfile(ROOT.parent/'mapping_002/vendor/fly_mapping'/name,ROOT/'vendor/fly_mapping'/name)
for name in ['readout_registry.json','startup_registry.json','mapping_profile.json']:
 shutil.copyfile(ROOT.parent/'mapping_002/config'/name,ROOT/'config'/name)
shutil.copyfile(ROOT.parent/'optimization_003/event_model.py',ROOT/'vendor/event_model.py')
shutil.copyfile(ROOT.parent/'mapping_002/service/engines.py',ROOT/'vendor/engines.py')
manifest=[]
for row in json.loads((ROOT/'evidence/VIDEO_SOURCES.json').read_text()):
 source=ROOT/row['path'];assert hashlib.sha256(source.read_bytes()).hexdigest()==row['sha256']
 decoded=[];times=[];raw=[]
 with av.open(str(source)) as container:
  stream=container.streams.video[0]
  for index,frame in enumerate(container.decode(stream)):
   assert frame.pts is not None
   pts=Fraction(frame.pts)*frame.time_base
   if times:assert pts>times[-1]
   times.append(pts);raw.append({'index':index,'pts':frame.pts,'time_base':str(frame.time_base)})
   decoded.append(np.asarray(ImageOps.fit(frame.to_image().convert('RGB'),(160,120),method=Image.Resampling.LANCZOS)))
   if pts>=8:break
 assert times[0]==0 and times[-1]>=8
 selected=[];entries=[]
 for k in range(80):
  target=Fraction(k,10)
  index=max(i for i,t in enumerate(times) if t<=target)
  selected.append(decoded[index]);entries.append(dict(raw[index],media_pts_seconds=float(times[index]),replay_seconds=float(target),sampling_age_seconds=float(target-times[index])))
 frames=np.stack(selected).astype(np.uint8)
 assert frames.shape==(80,120,160,3)
 name='tum_fr1_'+row['scene'];np.save(ROOT/'inputs'/(name+'.npy'),frames,allow_pickle=False)
 (ROOT/'inputs'/(name+'_timestamps.json')).write_bytes((json.dumps(entries,indent=2)+'\n').encode())
 preview=ROOT/'inputs'/(name+'.mp4')
 args=[shutil.which('ffmpeg'),'-v','error','-n','-f','rawvideo','-pixel_format','rgb24','-video_size','160x120','-framerate','10','-i','pipe:0','-an','-c:v','libx264','-pix_fmt','yuv420p','-movflags','+faststart',str(preview)]
 subprocess.run(args,input=frames.tobytes(),check=True,timeout=30)
 for k in [0,30,60]:Image.fromarray(frames[k]).save(ROOT/'inputs'/(name+'_frame'+str(k)+'.png'))
 manifest.append({'name':name,'source_sha256':row['sha256'],'frames_file':'inputs/'+name+'.npy','timestamps_file':'inputs/'+name+'_timestamps.json','preview_file':'inputs/'+name+'.mp4','frames':80,'sample_hz':10,'interval_ms':100,'duration_seconds':8,'genuine_recorded_video':True})
(ROOT/'config/videos.json').write_bytes((json.dumps(manifest,indent=2)+'\n').encode())
(ROOT/'evidence/PREPARATION_ENV.json').write_bytes((json.dumps({'av':av.__version__,'numpy':np.__version__,'PIL':Image.__version__,'ffmpeg':subprocess.check_output([shutil.which('ffmpeg'),'-version']).decode('utf-8').splitlines()[0]},indent=2)+'\n').encode())
print(json.dumps({'videos':len(manifest),'frames':160,'status':'PREPARED'}))
