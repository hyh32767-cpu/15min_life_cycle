"""Shunlu introduction and neural narration over actual operation footage.

Speech stays at its synthesized speed. The video follows the sentence length;
there is no audio time compression and no screenshot/frozen-frame padding.
"""
import asyncio, hashlib, json, math, os, subprocess, sys, wave
from pathlib import Path

sys.path.insert(0,'/tmp/shunlu-voice-deps')
import edge_tts

ROOT=Path(__file__).resolve().parents[2]/'output/demo-video-20261016'
PART=ROOT/'shunlu-parts';PART.mkdir(exist_ok=True)
FF=os.environ.get('FFMPEG','/tmp/shunshou-video-deps/imageio_ffmpeg/binaries/ffmpeg-macos-aarch64-v7.1')
VOICE='zh-CN-XiaoxiaoNeural'
INTRO='这是顺路。看看附近有什么，也把路上的事，顺便安排好。'
cuts=json.loads((ROOT/'operation-cuts.json').read_text())
texts=[INTRO]+[c['caption'] for c in cuts]
rates=['-3%']+['-3%' for i in cuts]

def run(args):
    r=subprocess.run(args,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    if r.returncode:raise RuntimeError(r.stderr.decode(errors='replace')[-3500:])
def stamp(t):
    t=round(t*1000);h,t=divmod(t,3600000);m,t=divmod(t,60000);s,ms=divmod(t,1000)
    return f'{h:02}:{m:02}:{s:02},{ms:03}'
def at(t):return stamp(t).replace(',','.')[:-1]
def wrap(s,n=23):return '\\N'.join(s[i:i+n] for i in range(0,len(s),n))
def seconds(file):
    with wave.open(str(file)) as w:return w.getnframes()/w.getframerate()
def header():return '''[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Caption,Heiti SC,38,&H00FFFFFF,&H00FFFFFF,&H000F1929,&H000F1929,0,0,0,0,100,100,0,0,1,1,0,2,52,52,22,1
Style: Chapter,Heiti SC,27,&H00FFFFFF,&H00FFFFFF,&H000F1929,&H000F1929,0,0,0,0,100,100,0,0,1,0,0,7,78,76,18,1
Style: Brand,Heiti SC,27,&H00E2CF79,&H00FFFFFF,&H000F1929,&H000F1929,0,0,0,0,100,100,0,0,1,0,0,9,76,76,18,1
Style: Badge,Heiti SC,24,&H00FFFFFF,&H00FFFFFF,&H001A3D65,&H001A3D65,0,0,0,0,100,100,0,0,3,7,0,8,65,65,250,1
Style: Intro,Heiti SC,138,&H00FFFFFF,&H00FFFFFF,&H000F1929,&H000F1929,0,0,0,0,100,100,0,0,1,0,0,5,0,0,0,1
[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
'''
def line(end,style,text,start=0):return f'Dialogue: 0,{at(start)},{at(end)},{style},,0,0,0,,{text}\n'

async def speech(i,text,rate,limit):
    sig=hashlib.sha256((VOICE+rate+text).encode()).hexdigest()
    sigfile=PART/f'{i:02}.voice-signature';mp3=PART/f'{i:02}.mp3';wav=PART/f'{i:02}.wav'
    if not sigfile.exists() or sigfile.read_text()!=sig or not wav.exists():
        async with limit:
            chunks=[]
            for attempt in range(3):
                try:
                    chunks=[]
                    with mp3.open('wb') as f:
                        communicate=edge_tts.Communicate(text,VOICE,rate=rate,pitch='+0Hz',connect_timeout=15,receive_timeout=25)
                        async for chunk in communicate.stream():
                            if chunk['type']=='audio':f.write(chunk['data'])
                            elif chunk['type']=='SentenceBoundary':chunks.append(chunk)
                    break
                except Exception:
                    if attempt==2:raise
                    await asyncio.sleep(2+attempt)
            (PART/f'{i:02}.boundaries.json').write_text(json.dumps(chunks,ensure_ascii=False,indent=2))
            run([FF,'-y','-i',str(mp3),'-ar','48000','-ac','1',str(wav)])
            sigfile.write_text(sig)
            (PART/f'{i:02}.txt').write_text(text)
            print(f'voice {i+1}/{len(texts)}',flush=True)
    return seconds(wav)

async def main():
    limit=asyncio.Semaphore(2)
    lengths=await asyncio.gather(*(speech(i,text,rates[i],limit) for i,text in enumerate(texts)))
    if '--voices-only' in sys.argv: return
    intro_d=math.ceil(max(7.5,lengths[0]+1)*25)/25
    transition=.4
    script=header()
    script+=line(intro_d,'Intro',r'{\move(540,890,540,810,0,900)\fad(650,500)}顺路',.15)
    script+=line(intro_d,'Intro',r'{\pos(540,990)\fs40\fad(700,450)}附近生活 · 顺路办事',1.2)
    script+=line(intro_d,'Intro',r'{\pos(540,1070)\fs28\c&HE2CF79&\fad(500,450)}15分钟生活助手',2.0)
    script+=line(2.0,'Caption','这是顺路。')
    script+=line(intro_d-transition,'Caption',wrap('看看附近有什么，也把路上的事，顺便安排好。'),2.0)
    (PART/'intro.ass').write_text(script)
    intro=PART/'intro.mp4'
    run([FF,'-y','-ss','35','-t',str(intro_d*1.5),'-i',str(ROOT/'raw/current-release.webm'),'-i',str(PART/'00.wav'),'-filter_complex',f'[0:v]setpts=(PTS-STARTPTS)/1.5,scale=1080:2025,crop=1080:1920,boxblur=12:2,drawbox=x=0:y=0:w=iw:h=ih:color=0x071327@0.5:t=fill,setsar=1,ass={PART}/intro.ass[v];[1:a]adelay=120,apad,atrim=duration={intro_d},afade=t=in:d=0.08,afade=t=out:st={intro_d-.2}:d=0.2[a]','-map','[v]','-map','[a]','-t',str(intro_d),'-r','25','-c:v','libx264','-preset','veryfast','-crf','19','-pix_fmt','yuv420p','-c:a','aac','-b:a','128k',str(intro)])
    subtitles=[(0,2,'这是顺路。'),(2,intro_d-transition,'看看附近有什么，也把路上的事，顺便安排好。')]
    timeline=[{'chapter':'顺路 · 开场','start':0,'duration':intro_d-transition,'caption':INTRO}]
    cursor=intro_d-transition
    durations=[]
    for i,c in enumerate(cuts):
        source_d=c['end']-c['start'];base_d=source_d/c.get('speed',1)
        dur=math.ceil(max(base_d,lengths[i+1]+.65)*25)/25
        scale=dur/source_d;durations.append(dur)
        script=header()+line(dur,'Caption',wrap(c['caption']))
        script+=line(min(dur,3.4),'Chapter',c['chapter'])+line(dur,'Brand','顺路')
        if c.get('speed',1)>1:script+=line(dur,'Badge',f'加载过程加速 ×{source_d/dur:.1f}')
        ass=PART/f'cut-{i:02}.ass';ass.write_text(script)
        target=PART/f'cut-{i:02}.mp4'
        run([FF,'-y','-ss',str(c['start']),'-t',str(source_d),'-i',str(ROOT/'raw'/c['source']),'-i',str(PART/f'{i+1:02}.wav'),'-filter_complex',f'[0:v]setpts=(PTS-STARTPTS)*{scale},scale=928:1652:flags=lanczos,pad=1080:1920:76:80:color=0x0f1929,setsar=1,ass={ass}[v];[1:a]adelay=120,apad,atrim=duration={dur},afade=t=in:d=0.06,afade=t=out:st={dur-.2}:d=0.2[a]','-map','[v]','-map','[a]','-t',str(dur),'-r','25','-c:v','libx264','-preset','veryfast','-crf','19','-pix_fmt','yuv420p','-c:a','aac','-b:a','128k',str(target)])
        subtitles.append((cursor,cursor+dur,c['caption']))
        timeline.append({**c,'outputStart':round(cursor,3),'outputDuration':dur,'voiceSeconds':lengths[i+1],'audioTimeCompression':False})
        cursor+=dur
        print(f'video {i+1}/{len(cuts)} {dur:.2f}s',flush=True)
    prefix_d=intro_d+durations[0]-transition
    run([FF,'-y','-i',str(intro),'-i',str(PART/'cut-00.mp4'),'-filter_complex',f'[0:v]settb=AVTB[v0];[1:v]settb=AVTB[v1];[v0][v1]xfade=transition=fade:duration={transition}:offset={intro_d-transition}[v];[0:a][1:a]acrossfade=d={transition}[a]','-map','[v]','-map','[a]','-t',str(prefix_d),'-r','25','-c:v','libx264','-preset','veryfast','-crf','19','-pix_fmt','yuv420p','-c:a','aac','-b:a','128k',str(PART/'prefix.mp4')])
    files=[PART/'prefix.mp4']+[PART/f'cut-{i:02}.mp4' for i in range(1,len(cuts))]
    (PART/'concat.txt').write_text('\n'.join(f"file '{f}'" for f in files))
    run([FF,'-y','-f','concat','-safe','0','-i',str(PART/'concat.txt'),'-c','copy','-metadata','title=顺路 · 15分钟生活助手','-movflags','+faststart',str(ROOT/'顺路-新版实操演示.mp4')])
    (ROOT/'顺路-中文字幕.srt').write_text('\n'.join(f'{i+1}\n{stamp(a)} --> {stamp(b)}\n{text}\n' for i,(a,b,text) in enumerate(subtitles)))
    (ROOT/'shunlu-timeline.json').write_text(json.dumps(timeline,ensure_ascii=False,indent=2))
    (ROOT/'shunlu-voice.json').write_text(json.dumps({'voice':VOICE,'rates':rates,'audioTimeCompression':False,'introSeconds':intro_d,'durationSeconds':cursor,'speechSource':'https://github.com/rany2/edge-tts','notes':'神经语音，原速播放；字幕和段落之间保留停顿，画面跟随语句长度。'},ensure_ascii=False,indent=2))
    print(f'DONE {cursor:.2f}s',flush=True)

if __name__=='__main__':asyncio.run(main())
