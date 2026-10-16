"""绘制兰州新前沿诊断图和真实百度底图回放；不查询业务API。"""
from pathlib import Path
import json
import math

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'output/benchmarks/lanzhou-disk-frontier-20261016'


def main():
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    from tools.demo.compare_outside_in_grid import legacy_geometry
    report=json.loads((OUT/'report.json').read_text())
    source=json.loads((ROOT/'experiments/results/e10_boundary/e10x_lanzhou.json').read_text())
    summary=report['summary'];geo=report['geometryLocalMeters']
    font_manager.fontManager.addfont('/System/Library/Fonts/Hiragino Sans GB.ttc')
    plt.rcParams.update({'font.family':'Hiragino Sans GB','axes.unicode_minus':False})
    fig,axes=plt.subplots(1,3,figsize=(17,6))
    for ax in axes:
        ax.add_patch(plt.Circle((0,0),1000,fill=False,color='#a4afbf',lw=1))
        ax.set(xlim=(-1050,1050),ylim=(-1050,1050),aspect='equal',xlabel='东西偏移 / 米',ylabel='南北偏移 / 米')
        ax.grid(alpha=.12)
        for p in report['heldOut']:
            ax.scatter(p['x'],p['y'],s=5,c='#159d72' if p['seconds']<=900 else '#93a0b4',alpha=.4)
        ax.scatter(0,0,marker='*',s=80,c='#172a45',zorder=8)
    old=legacy_geometry(source,half=1000)
    for polygon in ([old] if old.geom_type=='Polygon' else old.geoms):
        x,y=polygon.exterior.xy;axes[0].plot(x,y,color='#df8d2c',lw=2)
    axes[0].set_title('旧射线轮廓 · 历史结果')
    baseline_path=OUT/'report-before-barrier.json'
    if baseline_path.exists():
        # 清除原射线对照，改为同一个网格算法修复前的边界。
        for artist in list(axes[0].lines):artist.remove()
        baseline=json.loads(baseline_path.read_text())
        for poly in baseline['geometryLocalMeters']['polygons']:
            for line in [poly['outer'],*poly['holes']]:axes[0].plot(*zip(*line),color='#df8d2c',lw=2)
        axes[0].set_title('修复前 · 网格前沿分析边界')
    for poly in geo['polygons']:
        for line in [poly['outer'],*poly['holes']]:
            axes[1].plot(*zip(*line),color='#159d72',lw=2)
    for p in report['mistakes']:
        axes[1].scatter(p['x'],p['y'],marker='x',s=25,c='#d63449' if p['type']=='false-reachable' else '#de941e',lw=1)
    axes[1].set_title(f"新圆盘前沿 · 分析边界\n{summary['diskMeasured']}位置 / {summary['diskBatches']}批，红×误可达 / 橙×漏可达")
    for line in report['frames'][-1]['previewContours']:
        axes[2].plot(*zip(*line),color='#2462f2',lw=2)
    axes[2].set_title('最终三角网拟合 · 仅展示\n不作为覆盖和评分边界')
    score=summary['heldOutChecks']
    fig.suptitle('兰州·中山桥｜黄河与桥梁绕行检查',fontsize=18,fontweight='bold')
    fig.text(.5,.025,f"未参与本次前沿的历史检查点 {score['points']} 个：误可达 {score['fp']}，漏可达 {score['fn']}。历史/当日测值混合，不是同时全量参考；内部仍是有限抽检。",ha='center',fontsize=10,color='#65758b')
    fig.tight_layout(rect=(0,.06,1,.93));fig.savefig(OUT/'comparison.png',dpi=160);plt.close(fig)
    payload={'center':report['centerBD09'],'summary':summary,'frames':report['frames']}
    template=(ROOT/'tools/demo/templates/disk-frontier.html').read_text().replace('王府井','兰州·中山桥')
    template=template.replace('从圆周向内寻找边界','黄河与桥梁绕行检查')
    template=template.replace('历史实测逐批回放，播放速度不代表真实耗时。',
        f"历史数据与本次补测混合回放。历史检查点{score['points']}个：误可达{score['fp']}，漏可达{score['fn']}。")
    # 将正式分析边界和误判点单独显示，不能只凭平滑蓝线宣称河流处理成功。
    diagnostics='''
  if(frame.done){
    for(const polygon of data.analysisPolygons)for(const coords of [polygon.outer,...polygon.holes]){
      const line=new B.Polyline(coords.map(point),{strokeColor:'#159d72',strokeWeight:4,strokeOpacity:.85});map.addOverlay(line);overlays.push(line);
    }
    for(const p of data.mistakes){
      const label=new B.Label('×',{position:point([p.x,p.y])});label.setStyle({color:p.type==='false-reachable'?'#d63449':'#de941e',fontSize:'16px',lineHeight:'16px',width:'16px',height:'16px',fontWeight:'bold',background:'transparent',textShadow:'0 0 2px white',border:'0',transform:'translate(-50%,-50%)',pointerEvents:'none'});map.addOverlay(label);overlays.push(label);
    }
  }
'''
    template=template.replace('  if(!frame)return;','  if(!frame)return;'+diagnostics)
    template=template.replace('灰线是初始测量圆。','灰线为原圆，完成后绿线为分析边界；红×误可达，橙×漏可达。')
    payload.update(analysisPolygons=geo['polygons'],mistakes=report['mistakes'])
    page=template.replace('__FRONTIER_DATA__',json.dumps(payload,ensure_ascii=False)).replace("location.replace('http://127.0.0.1:5173/frontier-demo.html')","location.replace('http://127.0.0.1:5173/frontier-lanzhou.html')")
    (OUT/'index.html').write_text(page)
    (ROOT/'web/public/frontier-lanzhou.html').write_text(page)
    print('Lanzhou diagnostic map and comparison ready.')


if __name__=='__main__':main()
