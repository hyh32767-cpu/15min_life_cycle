// Real browser recording controller. No business API fixtures or response replacement.
const {chromium}=require('../../web/node_modules/playwright');
const fs=require('node:fs/promises');
const path=require('node:path');
const http=require('node:http');
(async()=>{
 const dir=path.resolve(__dirname,'../../output/demo-video-20261016');
 await fs.mkdir(dir+'/raw',{recursive:true});await fs.mkdir(dir+'/shots',{recursive:true});
 const browser=await chromium.launch({headless:true,args:['--enable-webgl','--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
 const ctx=await browser.newContext({viewport:{width:480,height:854},recordVideo:{dir:dir+'/raw',size:{width:480,height:854}},acceptDownloads:true});
 const page=await ctx.newPage();page.setDefaultTimeout(8000);
 const start=Date.now(),marks=[],events=[];
 const mark=(name,caption='')=>{const item={name,caption,t:(Date.now()-start)/1000};marks.push(item);return item;};
 const save=async()=>{
  await fs.writeFile(dir+'/marks.json',JSON.stringify(marks,null,2));
  await fs.writeFile(dir+'/api-events.json',JSON.stringify(events,null,2));
 };
 page.on('response',async response=>{
  const pathname=new URL(response.url()).pathname;
  if(!pathname.startsWith('/api/')||pathname==='/api/maps/config')return;
  const row={t:(Date.now()-start)/1000,path:pathname,status:response.status()};
  try{
   const data=await response.json();
   for(const key of ['status','thresholdSeconds','pairsUsed','algorithmVersion','cacheHit','backgroundStatus'])if(data[key]!==undefined)row[key]=data[key];
   if(data.error)row.errorCode=data.error.code;
   if(data.cost)row.cost=data.cost;
  }catch{}
  events.push(row);await save();
 });
 page.on('pageerror',error=>events.push({t:(Date.now()-start)/1000,type:'pageerror',message:error.message}));
 await page.goto('http://127.0.0.1:5173/community');
 await page.locator('.shell__search').waitFor();mark('ready');await save();
 const server=http.createServer(async(req,res)=>{
  let code='';for await(const part of req)code+=part;
  try{
   if(req.url==='/finish'){
    mark('finish');await save();const video=page.video();await ctx.close();await video.saveAs(dir+'/raw/current-release.webm');
    await browser.close();res.end(JSON.stringify({ok:true,marks:marks.length}));server.close();return;
   }
   const result=await new Function('page','ctx','fs','dir','mark','save','return (async()=>{'+code+'})()')(page,ctx,fs,dir,mark,save);
   await save();res.end(JSON.stringify({ok:true,result}));
  }catch(error){await page.screenshot({path:dir+'/last-error.png'}).catch(()=>{});await save();res.end(JSON.stringify({ok:false,error:error.message}));}
 });
 server.listen(18891,'127.0.0.1');console.log('Real capture ready on local controller 18891',flush=true);
})();
