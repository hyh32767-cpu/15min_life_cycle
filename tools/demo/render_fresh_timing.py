"""新点冷启动计时报告与图，无网络请求。"""
from pathlib import Path
import argparse
import json
import math


def main():
    parser=argparse.ArgumentParser();parser.add_argument('directory',type=Path);args=parser.parse_args()
    out=args.directory;report=json.loads((out/'report.json').read_text())
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    font_manager.fontManager.addfont('/System/Library/Fonts/Hiragino Sans GB.ttc')
    plt.rcParams.update({'font.family':'Hiragino Sans GB','axes.unicode_minus':False})
    fig,axes=plt.subplots(1,3,figsize=(17,6))
    palette={'fan':'#df8d2c','grid':'#2462f2'};names={'fan':'原16向自适应扇形','grid':'新圆盘前沿＋屏障检查'}
    for i,run in enumerate(report['runs']):
        kind=run['kind'];data=json.loads((out/f'{kind}.json').read_text());ax=axes[i]
        if kind=='fan':
            radii=sorted((float(b),r) for b,r in data['result'].get('radiiM',{}).items())
            points=[(r*math.sin(math.radians(b)),r*math.cos(math.radians(b))) for b,r in radii]
            if points:ax.plot(*zip(*(points+[points[0]])),color=palette[kind],lw=2)
        else:
            for polygon in (data.get('geometryLocalMeters') or {}).get('polygons',[]):
                for line in [polygon['outer'],*polygon['holes']]:ax.plot(*zip(*line),color=palette[kind],lw=2)
        center=report['centerBD09']
        for sample in data['samples']:
            coord=sample['coord'];x=(coord['lng']-center['lng'])*111320*math.cos(math.radians(center['lat']));y=(coord['lat']-center['lat'])*111320
            ax.scatter(x,y,c=palette[kind],s=5,alpha=.5)
        ax.add_patch(plt.Circle((0,0),report.get('gridRadiusM',1000),fill=False,color='#a4afbf',lw=1,ls='--'))
        ax.scatter(0,0,c='#182a43',marker='*',s=80)
        ax.set(xlim=(-1900,1900),ylim=(-1900,1900),aspect='equal',xlabel='东西偏移 / 米',ylabel='南北偏移 / 米')
        ax.grid(alpha=.13)
        ax.set_title(f"{names[kind]}\n{run['elapsedSeconds']:.2f}秒 · {run['pairs']}对 · {run['accounting']['liveRequests']}次HTTP")
        count=0;xs=[0];ys=[0]
        for batch in data['batches']:
            count+=batch['pairs'];xs.append(batch['elapsedSeconds']);ys.append(count)
        axes[2].step(xs,ys,where='post',color=palette[kind],label=names[kind],lw=2)
    axes[2].set(xlabel='累计用时 / 秒',ylabel='已查OD对数',title='真实时间线（包含发送等待）');axes[2].grid(alpha=.15);axes[2].legend(fontsize=9)
    fig.suptitle(report['name']+'｜单次冷启动对照',fontsize=18,fontweight='bold')
    fig.text(.5,.02,f"两套空缓存、同一发送节奏、15分钟阈值、各{report['maxPairsEach']}对上限。新网格半径{report['gridRadiusM']/1000:g}公里，旧扇形原括界1.8公里；无完整真值，不比较精度。",ha='center',fontsize=9,color='#65758b')
    fig.tight_layout(rect=(0,.06,1,.93));fig.savefig(out/'comparison.png',dpi=160);plt.close(fig)
    lines=['# '+report['name']+'：新算法与原扇形冷启动计时','',
           '| 算法 | 总用时 | 首次实测更新 | OD对数 | HTTP请求 | 缓存命中 | 状态 |',
           '| --- | ---: | ---: | ---: | ---: | ---: | --- |']
    for run in report['runs']:
        lines.append(f"| {names[run['kind']]} | {run['elapsedSeconds']:.3f}秒 | {run['firstMeasuredUpdateSeconds']}秒 | {run['pairs']} | {run['accounting']['liveRequests']} | {run['accounting']['cacheHits']} | {run['status']} |")
    order='→10秒间隔→'.join(names[run['kind']] for run in report['runs'])
    order=report.get('orderNote',order)
    lines+=['',report['scopeNote'],'',f'单点单轮测试，顺序为{order}；间隔不计入任何一项。没有重复压测，没有完整参考网格，不声称精度或普遍性能排名。']
    slow=[]
    for run in report['runs']:
        data=json.loads((out/f"{run['kind']}.json").read_text())
        count=sum(b['apiSeconds']>=9 for b in data['batches'])
        slow.append(f"{names[run['kind']]}：服务调用≥9秒的批次{count}个，上游累计{run.get('upstreamSeconds',run['accounting']['latencyMs']/1000):.3f}秒")
    lines+=['','；'.join(slow)+'。真实总时间差包含接口响应和发送等待，不能全部归因于算法。首次实测更新是算法可发布快照的时间，不包括地点搜索、底图加载与前端轮询。',
            '是否加密受限、是否触及测量窗口，以各轮原始结果的warnings/clipped为准。未用完整参考网格比较精度。']
    (out/'README.md').write_text('\n'.join(lines)+'\n')
    print('\n'.join(lines))


if __name__=='__main__':main()
