"""Project introduction PDF with current product captures and vector diagrams."""
import json
import math
from pathlib import Path
from xml.sax.saxutils import escape
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.colors import HexColor, Color, white
from reportlab.platypus import Paragraph
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader

ROOT=Path(__file__).resolve().parents[2]
SHOTS=ROOT/'output/demo-video-20261016/shots'
OUT=ROOT/'output/pdf/顺路项目介绍.pdf'
W,H=595.276,841.89
INK=HexColor('#17263f');MUTED=HexColor('#657790');BLUE=HexColor('#2864ed')
PALE=HexColor('#f2f6ff');LINE=HexColor('#dfe7f3');GREEN=HexColor('#12a77e')


def main():
    OUT.parent.mkdir(parents=True,exist_ok=True)
    for name,path in [('Body','/System/Library/Fonts/STHeiti Light.ttc'),('Bold','/System/Library/Fonts/STHeiti Medium.ttc')]:
        pdfmetrics.registerFont(TTFont(name,path,subfontIndex=0))
    c=canvas.Canvas(str(OUT),pagesize=(W,H))
    c.setTitle('顺路项目介绍');c.setAuthor('顺路项目');c.setSubject('项目背景 技术架构 应用场景 创新点')
    def text(s,x,y,size=11,color=INK,bold=False):
        c.setFillColor(color);c.setFont('Bold' if bold else 'Body',size);c.drawString(x,y,s)
    def para(s,x,y,width,size=11,color=INK,leading=None,bold=False):
        style=ParagraphStyle('p',fontName='Bold' if bold else 'Body',fontSize=size,leading=leading or size*1.75,textColor=color,wordWrap='CJK',spaceAfter=0)
        p=Paragraph(s,style);_,h=p.wrap(width,H);p.drawOn(c,x,y-h);return y-h
    def card(x,y,w,h,fill=PALE):
        c.setFillColor(fill);c.setStrokeColor(LINE);c.setLineWidth(.6);c.roundRect(x,y,w,h,14,stroke=1,fill=1)
    def page(n,title,kicker):
        c.setFillColor(white);c.rect(0,0,W,H,fill=1,stroke=0)
        text('顺路',44,H-35,11,BLUE,True);text(kicker,84,H-35,9,MUTED)
        text(title,44,H-91,27,INK,True)
        c.bookmarkPage('p'+str(n));c.addOutlineEntry(title,'p'+str(n),0,False)
        c.setStrokeColor(LINE);c.setLineWidth(.6);c.line(44,43,W-44,43)
        text('顺路  项目介绍',44,27,8.5,MUTED);text(f'{n:02d} / 08',W-82,27,8.5,MUTED)
    def shot(name,x,y,w,h):
        path=SHOTS/name
        if not path.exists():raise FileNotFoundError(path)
        im=ImageReader(str(path));iw,ih=im.getSize();scale=min(w/iw,h/ih)
        c.drawImage(im,x+(w-iw*scale)/2,y+(h-ih*scale)/2,width=iw*scale,height=ih*scale,mask='auto')
    def phone(name,x,y,w,h):
        card(x-5,y-5,w+10,h+10,white);shot(name,x,y,w,h)
    def arrow(x1,y1,x2,y2,color=BLUE):
        c.setStrokeColor(color);c.setFillColor(color);c.setLineWidth(1.3);c.line(x1,y1,x2,y2)
        a=math.atan2(y2-y1,x2-x1);p=c.beginPath();p.moveTo(x2,y2)
        p.lineTo(x2-7*math.cos(a-.45),y2-7*math.sin(a-.45));p.lineTo(x2-7*math.cos(a+.45),y2-7*math.sin(a+.45));p.close();c.drawPath(p,fill=1,stroke=0)
    def box(title,body,x,y,w,h,fill=PALE):
        card(x,y,w,h,fill);text(title,x+15,y+h-28,13,INK,True);para(body,x+15,y+h-43,w-30,10,MUTED,16)

    # Cover
    page(1,'顺路项目介绍','15分钟生活圈与沿途便民服务')
    c.setFillColor(PALE);c.circle(545,645,135,fill=1,stroke=0)
    text('顺路',44,647,55,INK,True)
    para('15分钟生活圈分析<br/>与沿途便民服务推荐平台',46,608,290,19,INK,30,True)
    para('家门口有什么，步行能到哪，路上还能办什么。',46,520,284,12,BLUE,21)
    para('顺路把社区生活圈分析与日常出行连接起来。先用地图了解附近服务，再把买药、买菜、取快递等事情放进一条可调整的步行路线。',46,471,278,12,INK,22)
    phone('05-circle-ready.png',355,185,186,332)
    for i,(a,b) in enumerate([('生活圈','5 / 10 / 15分钟可达范围'),('社区评分','设施覆盖与服务短板'),('顺路办事','一句话安排 可继续修改')]):
        yy=276-i*58;text(a,46,yy,13,INK,True);text(b,46,yy-21,10,MUTED)
    text('产品介绍  2026年10月',46,94,9,MUTED)
    c.showPage()

    page(2,'从附近有设施到真正走得到','项目背景')
    y=para('一刻钟便民生活圈关注的是居民在步行约十五分钟的范围里，能否方便获得日常服务。商务部相关建设指南覆盖便利店、菜市场、药店、快递等基本服务，并关注养老、托育和品质生活需求。',44,714,507,11.5)
    para('地图上的距离并不能直接回答生活是否方便。河流、出入口和道路绕行会改变步行时间；一家店离家很近，也未必在出门办事的顺路方向。',44,y-19,507,11.5)
    card(44,366,507,177,white)
    text('看起来很近',66,514,12,INK,True);text('沿道路实际步行',306,514,12,INK,True)
    c.setStrokeColor(LINE);c.setLineWidth(1);c.line(285,386,285,521)
    for cx in [158,410]:
        c.setFillColor(PALE);c.circle(cx,447,51,fill=1,stroke=0)
        c.setFillColor(BLUE);c.circle(cx-30,434,5,fill=1,stroke=0)
        c.setFillColor(GREEN);c.circle(cx+30,460,5,fill=1,stroke=0)
    c.setStrokeColor(MUTED);c.setDash(3,3);c.line(128,434,188,460);c.setDash()
    c.setStrokeColor(BLUE);c.setLineWidth(2.5);p=c.beginPath();p.moveTo(380,434);p.lineTo(380,477);p.lineTo(430,477);p.lineTo(430,460);p.lineTo(440,460);c.drawPath(p)
    text('直线距离无法说明可达时间',73,391,9,MUTED);text('步行用时反映绕行与连接关系',311,391,9,MUTED)
    text('三类日常问题',44,328,17,INK,True)
    box('居民想知道','附近能否方便买菜、买药，哪些服务仍不够容易到达。',44,183,159,120)
    box('通勤者想知道','回家路上办几件事，怎样少折返，并按时到终点。',218,183,159,120)
    box('社区工作者想知道','哪些位置服务覆盖较弱，新增服务点可能改善哪里。',392,183,159,120)
    para('顺路以地图可检索设施和真实步行测时为基础，把这些问题变成可以查看、比较和继续调整的结果。',44,146,507,11.5)
    text('背景参考  城市一刻钟便民生活圈建设指南及2025年扩围升级通知',44,70,8,MUTED)
    c.showPage()

    page(3,'看清社区服务覆盖','生活圈与设施社区评分')
    para('搜索地址、地图选点或选择收藏地点，自动生成步行时间分层。随后选择关心的服务，看设施位置、覆盖分布和简短的社区解读。',44,714,507,11.5)
    phone('06-community-score.png',48,205,290,429)
    y=625
    for title,body in [('时间分层','绿色、青色和蓝色依次表示五分钟、十分钟和十五分钟范围。后续设施分析以十五分钟为准。'),('按需选择服务','目录包含基本便民、品质生活与公共配套，共二十九项服务，可只查询自己关心的类别。'),('地图与评分联动','点选服务卡，在地图上查看对应设施；未覆盖采样点与新增设施建议放在同一分析流程。'),('社区解读','在已有统计完成后生成短文，说明当前服务的长处与不足。')]:
        text(title,363,y,13,INK,True);y=para(body,363,y-16,182,10.5,MUTED,18)-25
    card(44,75,507,99)
    text('怎样理解覆盖与分数',60,148,12,INK,True)
    para('每类覆盖率表示：采样点中，能在十五分钟内步行到达至少一家参评设施的比例。社区分数取所选服务覆盖率的平均值。未知结果保留为未知，不把未检索到设施等同于现实中没有服务。',60,130,474,10.2,MUTED,17)
    c.showPage()

    page(4,'把路上的事情一起安排','顺路办事与自然语言推荐')
    para('起点和终点可以是任意地点。先查看沿途服务，再用一句话说明要办什么、能多花多久。顺路会在已有真实候选中选店，通过路径计算形成可执行的安排。',44,714,507,11.5)
    card(44,588,507,58,PALE)
    text('试着说',60,623,10,MUTED);text('先买药再取快递  每处停留两分钟  九十分钟内到终点',60,604,11,BLUE,True)
    shot('10-route-ai.png',44,369,507,194)
    text('生成之后仍由你决定',44,336,17,INK,True)
    para('推荐结果直接进入原来的途经点列表，地点、顺序和地图路线一起更新。之后仍可换一家店、增加或删除地点、拖动调整顺序，或修改停留时间再重新规划。',44,310,507,11.5)
    shot('11-waypoints.png',44,120,320,128)
    para('原来的地点和路线收藏继续可用。同类任务会复用，安排失败时保留已有计划。',389,239,155,10.5,MUTED,18)
    para('未说明停留时长时，沿用当前设置；有营业时间数据时纳入约束，未提供时保持未知。',44,87,507,9,MUTED,15)
    c.showPage()

    page(5,'地图 算法与语言模型各司其职','技术架构')
    para('前端负责选择与展示，后端组织数据和计算。语言模型负责理解需求与说明结果；位置、步行耗时和路线可行性仍由地图服务及规划算法提供。',44,714,507,11.5)
    box('移动端优先的交互','Vue 3  TypeScript  Pinia\n地图抽屉  设施卡片  途经点编辑  图表与报告',71,564,453,81,white)
    arrow(297,561,297,535)
    box('应用与计算服务','FastAPI  Python\n坐标转换  POI整理  等时圈任务  覆盖计算  多任务路径规划',71,427,453,105)
    arrow(166,425,166,394);arrow(424,425,424,394)
    box('百度地图开放能力','地理编码与逆地理编码\n地点检索  步行路径  批量距离矩阵\n百度地图JS API绘制底图与覆盖物',44,255,245,135,white)
    box('大模型服务','需求转为类别 时间和先后关系\n根据已有覆盖统计生成短文\n结构化输出和服务端校验',307,255,244,135,white)
    box('数据与复用','SQLite保存地图响应 派生结果与调用记录；有效期内复用相同查询。模型短文使用有界短时缓存。服务凭据仅保留在后端。',71,103,453,109)
    arrow(297,427,297,216,MUTED)
    text('数据通过服务端统一组织  前端不持有服务端密钥',112,73,9,MUTED)
    c.showPage()

    page(6,'沿着边界逐步看清生活圈','等时圈算法与渐进绘图')
    para('顺路调用百度步行距离矩阵获取测点的实际路网用时，再从离散测时重建近似可达区域。这个过程不要求下载完整道路拓扑，也不会把直线半径直接当成步行范围。',44,714,507,11.5)
    card(44,306,265,316,white)
    cx,cy,r=176,474,111
    c.setStrokeColor(LINE);c.setLineWidth(1);c.circle(cx,cy,r,fill=0,stroke=1)
    state_path=ROOT/'output/demo-video-20261016/circle-900.json'
    if state_path.exists():
        data=json.loads(state_path.read_text());frontier=data.get('frontier',{});radius=frontier.get('radiusM',1100)
        for p in frontier.get('samples',[]):
            color=GREEN if p.get('state')=='reachable' else HexColor('#b8c5d7') if p.get('state')=='outside' else HexColor('#d6a35a')
            c.setFillColor(color);c.circle(cx+p['x']/radius*r,cy+p['y']/radius*r,1.9,fill=1,stroke=0)
        c.setStrokeColor(BLUE);c.setLineWidth(1.4)
        center=data.get('origin')
        if center:
            for line in data.get('reconstruction',{}).get('contours',[]):
                path=c.beginPath()
                for i,p in enumerate(line):
                    xx=cx+(p['lng']-center['lng'])*111320*math.cos(math.radians(center['lat']))/radius*r
                    yy=cy+(p['lat']-center['lat'])*111320/radius*r
                    (path.moveTo if i==0 else path.lineTo)(xx,yy)
                c.drawPath(path,stroke=1)
    c.setFillColor(INK);c.circle(cx,cy,3,fill=1,stroke=0)
    text('本次生活圈的采样与显示线',67,335,10,MUTED)
    y=605
    for i,(title,body) in enumerate([('圆形网格作为起点','以一百米网格覆盖圆形测量区域，十五分钟圈的搜索半径上限为一点一公里。'),('先外侧 再向内','外侧同层测完再进入内层；可达分支停止继续深入，减少不必要的查询。'),('检查内部连接','主边界之后检查轴线，并沿已知超时或断路位置追踪内部屏障。'),('逐批更新地图','加载时显示连续变化的预览轮廓，完成后显示实测点时间场的拟合线。')]):
        text(str(i+1).zfill(2),332,y,13,BLUE,True);text(title,361,y,12,INK,True)
        y=para(body,361,y-16,187,10.2,MUTED,17)-25
    card(44,119,507,132)
    text('看得顺滑  计算仍保留原始几何',60,224,14,INK,True)
    para('绘图中的平滑和过渡只改变显示效果。设施过滤、覆盖分析和面积计算使用独立的分析多边形，保留孔洞与分离区域。步行时间分层分别测量，并复用已有测点数据。',60,201,474,10.8,MUTED,18)
    para('边界是有限采样推导的近似范围；狭窄障碍和未测区域仍需结合更细数据或现场调查。',44,87,507,9,MUTED,15)
    c.showPage()

    page(7,'让分析结果进入日常行动','创新点与工程设计')
    items=[('渐进分析','采用外向内的圆盘网格前沿，按批发布测量进度。长计算过程有可见反馈，用户先看到变化，再获得完整结果。'),
        ('分析与绘图分离','加载预览和视觉圆角不参与覆盖判定，让流畅的地图表现与采样计算各自保持清晰职责。'),
        ('社区与沿途连接','同一个地点既能分析周边服务，也能成为路线的出发位置。沿途生活圈固定十五分钟，方便继续查看当地设施。'),
        ('自然语言与确定性规划结合','用一句话提取要办的事与时间，把选店和可行性留给实际计算；推荐直接进入可编辑的途经点列表。')]
    for i,(title,body) in enumerate(items):
        xx=44+(i%2)*263;yy=422-(i//2)*180
        box(title,body,xx,yy,244,153,white)
        text(str(i+1).zfill(2),xx+206,yy+125,10,BLUE)
    text('把有限接口资源用在需要的地方',44,205,17,INK,True)
    para('地图请求通过后端统一发送，步行矩阵按路线对数控制批量和节奏。缓存区分接口、坐标系、方向、时间与算法版本，过期结果不当作当前结果继续使用。',44,178,507,11.3)
    para('接口异常或频率受限时保留已有结果，明确哪些信息尚未查明。社区解读与路线需求解析只在用户主动操作时调用，避免额外的地图查询和反复生成。',44,110,507,11.3)
    c.showPage()

    page(8,'从个人出行到社区服务改善','应用场景')
    rows=[('日常生活','在一个准备搬入或常去的社区，看看买菜、买药、养老等服务是否容易步行到达。'),('下班办事','给定起终点、办事内容与可用时间，推荐沿途地点，再由用户调整行程。'),('社区服务观察','把不同服务的覆盖分布放到同一张地图，发现值得进一步调查的位置。'),('新增服务讨论','试放一个假设服务点，比较新增前后的采样覆盖变化，为现场调研和方案讨论提供参考。')]
    y=705
    for title,body in rows:
        text(title,44,y,14,INK,True);y=para(body,173,y+3,375,11.2,MUTED,19)-38
    card(44,185,507,151)
    text('在 GitHub 了解顺路',63,305,19,INK,True)
    para('先选一个熟悉的地点，<br/>看看附近有什么，再安排路上的事。',63,276,300,12,INK,22)
    repository='https://github.com/hyh32767-cpu/15min_life_cycle'
    text(repository,63,217,11,BLUE)
    c.linkURL(repository,(61,211,535,233),relative=0)
    text('参考资料',44,145,11,INK,True)
    for yy,label,url in [(123,'商务部 城市一刻钟便民生活圈建设指南 2021','https://www.mofcom.gov.cn/zwgk/gztz/art/2021/art_04807f8fe711403485c7d962a83a1172.html'),(103,'商务部 加力推动城市一刻钟便民生活圈建设扩围升级通知 2025','https://www.mofcom.gov.cn/gztz/art/2025/art_989b4d7d0d5842db8177a7ea4d29236a.html')]:
        text(label,44,yy,8.5,MUTED);c.linkURL(url,(44,yy-3,551,yy+10),relative=0)
    text('本文按2026年10月当前产品撰写  截图来自产品实际操作',44,72,8,MUTED)
    c.showPage();c.save();print(OUT)


if __name__=='__main__':main()
