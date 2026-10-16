"""王府井2km/100m历史数据验证和逐批拟合展示；无网络、无真实计时宣传。"""
from pathlib import Path
import json
import math

from core.grid_frontier import grid_frontier, frontier_geometry, fit_preview
from tools.demo import compare_outside_in_grid as charts


def main():
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    from shapely.geometry import Polygon,Point
    from shapely.ops import unary_union
    root=Path(__file__).resolve().parents[2]
    out=root/'output/benchmarks/grid-frontier-progress-20261016'
    out.mkdir(parents=True,exist_ok=True)
    source=json.loads((root/'output/benchmarks/outside-in-2km-grid100-20261016/e4.json').read_text())
    truth={(p['eastM'],p['northM']):p['durationSeconds'] for p in source['truthGrid']}
    frames=[]
    state=grid_frontier(lambda ps:[truth[p] for p in ps],half_m=1000,on_progress=frames.append,domain_shape='square',max_pairs=440)
    geo=frontier_geometry(state)
    shape=unary_union([Polygon(p['outer'],p['holes']) for p in geo['polygons']])
    charts.AXIS=list(range(-1000,1001,100))
    reference=charts.geometry(truth)
    previous=source['runs']['main15']
    summary={'source':'historical BD09 Wangfujing 2km square, 100m grid',
        'liveApiCalls':0,'uniqueQueries':state['pairsUsed'],'serialBatches':len(state['batches']),
        'previousAmrQueries':previous['summary']['uniqueQueries'],
        'previousAmrBatches':sum(p['newQueries']>0 for p in previous['phases']),
        'previousAmrStatus':'budget limited','status':state['status'],
        'areaIoU':round(shape.intersection(reference).area/shape.union(reference).area,6),
        'gridMistakes':sum(shape.covers(Point(*p))!=(v<=900) for p,v in truth.items() if p!=(0,0)),
        'firstPublishAfterMeasuredPoints':frames[0]['pairsUsed'],
        'boundaryShells':[b['shellM'] for b in state['batches'] if b['phase']=='boundary'],
        'previewUsedForAnalysis':False,'realApiDurationMeasured':False,'interiorEstimated':True,'clipped':state['clipped']}
    lat,lng=source['summary']['centerLatLngBD09']
    for f in frames:
        f['actualContours']=frontier_geometry(f)['contours']
        f['previewContours']=[[[round((p['lng']-lng)*111320*math.cos(math.radians(lat)),4),round((p['lat']-lat)*111320,4)] for p in line] for line in fit_preview(f,lng=lng,lat=lat)]
    report={'summary':summary,'result':state,'geometryLocalMeters':geo,'frames':frames}
    (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    font_manager.fontManager.addfont('/System/Library/Fonts/Hiragino Sans GB.ttc')
    plt.rcParams.update({'font.family':'Hiragino Sans GB','axes.unicode_minus':False})
    fig,axs=plt.subplots(1,3,figsize=(16,6))
    for ax in axs:
        ax.set(xlim=(-1050,1050),ylim=(-1050,1050),aspect='equal',xlabel='东西偏移 / 米',ylabel='南北偏移 / 米')
        ax.grid(alpha=.15)
        charts.plot_lines(ax,truth,'#26374c',1.3,style='--')
    charts.plot_lines(axs[0],truth,'#26374c',2)
    axs[0].set_title('完整100米网格参考 · 440个外部位置')
    old_pred={(p['eastM'],p['northM']):p['durationSeconds'] for p in previous['prediction']}
    charts.plot_lines(axs[1],old_pred,'#e67c24',2)
    for p in previous['samples']:axs[1].scatter(p['eastM'],p['northM'],s=5,c='#d18a46',alpha=.65)
    axs[1].set_title('上一版AMR · 300点 / 33批\n预算受限 · 格点误判9个')
    charts.plot_shape(axs[2],shape,'#2462f2',2,half=1000)
    for p in state['samples']:axs[2].scatter(p['x'],p['y'],s=6,c='#159d72' if p['state']=='reachable' else '#8092af',alpha=.75)
    axs[2].set_title(f'外向内前沿 · {state["pairsUsed"]}点 / {len(state["batches"])}批\n有限内部检查后完成 · 格点误判{summary["gridMistakes"]}个')
    fig.suptitle('王府井｜严格外向内前沿与旧AMR对照',fontweight='bold',fontsize=17)
    fig.text(.5,.025,'历史实测离线回算，非真实API耗时；黑虚线为完整网格参考。未测内部为有限检查下的近似区域，窗口触边仍保留。',ha='center',fontsize=9,color='#596579')
    fig.tight_layout(rect=(0,.06,1,.92))
    fig.savefig(out/'comparison.png',dpi=180);plt.close(fig)
    data=json.dumps(frames,ensure_ascii=False)
    page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>外向内逐批展示</title><style>body{max-width:900px;margin:24px auto;padding:16px;font:16px/1.6 system-ui;color:#26344a;background:#f6f8fc}svg{width:100%;background:white;border:1px solid #dbe2ed;border-radius:18px}button{padding:8px 18px;border:1px solid #ccd6e5;background:white;border-radius:10px;margin-right:12px}input{width:60%}small{color:#65758b}img{width:100%}</style><h1>外向内前沿 · 逐批测点与拟合线</h1><p>历史数据离线过程展示。播放速度为演示设置，不代表真实API耗时。</p><button id="play">播放</button><input id="step" type="range" min="0"><p id="status"></p><svg id="map" viewBox="-1100 -1100 2200 2200"></svg><p><span style="color:#159d72">● 实测可达</span>　<span style="color:#8092af">● 实测超时</span>　<span style="color:#7c8db5">虚线：当前测点拟合，仅供动态展示</span></p><small>实线只使用局部实测边界证据；拟合线不参与覆盖、评分或最终边界。未测内部仍是有限抽检下的近似。</small><h2>与上一版比较</h2><img src="comparison.png"><p><a href="report.json">完整逐批记录</a></p><script>const frames=DATA;const svg=document.querySelector('#map'),step=document.querySelector('#step');step.max=frames.length-1;step.value=0;const path=(l)=>l.map((p,i)=>(i?'L':'M')+p[0]+','+(-p[1])).join(' ');function draw(){const f=frames[+step.value];svg.innerHTML='<rect x="-1000" y="-1000" width="2000" height="2000" fill="none" stroke="#dbe2ed"/>'+f.previewContours.map(l=>'<path d="'+path(l)+'" fill="none" stroke="#7c8db5" stroke-width="7" stroke-dasharray="20 15"/>').join('')+f.actualContours.map(l=>'<path d="'+path(l)+'" fill="none" stroke="#2462f2" stroke-width="8"/>').join('')+f.samples.map(p=>'<circle cx="'+p.x+'" cy="'+(-p.y)+'" r="9" fill="'+(p.state==='reachable'?'#159d72':p.state==='unknown'?'#e49932':'#8092af')+'"/>').join('');document.querySelector('#status').textContent=(f.phase==='boundary'?'由外向内测量':f.phase==='interior-check'?'有限内部检查':'本轮完成')+' · 已测 '+f.pairsUsed+' 个位置 · 第 '+f.batches.length+' 批';}step.oninput=draw;let timer;document.querySelector('#play').onclick=()=>{if(timer){clearInterval(timer);timer=null;return}if(+step.value===frames.length-1)step.value=0;timer=setInterval(()=>{step.value=Math.min(frames.length-1,+step.value+1);draw();if(+step.value===frames.length-1){clearInterval(timer);timer=null}},900)};draw();</script></html>'''
    (out/'index.html').write_text(page.replace('DATA',data))
    print(json.dumps(summary,ensure_ascii=False))


if __name__=='__main__':main()
