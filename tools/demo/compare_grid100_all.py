"""2×2km、100m历史完整网格全量盘点与外向内实验；只读、零网络。"""
from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path
import sqlite3

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.lines import Line2D
import numpy as np
from shapely.geometry import Point

from experiments.e4_sampling.outside_in_grid import outside_in
from tools.demo import compare_outside_in_grid as charts

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT/'output/benchmarks/outside-in-2km-grid100-20261016'
AXIS = list(range(-1000,1001,100))


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    charts.AXIS = AXIS
    font_manager.fontManager.addfont('/System/Library/Fonts/Hiragino Sans GB.ttc')
    plt.rcParams.update({'font.family':'Hiragino Sans GB','axes.unicode_minus':False,'font.size':10})
    db = ROOT/'experiments/logs/cache.db'
    digest = hashlib.sha256(db.read_bytes()).hexdigest()
    conn = sqlite3.connect(f'file:{db}?mode=ro',uri=True)
    sources = list((ROOT/'experiments/results/e10_boundary').glob('e10x_*.json'))
    sources += [ROOT/'experiments/results/e4_sampling/e4.json',ROOT/'experiments/results/e4_sampling/e4b.json']
    known = {}
    for p in sources:
        d=json.loads(p.read_text())
        slug=p.stem.removeprefix('e10x_')
        name=d.get('city') or {'e4':'北京·王府井','e4b':'北京·东花市'}[slug]
        known[tuple(round(v,6) for v in d['center'])]=(slug,name,d,p)
    origins=list(conn.execute('SELECT o_lat,o_lng,COUNT(*) FROM walk_times GROUP BY o_lat,o_lng'))
    inventory=[]
    eligible=[]
    for lat,lng,total in origins:
        rows=list(conn.execute("SELECT d_lat,d_lng,duration_s FROM walk_times WHERE o_lat=? AND o_lng=? AND mode='walking'",(lat,lng)))
        raw={(a,b):v for a,b,v in rows}
        entry=known.get((lat,lng))
        if entry:
            slug,name,data,path=entry
            truth={(x,y):raw.get(charts.coordinate(data['center'],x,y)) for x in AXIS for y in AXIS}
            valid=sum(v is not None and math.isfinite(v) and v>=0 for v in truth.values())
            matched=sum(charts.coordinate(data['center'],x,y) in raw for x in AXIS for y in AXIS)
        else:
            # 仅盘点未知中心接近100m格点的现有数量，不拿近邻替代实际查询坐标。
            matched_keys=set();valid_keys=set()
            for a,b,v in rows:
                x=(b-lng)*111320*math.cos(math.radians(a));y=(a-lat)*111320
                i,j=round(x/100),round(y/100)
                if abs(x-i*100)<.2 and abs(y-j*100)<.2 and abs(i)<=10 and abs(j)<=10:
                    matched_keys.add((i,j))
                    if v is not None and math.isfinite(v) and v>=0:valid_keys.add((i,j))
            slug=f'unknown-{lat}-{lng}';name=f'未归档中心 {lat},{lng}'
            matched,valid=len(matched_keys),len(valid_keys)
        record={'slug':slug,'name':name,'originRoundedLatLngBD09':[lat,lng],
                'storedODRows':total,'matched100mGridPositions':matched,'valid100mGridPositions':valid,
                'requiredGridPositions':441,'missingOrInvalid':441-valid,
                'historicalReferenceSpacingM':(data.get('metrics',{}).get('truth_spacing') or (100 if slug=='e4' else 150 if slug=='e4b' else None)) if entry else None,
                'eligible':bool(entry and valid==441),'sourceFile':str(path.relative_to(ROOT)) if entry else None}
        inventory.append(record)
        if record['eligible']:eligible.append((record,data,raw,truth))
    (OUT/'inventory.json').write_text(json.dumps(inventory,ensure_ascii=False,indent=2))
    with (OUT/'inventory.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=['name','historicalReferenceSpacingM','matched100mGridPositions','valid100mGridPositions','requiredGridPositions','missingOrInvalid','eligible'])
        writer.writeheader();writer.writerows({k:r[k] for k in writer.fieldnames} for r in inventory)
    summaries=[]
    for item,data,raw,truth in eligible:
        runs={}
        for label,thresholds in [('main15',(900,)),('layers',(900,600,300))]:
            runs[label]=outside_in(lambda x,y:truth.get((x,y)),half=1000,spacing=100,budget=300,thresholds=thresholds)
        old=charts.legacy_geometry(data,half=1000)
        reference=charts.geometry(truth)
        reference_keys={charts.coordinate(data['center'],x,y) for x,y in truth}
        offgrid={}
        for (lat,lng),v in raw.items():
            if (lat,lng) in reference_keys or v is None or not math.isfinite(v) or v<=0:continue
            x=(lng-data['center'][1])*111320*math.cos(math.radians(lat));y=(lat-data['center'][0])*111320
            if -1000<x<1000 and -1000<y<1000:offgrid[x,y]=v
        fig,axs=plt.subplots(2,2,figsize=(12,12))
        for ax in axs.flat:
            ax.set(xlim=(-1050,1050),ylim=(-1050,1050),aspect='equal',xlabel='东西偏移 / 米',ylabel='南北偏移 / 米')
            ax.set_xticks([-1000,-500,0,500,1000]);ax.set_yticks([-1000,-500,0,500,1000])
            ax.grid(alpha=.16);ax.scatter([0],[0],marker='*',s=70,c='#182337',zorder=9)
            ax.spines[['top','right']].set_visible(False)
        def background(ax,field):
            ax.contourf(AXIS,AXIS,charts.array(field),levels=[-.01,300,600,900,100000],colors=['#b7e6cb','#b4e3e8','#d1dffc','#f4f5f8'])
        background(axs[0,0],truth)
        charts.plot_lines(axs[0,0],truth,'#26374c',2)
        axs[0,0].scatter(*np.array(list(truth)).T,s=6,c='#687b91',alpha=.5)
        axs[0,0].set_title('完整100米网格参考 · 441位置\n5分钟绿 / 10分钟青 / 15分钟蓝',fontweight='bold')
        background(axs[0,1],truth)
        charts.plot_lines(axs[0,1],truth,'#26374c',1.2,style='--')
        charts.plot_shape(axs[0,1],old,'#e67c24',2,half=1000)
        axs[0,1].set_title('原射线主边界＋记录的复通/间隔带\n不含R2场融合',fontweight='bold')
        old_class=lambda p:old.covers(Point(*p))
        old_summary={'areaIoU':round(old.intersection(reference).area/max(1,old.union(reference).area),6),
                     'gridScore':charts.score(old_class,truth,[p for p in truth if p!=(0,0)]),
                     'offGridChecks':charts.score(old_class,offgrid,list(offgrid))}
        details={}
        for label,ax in [('main15',axs[1,0]),('layers',axs[1,1])]:
            run=runs[label];pred=run['prediction'];shape=charts.geometry(pred)
            background(ax,pred)
            levels=(900,) if label=='main15' else (300,600,900)
            for t in levels:charts.plot_lines(ax,pred,{300:'#19995c',600:'#1599a4',900:'#2462f2'}[t],2 if t==900 else 1.2,t)
            charts.plot_lines(ax,truth,'#26374c',1.2,style='--')
            smp=np.array(list(run['observed']));ax.scatter(smp[:,0],smp[:,1],s=7,c='#245ad1',alpha=.5)
            def classify(p):
                x,y=p;x0,y0=math.floor(x/100)*100,math.floor(y/100)*100
                s,t=(x-x0)/100,(y-y0)/100
                keys=[(x0,y0),(x0+100,y0),(x0+100,y0+100),(x0,y0+100)]
                if any(k not in pred for k in keys):return None
                a,b,c,d=(pred[k] for k in keys)
                return a*(1-s)*(1-t)+b*s*(1-t)+c*s*t+d*(1-s)*t<=900
            mistakes=np.array([p for p,t in offgrid.items() if classify(p)!=(t<=900)])
            if len(mistakes):ax.scatter(mistakes[:,0],mistakes[:,1],marker='x',s=14,c='#d63642',lw=.8,zorder=8)
            checks=charts.score(classify,offgrid,list(offgrid))
            held=[p for p in truth if p not in run['observed'] and p!=(0,0)]
            gridclass=lambda p:pred[p]<=900 if p in pred else None
            summary={'uniqueQueries':run['queryCount'],'querySavingVsFull440':round(1-run['queryCount']/440,4),
                'budgetLimited':run['budgetExhausted'],'unresolvedPositions':len(run['unresolved']),
                'gridScore':charts.score(gridclass,truth,[p for p in truth if p!=(0,0)]),
                'unqueriedGridScore':charts.score(gridclass,truth,held),
                'offGridChecks':checks,'areaIoU':round(shape.intersection(reference).area/max(1,shape.union(reference).area),6),
                'clipped15min':any(v<=900 for (x,y),v in pred.items() if abs(x)==1000 or abs(y)==1000),
                'thresholdGridMistakes':{str(t):sum((v<=t)!=(pred[p]<=t) for p,v in truth.items() if p!=(0,0)) for t in (300,600,900)}}
            details[label]={'summary':summary,'phases':run['phases'],'leaves':run['leaves'],
                'samples':[{'eastM':x,'northM':y,'durationSeconds':v} for (x,y),v in sorted(run['observed'].items())],
                'prediction':[{'eastM':x,'northM':y,'durationSeconds':v} for (x,y),v in sorted(pred.items())],
                'unresolvedPositions':sorted(run['unresolved']),
                'contoursLocalMeters':{str(t):[line.tolist() for line in charts.contours(pred,t)] for t in levels}}
            ax.set_title(f'{"15分钟主圈" if label=="main15" else "5/10/15分钟三层"} · {run["queryCount"]}个查询位置\n非格点F1 {checks["f1"]:.3f} · {"预算受限" if run["budgetExhausted"] else "无剩余已发现风险单元"}',fontweight='bold')
        summary={'slug':item['slug'],'name':item['name'],'centerLatLngBD09':data['center'],
                 'main15':details['main15']['summary'],'layers':details['layers']['summary'],'oldRay':old_summary}
        summaries.append(summary)
        fig.suptitle(f'{item["name"]}｜2×2公里 · 100米网格对照',fontsize=19,fontweight='bold',y=.99)
        fig.legend(handles=[Line2D([0],[0],color='#26374c',ls='--',label='完整网格15分钟参考'),Line2D([0],[0],color='#e67c24',label='原射线'),Line2D([0],[0],color='#2462f2',label='新网格'),Line2D([0],[0],color='#d63642',marker='x',ls='',label='未参与新采样的历史错点')],loc='lower center',bbox_to_anchor=(.5,.042),ncol=4)
        fig.text(.5,.016,'历史实测离线重跑，零新增API；非格点含50米内部测点及旧射线探针，并非对原算法独立留出集。',ha='center',fontsize=9,color='#58677c')
        fig.tight_layout(rect=(0,.08,1,.96),h_pad=2)
        fig.savefig(OUT/f'{item["slug"]}.png',dpi=180);fig.savefig(OUT/f'{item["slug"]}.svg');plt.close(fig)
        (OUT/f'{item["slug"]}.json').write_text(json.dumps({'summary':summary,'runs':details,
            'truthGrid':[{'eastM':x,'northM':y,'durationSeconds':v} for (x,y),v in sorted(truth.items())],
            'offGridHistoricalChecks':[{'eastM':x,'northM':y,'durationSeconds':v} for (x,y),v in sorted(offgrid.items())]},ensure_ascii=False,indent=2))
    conn.close()
    assert hashlib.sha256(db.read_bytes()).hexdigest()==digest
    report={'experiment':'outside-in-2km-grid100-v1','liveApiCalls':0,'halfM':1000,'spacingM':100,
            'budget':300,'sourceDbSha256':digest,'historicalOriginsAudited':len(origins),
            'eligibleCount':len(eligible),'inventory':inventory,'results':summaries,
            'caution':'complete existing 100m grids only; no interpolation used as oracle; original comparison excludes R2; off-grid checks may train old rays'}
    (OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    images=''.join(f'<h2>{c["name"]}</h2><a href="{c["slug"]}.png"><img src="{c["slug"]}.png" alt="2公里100米网格对照"></a><p><a href="{c["slug"]}.svg">矢量图</a> · <a href="{c["slug"]}.json">逐点记录</a></p>' for c in summaries)
    table=''.join(f'<tr><td>{r["name"]}</td><td>{r["historicalReferenceSpacingM"] or "未记录"}</td><td>{r["valid100mGridPositions"]}/441</td><td>{"已重跑" if r["eligible"] else "缺测，未补测"}</td></tr>' for r in inventory)
    (OUT/'index.html').write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>2公里100米网格实验</title><style>body{font:16px/1.7 system-ui;max-width:1200px;margin:30px auto;padding:16px;color:#26344a}img{width:100%}td,th{padding:8px;border-bottom:1px solid #ddd;text-align:left}table{border-collapse:collapse;width:100%}a{color:#245ad1}</style><h1>2×2公里 · 100米网格重算</h1><p>盘点34个历史测量中心，仅完整100米网格进入重算。零新增API。其他城市缺测不伪造、不自动追加查询。</p>'+images+'<h2>全部中心覆盖盘点</h2><p><a href="inventory.csv">CSV</a> · <a href="report.json">汇总JSON</a></p><table><tr><th>地点</th><th>历史大范围网格间距/米</th><th>有效100米格点</th><th>处理</th></tr>'+table+'</table></html>')
    print(json.dumps({'auditedOrigins':len(origins),'eligibleCount':len(eligible),'results':summaries},ensure_ascii=False))


if __name__=='__main__':main()
