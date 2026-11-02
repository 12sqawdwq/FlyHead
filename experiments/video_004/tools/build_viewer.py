"""Viewer derived from locked genuine-video outputs, no inference or score changes."""
from pathlib import Path
import base64,csv,hashlib,json
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
r=json.loads((ROOT/'run_001/RESULTS.json').read_text());v=json.loads((ROOT/'evidence/VALIDATION.json').read_text());reg=json.loads((ROOT/'config/readout_registry.json').read_text());videos=json.loads((ROOT/'config/videos.json').read_text())
lock=json.loads((ROOT/'RESULT_LOCK.json').read_text())
for x in lock['files']:assert hashlib.sha256((ROOT/x['path']).read_bytes()).hexdigest()==x['sha256']
episodes=[json.loads((ROOT/'run_001'/(x['episode_id']+'.json')).read_text()) for x in r['episodes']]
media={x['name']:{'mp4':base64.b64encode((ROOT/x['preview_file']).read_bytes()).decode(),'poster':base64.b64encode((ROOT/'inputs'/(x['name']+'_frame0.png')).read_bytes()).decode()} for x in videos}
# A common y-scale across all episode plots, not per-condition autoscaling.
ymax=max(200,int(np.ceil(max(max(row['readout_counts'].values())*10 for e in episodes for row in e['frames'])/50)*50))
data=json.dumps({'episodes':episodes,'summary':v['summary'],'media':media,'readouts':reg['readout_keys'],'cells':reg['cells'],'ymax':ymax},ensure_ascii=False).replace('<','\\u003c')
with (ROOT/'FRAME_RESPONSES.csv').open('w',encoding='utf-8-sig',newline='') as f:
 keys=['episode','video','arm','seed','frame','replay_seconds','frame_present','hs_valid','all_spikes','active_neurons','model_ms','processing_ms','compute_budget_ok']+reg['readout_keys']+['shadow_v','shadow_yaw','state']
 w=csv.DictWriter(f,fieldnames=keys);w.writeheader()
 for e in episodes:
  for row in e['frames']:
   w.writerow(dict(episode=e['episode_id'],video=e['video'],arm=e['arm'],seed=e['seed'],frame=row['frame'],replay_seconds=row['replay_seconds'],frame_present=row['stimulus']['frame_present'],hs_valid=row['stimulus']['hs_valid'],all_spikes=row['all_spikes'],active_neurons=row['active_neurons'],model_ms=row['model_and_health_ms'],processing_ms=row['processing_ms'],compute_budget_ok=row['within_100ms_compute_budget'],**row['readout_counts'],shadow_v=row['intent']['shadow_forward_m_s'],shadow_yaw=row['intent']['shadow_yaw_rad_s'],state=row['intent']['state']))
html=r'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>连续视频与果蝇脑响应</title>
<style>body{max-width:1240px;margin:26px auto;padding:0 24px;background:#f3f6fa;color:#182d48;font:16px system-ui}h1{font-size:29px}h2{font-size:20px}section{background:#fff;border:1px solid #d9e3ed;border-radius:9px;margin:16px 0;padding:20px}.grid{display:grid;grid-template-columns:420px 1fr;gap:24px}.stage{position:relative;width:400px;height:300px;background:#172635}video,.overlay{position:absolute;width:100%;height:100%;object-fit:contain}.overlay{pointer-events:none}.tail{display:none;position:absolute;inset:0;background:#172635;color:white;text-align:center;padding-top:125px;box-sizing:border-box}select,button{font:16px system-ui;padding:8px;margin:5px}input{width:95%}table{border-collapse:collapse;width:100%;font-size:14px}td,th{padding:7px;text-align:left;border-bottom:1px solid #e5ebf1}small{color:#566a80}.good{color:#167247}.bad{color:#a93a27}svg{width:100%;height:auto}.scroll{overflow:auto}code{font-size:12px}</style>
<h1>真实视频 → 持续脑状态 → 逐帧神经响应</h1>
<p>TUM 室内相机视频 · 2视频 × 4条件 × 2种子 · 8秒视频＋1秒停止刺激 · 10Hz输入</p>
<p>完整138639神经元 / 15091983连接。这里只播放已冻结的离线结果，不控制机器人。</p>
<section><select id="episode"></select><div class="grid"><div><div class="stage"><video id="video" muted playsinline preload="auto"></video><img id="frozen" class="overlay"><div id="tail" class="tail">无视频帧 · 零刺激观察尾段</div></div><p><button id="play">播放</button><button id="pause">暂停</button><span id="time"></span></p><input id="frame" type="range" min="0" max="89" value="0"><p id="source"></p><p id="quality"></p><p id="rates"></p></div><div><h2>本帧刺激100ms后的读出</h2><div id="readouts"></div><p id="intent"></p><p id="timing"></p><small>显示Hz为100ms窗口尖峰数×10。回放时间不等于Kinect采集时戳或计算完成时刻。</small></div></div></section>
<section><h2>前进与转向读出的连续时间曲线</h2><p>实线为神经发放率，不是实机速度。灰色区域8–9秒为停止感觉刺激，虚线标记当前响应窗口末端。</p><div id="plots"></div></section>
<section><h2>对照结果（逐回合，不把帧当独立试验）</h2><div id="summary" class="scroll"></div></section>
<section><h2>本轮观察</h2><p>两段真实视频的HS有效帧约79%和65%，大量位移落到±4像素搜索边界。LC9对比度输入在97.5%–100%的半图采样中饱和，P9前进读出因此对两场景变化不敏感。</p><p>逐帧重置状态改变了DNa02响应，不能替代持续脑状态。停止刺激后还有短暂全脑残留，但尾段影子输出始终HOLD；这不是实机停车测试。</p><p>共享GPU负载下，完整诊断记录流程多数超过100ms，未通过实时控制准入。没有扩大源龄门。</p><p>数据：<a href="FRAME_RESPONSES.csv">逐帧CSV</a> · <a href="RESULTS.md">结果与边界</a>。出处：<a href="https://cvg.cit.tum.de/data/datasets/rgbd-dataset/download">TUM RGB-D Benchmark 官方RGB预览视频</a>，只用RGB，未读取深度或轨迹。</p></section>
<script>const D=__DATA__;
const $=x=>document.getElementById(x);const E=s=>String(s??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');
const table=(h,rows)=>'<table><tr>'+h.map(x=>'<th>'+E(x)+'</th>').join('')+'</tr>'+rows.map(r=>'<tr>'+r.map(x=>'<td>'+E(x)+'</td>').join('')+'</tr>').join('')+'</table>';
let current=D.episodes[0],playing=false,timer=null;
function stop(){playing=false;$('video').pause();if(timer){clearInterval(timer);timer=null}}
D.episodes.forEach((x,i)=>{let o=document.createElement('option');o.value=i;o.textContent=x.episode_id;$('episode').appendChild(o)});
function charts(k){const groups=[['DNp09_left','DNp09_right'],['DNa02_left','DNa02_right']];let svg='<svg viewBox="0 0 1160 440">';groups.forEach((g,j)=>{let y0=30+j*215,h=150,x0=58,w=1040;svg+='<rect x="'+(x0+w*8/9)+'" y="'+y0+'" width="'+w/9+'" height="'+h+'" fill="#edf0f5"/>';[0,100,200].filter(z=>z<=D.ymax).forEach(val=>{let y=y0+h-val/D.ymax*h;svg+='<line x1="'+x0+'" x2="'+(x0+w)+'" y1="'+y+'" y2="'+y+'" stroke="#e4eaf1"/><text x="3" y="'+(y+5)+'" font-size="13">'+val+' Hz</text>'});g.forEach((key,c)=>{let points=current.frames.map((r,i)=>(x0+(i+1)/90*w)+','+(y0+h-r.readout_counts[key]*10/D.ymax*h)).join(' ');let color=c?'#cb6841':'#2375b9';svg+='<polyline points="'+points+'" fill="none" stroke="'+color+'" stroke-width="2"/><text x="'+(70+c*230)+'" y="'+(y0-10)+'" fill="'+color+'" font-size="16">'+key+'</text>'});let x=x0+(k+1)/90*w;svg+='<line x1="'+x+'" x2="'+x+'" y1="'+y0+'" y2="'+(y0+h)+'" stroke="#283c56" stroke-dasharray="5 4"/>';[0,2,4,6,8,9].forEach(s=>svg+='<text x="'+(x0+s/9*w-5)+'" y="'+(y0+h+22)+'" font-size="14">'+s+'s</text>')});return svg+'</svg>'}
function show(k){k=Math.max(0,Math.min(89,k));$('frame').value=k;let r=current.frames[k];$('time').textContent=(k/10).toFixed(1)+' / 9.0s';$('frozen').style.display=current.arm==='FROZEN_FIRST'&&k<80?'block':'none';$('tail').style.display=k>=80?'block':'none';let s=r.original_video_source;$('source').textContent=s?'源视频帧 '+s.index+'，媒体PTS '+s.media_pts_seconds.toFixed(3)+'s'+(current.arm==='FROZEN_FIRST'?'（冻结首帧控制）':''):'没有新帧，神经状态继续推进';$('quality').innerHTML='HS质量：<b class="'+(r.stimulus.hs_valid?'good':'bad')+'">'+(r.stimulus.hs_valid?'可用':E(r.stimulus.reason))+'</b>；全脑 '+r.all_spikes+' 个尖峰 / '+r.active_neurons+' 个活动细胞';$('rates').textContent='LC9实际感觉输入：左 '+r.stimulus.lc9_rates_hz.left.toFixed(1)+' Hz，右 '+r.stimulus.lc9_rates_hz.right.toFixed(1)+' Hz';$('readouts').innerHTML=table(['神经元','root_id','计数','Hz'],D.readouts.map(key=>[key,D.cells[key].root_id,r.readout_counts[key],r.readout_counts[key]*10]));$('intent').textContent='视觉质量门后的影子意图：'+r.intent.state+'；v='+r.intent.shadow_forward_m_s.toFixed(3)+' m/s，ω='+r.intent.shadow_yaw_rad_s.toFixed(3)+' rad/s。未发布。';$('timing').innerHTML='模型与健康检查 '+r.model_and_health_ms.toFixed(1)+'ms；全部处理 <b class="'+(r.within_100ms_compute_budget?'good':'bad')+'">'+r.processing_ms.toFixed(1)+'ms / 100ms</b>。';$('plots').innerHTML=charts(k)}
function load(){stop();current=D.episodes[Number($('episode').value)];$('video').src='data:video/mp4;base64,'+D.media[current.video].mp4;$('video').poster='data:image/png;base64,'+D.media[current.video].poster;$('frozen').src=$('video').poster;$('video').load();show(0)}
$('episode').addEventListener('change',load);$('pause').onclick=stop;$('frame').oninput=()=>{stop();let k=Number($('frame').value);if(k<80)$('video').currentTime=k/10;show(k)};
$('play').onclick=()=>{stop();let k=Number($('frame').value);if(k>=80){k=0;show(0)}$('video').currentTime=k/10;playing=true;$('video').play().catch(()=>{playing=false})};
$('video').ontimeupdate=()=>{if(playing)show(Math.min(79,Math.floor($('video').currentTime*10)))};
$('video').onended=()=>{if(!playing)return;let k=80;show(k);timer=setInterval(()=>{k++;if(k>89){stop();return}show(k)},100)};
$('summary').innerHTML=table(['视频 / 条件 / 种子','P9左右 Hz','DNa02左右 Hz','HS有效','全处理P99 ms','100ms预算通过','尾段总尖峰'],D.summary.map(s=>[s.video+' / '+s.arm+' / '+s.seed,s.mean_readout_hz.DNp09_left.toFixed(1)+' / '+s.mean_readout_hz.DNp09_right.toFixed(1),s.mean_readout_hz.DNa02_left.toFixed(1)+' / '+s.mean_readout_hz.DNa02_right.toFixed(1),(s.hs_valid_fraction*100).toFixed(1)+'%',s.processing_p99_ms.toFixed(1),(s.compute_budget_pass_fraction*100).toFixed(1)+'%',s.tail_total_spikes]));
const initial=new URLSearchParams(location.hash.slice(1));if(initial.has('frame')){let k=Number(initial.get('frame'));if(Number.isFinite(k))$('video').addEventListener('loadedmetadata',()=>{k=Math.max(0,Math.min(89,Math.floor(k)));if(k<80)$('video').currentTime=k/10;show(k)},{once:true})}load();</script></html>'''
(ROOT/'VIDEO_RESPONSE.html').write_bytes(html.replace('__DATA__',data).encode())
# Additional descriptive diagnostics on the frozen arrays, never model tuning.
extra=[]
for e in episodes:
 if e['arm']!='CONTINUOUS':continue
 frames=e['frames'][:80]
 extra.append({'episode':e['episode_id'],'lc9_side_samples_at_200hz_fraction':float(np.mean([x['stimulus']['lc9_rates_hz'][side]>=199.999 for x in frames for side in ['left','right']])),
               'processing_median_ms':float(np.median([x['processing_ms'] for x in frames]))})
(ROOT/'evidence/DESCRIPTIVE_VIDEO_DIAGNOSTICS.json').write_bytes((json.dumps(extra,indent=2)+'\n').encode())
print('VIDEO_RESPONSE.html and FRAME_RESPONSES.csv generated')
