"""汇总两个新点四次冷启动的真实计时，不发网络请求。"""
from pathlib import Path
import argparse
import json


def main():
    parser=argparse.ArgumentParser();parser.add_argument('directories',nargs=2,type=Path);args=parser.parse_args()
    reports=[json.loads((p/'report.json').read_text()) for p in args.directories]
    base=args.directories[0].parent
    output=base if base.name=='two-sites-frontier-1100-20261016' else base/'two-sites-frontier-1100-20261016'
    output.mkdir(exist_ok=True)
    lines=['# 两个新点：1.1公里网格与原扇形计时','',
           '| 地点 | 算法 | 用时 | 对数 | HTTP | 首次实测快照 | 错误 | 状态 |',
           '| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |']
    for report in reports:
        for kind in ('fan','grid'):
            run=next(r for r in report['runs'] if r['kind']==kind)
            lines.append(f"| {report['name']} | {'原16向自适应扇形' if kind=='fan' else '新网格v4（1.1公里）'} | {run['elapsedSeconds']:.2f}秒 | {run['pairs']} | {run['accounting']['liveRequests']} | {run['firstMeasuredUpdateSeconds']}秒 | {run['accounting']['errors']} | {run['status']} |")
    lines+=['','两地点采用相反先后顺序；每种算法独立空缓存，15分钟阈值，各376对上限，同样50对/12.5秒滚动窗口并叠加串行节奏。算法间冷却与杭州补测间隔不计时。',
            '杭州首次采用原窗口时触发RATE_LIMITED，失败记录单独保留，没有计入完成耗时；冷却后两算法统一改为上述保守窗口。',
            '杭州新版曾被本地队列10秒上限截断，第三批未发出，前两批60对单列为失败尝试；测试工具改为先在外层等足额度，新版使用另一套空缓存补测，已完成的扇形没有重测。',
            '新网格限制半径1.1公里，旧扇形保留原1.8公里括界，不能作为同范围同精度排名；无完整真值。仅两地点各一轮，不推断普遍速度倍数。']
    summary={'sites':reports,'artifactDirectories':[str(p.resolve()) for p in args.directories]}
    (output/'report.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
    (output/'README.md').write_text('\n'.join(lines)+'\n')
    print('\n'.join(lines))


if __name__=='__main__':main()
