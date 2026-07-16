/* FMEA v2 mockup — state machine. Demo only; not production code. */
(function(){
"use strict";
const $=(s,c)=>(c||document).querySelector(s), $$=(s,c)=>Array.from((c||document).querySelectorAll(s));
const HEADERS=["Function Description","Failure Mode Causes","Schematic Page","Component Part Description","Part Usage","BAE HDA Commodity Level 1","BAE HDA Commodity Level 2","FMD-2016 Commodity Type 1","FMD-2016 Commodity Type 2","Failure Mode","FM Ratio","FMEA-ID","Part Number","Qty"];
const ROWS=[
{f:"FMEA-ID",origin:"derived",note:"Generated from grouping + BOM data"},
{f:"Function Description",src:"Function Description",st:"auto",note:"Exact header — Grouping · Sheet1"},
{f:"Failure Mode Causes",src:"Failure Mode Causes",st:"auto",note:"Exact header — Grouping · Sheet1"},
{f:"Schematic Page",src:"Schematic Page",st:"auto",note:"Exact header — Grouping · Sheet1"},
{f:"Component Part Description",req:1,src:"Component Part Description",st:"auto",note:"Exact header — BOM · BOM_Flat"},
{f:"Part Usage",src:"Part Usage",st:"auto",note:"Exact header — BOM · BOM_Flat"},
{f:"HDA Commodity Level 1",src:"BAE HDA Commodity Level 1",st:"auto",note:"Exact header — BOM · BOM_Flat"},
{f:"HDA Commodity Level 2",src:"BAE HDA Commodity Level 2",st:"auto",note:"Exact header — BOM · BOM_Flat"},
{f:"FMD-2016 Commodity Type 1",src:"FMD-2016 Commodity Type 1",st:"manual",note:"Manual override"},
{f:"FMD-2016 Commodity Type 2",src:"FMD-2016 Commodity Type 2",st:"manual",note:"Manual override"},
{f:"Failure Mode",req:1,src:"Failure Mode",st:"auto",note:"Exact header — Failure modes · FMD2016"},
{f:"Failure Mode Ratio",req:1,src:"FM Ratio",st:"gap",note:"No exact header — closest match “FM Ratio”"}];
const PREVIEW=[["C201","Short, output-to-ground","0.42"],["C202","Open","0.31"],["U14","Output stuck low","0.28"],["R88","Parameter drift","0.17"],["Q7","Short, collector-emitter","0.24"],["L3","Open winding","0.11"]];
const LOG_BASE=[["14:02:04","info","shell","Desktop bridge connected — PID 4812"],["14:02:29","info","fmea","Indexed 3 sheets · 42 unique headers — PSU-7_BOM_Flat.xlsx"],["14:02:29","warn","fmea","Inspection capped at 5,000 rows — BOM_Flat"],["14:02:30","info","fmea","Auto-mapped 10 of 11 required columns from 3 workbooks"]];
const LOG_BLOCKED=[["14:03:05","err","fmea","validate_run: required column unmapped — Failure Mode Ratio"]];
const LOG_READY=[["14:03:41","info","fmea","Manual override: Failure Mode Ratio ← FM Ratio"]];
const LOG_RUN=[["14:04:02","info","fmea","validate_run OK — 0 errors · 1 warning"],["14:04:03","info","fmea","Generating rows — piece_part_generate · FMD-2016"],["14:04:09","info","fmea","1,284 rows built · 96 failure modes applied"],["14:04:16","info","fmea","Workbook written — FMEA_PSU-7_R2.xlsx (00:14)"]];
const V_CAP={sev:"warn",title:"Workbook inspection capped",detail:"Mapping suggestions for BOM_Flat were built from the first 5,000 rows to keep the bridge responsive.",area:"bom"};
const V_UNMAPPED={sev:"err",title:"Required column unmapped",detail:"Failure Mode Ratio has no source column. Map it in step 04 — the closest header is “FM Ratio”.",area:"mapping"};
let state="loaded", runTimers=[];
const STATUS_META={auto:["dot--ok","Auto"],manual:["dot--acc","Manual"],gap:["dot--warn","Unmapped"],derived:["dot--hollow","Derived"],none:["dot--hollow","—"]};

function rowStatus(r){
  if(state==="pristine")return "none";
  if(r.origin==="derived")return "derived";
  if(r.st==="gap")return (state==="loaded"||state==="blocked")?"gap":"manual";
  return r.st;
}
function renderTable(){
  const tb=$("#maptable tbody"); tb.innerHTML="";
  ROWS.forEach((r,i)=>{
    const st=rowStatus(r), tr=document.createElement("tr");
    const empty=st==="none"||st==="derived";
    const src=st==="gap"?null:(st==="manual"&&r.st==="gap"?"FM Ratio":r.src);
    let selHtml;
    if(empty){selHtml='<select class="sel sel-quiet" data-empty="true" disabled><option>'+(st==="derived"?"— Derived —":"—")+"</option></select>";}
    else if(st==="gap"){selHtml='<select class="sel sel-quiet" data-empty="true"><option selected>— Not mapped —</option>'+HEADERS.map(h=>"<option>"+h+"</option>").join("")+"</select>";}
    else{selHtml='<select class="sel sel-quiet"><option>— Not mapped —</option>'+HEADERS.map(h=>"<option"+(h===src?" selected":"")+">"+h+"</option>").join("")+"</select>";}
    const meta=STATUS_META[st];
    const note=state==="pristine"?(r.origin==="derived"?r.note:""):(st==="manual"&&r.st==="gap"?"Manual override — “FM Ratio”":r.note);
    const apply=st==="gap"?'<button class="mt-apply" type="button" data-apply="1">Apply match</button>':"";
    tr.innerHTML='<td class="mt-field">'+r.f+(r.req?'<span class="f-req" title="Required — Do Not Map blocks the run."> *</span>':"")+'</td><td class="mt-src">'+selHtml+'</td><td><span class="mt-st"><i class="dot '+meta[0]+'"></i><em>'+meta[1]+"</em></span></td><td><span class=\"mt-note\" title=\""+note+'">'+note+"</span> "+apply+"</td>";
    tb.appendChild(tr);
  });
  $$("[data-apply]").forEach(b=>b.addEventListener("click",()=>setState("ready")));
}
function renderFiles(){
  const pristine=state==="pristine";
  $$(".file-row").forEach((row,i)=>{
    row.dataset.st=pristine?(i===0?"active":"pending"):"loaded";
    const path=$(".f-path",row), sheet=$(".f-sheet",row), copy=$(".copybtn",row);
    if(pristine){path.dataset.empty="true";path.textContent="No file selected";path.removeAttribute("title");sheet.hidden=true;copy.hidden=true;}
    else{path.dataset.empty="false";path.textContent=path.getAttribute("data-p")||path.textContent;sheet.hidden=false;copy.hidden=false;}
  });
  $("#inputsMeta").textContent=pristine?"0 of 3 loaded":"3 of 3 loaded";
}
$$(".f-path").forEach(p=>p.setAttribute("data-p",p.textContent));
function chk(k,tone,val){const row=$('.chk-row[data-k="'+k+'"]');row.dataset.ok=tone==="ok";row.dataset.warn=tone==="warn";row.dataset.bad=tone==="bad";
  const ic=$(".i",row);ic.className="i ph"+(tone==="ok"?"-fill ph-check-circle":tone==="warn"?"-fill ph-warning-circle":tone==="bad"?"-fill ph-x-circle":" ph-circle");$(".val",row).textContent=val;}
function renderChecklist(){
  if(state==="pristine"){chk("inputs","dim","0 / 3");chk("mapping","dim","0 / 11");chk("output","dim","Default");}
  else if(state==="loaded"){chk("inputs","ok","3 / 3");chk("mapping","warn","10 / 11");chk("output","ok","Default");}
  else if(state==="blocked"){chk("inputs","ok","3 / 3");chk("mapping","bad","10 / 11");chk("output","ok","Default");}
  else{chk("inputs","ok","3 / 3");chk("mapping","ok","11 / 11");chk("output","ok","Default");}
}
function renderCoverage(){
  const m={pristine:["0 / 11",0,"Waiting for inputs"],loaded:["10 / 11",91,'<span class="num">8</span> auto · <span class="num">2</span> manual · <span class="num">1</span> derived · <span class="num">1</span> unmapped'],blocked:["10 / 11",91,'<span class="num">8</span> auto · <span class="num">2</span> manual · <span class="num">1</span> derived · <span class="num">1</span> unmapped']}[state]||["11 / 11",100,'<span class="num">8</span> auto · <span class="num">3</span> manual · <span class="num">1</span> derived · <span class="num">0</span> unmapped'];
  $("#covNum").textContent=m[0];$("#covBar").style.width=m[1]+"%";$("#mapCounts").innerHTML=m[2];
}
function badge(cls,n){return '<span class="badge badge--'+cls+'">'+n+"</span>";}
function renderValidation(){
  const list=$("#vList"), badges=$("#vBadges");
  let items=[];
  if(state==="pristine"){list.innerHTML='<p class="v-empty">Runs automatically before generation.</p>';badges.innerHTML="";return;}
  if(state==="blocked")items=[V_UNMAPPED,V_CAP];else items=[V_CAP];
  list.innerHTML=items.map(v=>'<div class="v-row"><i class="dot dot--'+(v.sev==="err"?"bad":"warn")+'"></i><div><b>'+v.title+"</b><p>"+v.detail+'</p></div><span class="v-area">'+v.area+"</span></div>").join("");
  badges.innerHTML=(items.some(v=>v.sev==="err")?badge("bad",items.filter(v=>v.sev==="err").length):"")+badge("warn",items.filter(v=>v.sev==="warn").length);
}
function renderPreview(){
  const wrap=$("#pWrap"), meta=$("#pMeta");
  if(state==="pristine"||state==="loaded"){wrap.innerHTML='<p class="p-empty">Validate to sample output rows.</p>';meta.textContent="";return;}
  if(state==="blocked"){wrap.innerHTML='<p class="p-empty">Blocked — resolve validation errors to sample rows.</p>';meta.textContent="";return;}
  meta.textContent="24 sampled";
  wrap.innerHTML='<table class="prevtable"><thead><tr><th>RefDes</th><th>Failure mode</th><th>Ratio</th></tr></thead><tbody>'+PREVIEW.map(r=>"<tr><td>"+r[0]+"</td><td>"+r[1]+"</td><td>"+r[2]+"</td></tr>").join("")+'</tbody></table><button class="p-more" type="button">Open full preview</button>';
}
function logLine(l){return '<div class="log-line" data-lv="'+l[1]+'"><span class="lt">'+l[0]+'</span><span class="lv'+(l[1]==="warn"?" lv--warn":l[1]==="err"?" lv--err":"")+'">'+l[1].toUpperCase()+'</span><span class="ltool">'+l[2]+'</span><span class="lmsg">'+l[3]+"</span></div>";}
let logLines=[];
function setLog(lines){logLines=lines.slice();$("#logBody").innerHTML=logLines.map(logLine).join("");renderLogMeta();}
function appendLog(l){logLines.push(l);$("#logBody").insertAdjacentHTML("beforeend",logLine(l));$("#logBody").scrollTop=$("#logBody").scrollHeight;renderLogMeta();}
function renderLogMeta(){
  $("#logCount").textContent=logLines.length;
  const w=logLines.filter(l=>l[1]==="warn").length,e=logLines.filter(l=>l[1]==="err").length;
  $("#logSev").innerHTML=(e?badge("bad",e):"")+(w?badge("warn",w):"");
}
function baseLog(){
  if(state==="pristine")return [LOG_BASE[0]];
  if(state==="loaded")return LOG_BASE.slice();
  if(state==="blocked")return LOG_BASE.concat(LOG_BLOCKED);
  if(state==="ready")return LOG_BASE.concat(LOG_BLOCKED,LOG_READY);
  return LOG_BASE.concat(LOG_BLOCKED,LOG_READY,LOG_RUN);
}
function renderRun(){
  const cta=$("#cta"),label=$("#ctaLabel"),block=$("#runBlock"),st=$("#runSt"),cancel=$("#cancelBtn");
  $("#progWrap").hidden=true;$("#resultWrap").hidden=true;cancel.hidden=true;
  block.hidden=true;block.style.color="";
  if(state==="pristine"){st.textContent="idle";cta.disabled=true;label.textContent="Generate FMEA";block.hidden=false;block.textContent="Load the three required inputs to enable generation.";block.style.color="var(--text-faint)";}
  else if(state==="loaded"){st.textContent="idle";cta.disabled=false;label.textContent="Generate FMEA";}
  else if(state==="blocked"){st.textContent="blocked";cta.disabled=true;label.textContent="Generate FMEA";block.hidden=false;block.textContent="1 error — map Failure Mode Ratio in step 04 to run.";}
  else if(state==="ready"){st.textContent="ready";cta.disabled=false;label.textContent="Generate FMEA";}
  else if(state==="running"){st.textContent="running";cta.disabled=true;label.textContent="Running…";$("#progWrap").hidden=false;cancel.hidden=false;}
  else{st.textContent="complete";cta.disabled=false;label.textContent="Generate again";$("#progWrap").hidden=false;$("#resultWrap").hidden=false;}
}
function setPhase(i,stt,t){const p=$('.phase[data-ph="'+i+'"]');p.dataset.st=stt;const ic=$(".i",p);
  if(stt==="done"){ic.outerHTML='<i class="i ph-fill ph-check-circle"></i>';}
  else if(stt==="active"){ic.outerHTML='<span class="spin i"></span>';}
  else{ic.outerHTML='<i class="i ph ph-circle"></i>';}
  if(t!==undefined)$(".t",p).textContent=t;}
function resetPhases(done){[0,1,2].forEach(i=>setPhase(i,done?"done":"pending",done?["00:01","00:09","00:04"][i]:""));}
function setBackend(busy){$("#beDot").className="dot "+(busy?"dot--acc dot--pulse":"dot--ok");$("#beLabel").textContent=busy?"Busy":"Ready";}
function clearTimers(){runTimers.forEach(clearTimeout);runTimers=[];}
function startRun(){
  clearTimers();state="running";renderAll();
  $("#logbar").dataset.open="true";setBackend(true);
  setLog(baseLog().slice(0,LOG_BASE.length+LOG_BLOCKED.length+LOG_READY.length));
  const bar=$("#progBar"),pct=$("#progPct"),phase=$("#progPhase");
  const steps=[[0,"Validating run state",0,"active"],[900,"Validating run state",18,null,()=>{appendLog(LOG_RUN[0]);}],[1100,"Generating FMEA rows",22,null,()=>{setPhase(0,"done","00:01");setPhase(1,"active");appendLog(LOG_RUN[1]);}],[2400,"Generating FMEA rows",54],[3600,"Generating FMEA rows",78,null,()=>{appendLog(LOG_RUN[2]);}],[4200,"Writing workbook",84,null,()=>{setPhase(1,"done","00:09");setPhase(2,"active");}],[5400,"Writing workbook",100,null,()=>{setPhase(2,"done","00:04");appendLog(LOG_RUN[3]);}],[5900,"",100,null,()=>{state="success";renderAll();}]];
  resetPhases(false);setPhase(0,"active");
  steps.forEach(s=>{runTimers.push(setTimeout(()=>{if(s[1])phase.textContent=s[1];bar.style.width=s[2]+"%";pct.textContent=s[2]+"%";if(s[4])s[4]();},s[0]));});
}
function renderAll(){
  document.body.dataset.state=state;
  renderFiles();renderTable();renderChecklist();renderCoverage();renderValidation();renderPreview();renderRun();
  if(state!=="running"){setLog(baseLog());setBackend(false);if(state==="success"){resetPhases(true);$("#progBar").style.width="100%";$("#progPct").textContent="100%";$("#progPhase").textContent="Complete";}}
  $$(".demo button[data-s]").forEach(b=>b.dataset.on=String(b.dataset.s===state));
}
function setState(s){clearTimers();if(s==="running"){if(state!=="ready"&&state!=="success"){state="ready";}startRun();return;}state=s;renderAll();}
$$(".demo button[data-s]").forEach(b=>b.addEventListener("click",()=>setState(b.dataset.s)));
$("#cta").addEventListener("click",()=>{if(state==="loaded"){setState("blocked");}else if(state==="ready"||state==="success"){startRun();}});
$("#cancelBtn").addEventListener("click",()=>{clearTimers();setState("ready");});
$("#logToggle").addEventListener("click",()=>{const lb=$("#logbar");lb.dataset.open=lb.dataset.open==="true"?"false":"true";});
$("#logCopy").addEventListener("click",function(){this.textContent="Copied";setTimeout(()=>this.textContent="Copy",1200);});
$$("#modes .mode").forEach((m,i)=>m.addEventListener("click",()=>{$$("#modes .mode").forEach(x=>x.dataset.on="false");m.dataset.on="true";$("#tbMode").textContent=$("h3",m).textContent;$("#ccaField").hidden=i!==3;}));
[["segFmd"],["segHda"],["segStrat"]].forEach(([id])=>{$$("#"+id+" button").forEach(b=>b.addEventListener("click",()=>{$$("#"+id+" button").forEach(x=>x.dataset.on="false");b.dataset.on="true";if(id==="segStrat")$("#targetRow").hidden=b.textContent==="New workbook";}));});
$$(".copybtn").forEach(b=>b.addEventListener("click",()=>{b.dataset.done="true";$(".i",b).className="i ph ph-check";setTimeout(()=>{b.dataset.done="false";$(".i",b).className="i ph ph-copy";$(".i",b).style.fontSize="12px";},1200);b.querySelector(".i").style.fontSize="12px";}));
$("#applyAll").addEventListener("click",()=>{if(state==="loaded"||state==="blocked")setState("ready");});
$("#themeBtn").addEventListener("click",()=>{const h=document.documentElement,dark=h.dataset.theme!=="dark_precision";h.dataset.theme=dark?"dark_precision":"light";$("#themeBtn .i").className="i ph "+(dark?"ph-sun":"ph-moon");});
function fit(){const sh=$(".shell"),s=Math.min(1,window.innerWidth/1440);sh.style.transform=s<1?"scale("+s+")":"";sh.style.height=(window.innerHeight/s)+"px";}
window.addEventListener("resize",fit);fit();
renderAll();
})();
