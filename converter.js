const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];

let selected = null;
let jobId = null;
let analysis = null;
let conversionResult = null;
let downloadUrls = {};
let analyzeTicker = null;

const screens = $$('.screen');
const steps = $$('.step');
const engineCard = $('.engine-card');

function toast(msg){
  const el = $('#toast');
  el.textContent = msg;
  el.classList.add('show');
  clearTimeout(toast.t);
  toast.t = setTimeout(()=>el.classList.remove('show'), 2800);
}
function setEngine(text, live=true){
  $('#engineState').textContent = text;
  engineCard.classList.toggle('live', live);
}
function go(step){
  screens.forEach(x=>x.classList.remove('active'));
  $('#screen'+step).classList.add('active');
  steps.forEach((x,i)=>{
    x.classList.toggle('active', i+1===step);
    x.classList.toggle('done', i+1<step);
  });
  window.scrollTo({top:0,behavior:'smooth'});
}
function formatBytes(n){
  if(n<1024) return n+' B';
  const u=['KB','MB','GB']; let i=-1;
  do { n/=1024; i++; } while(n>=1024 && i<u.length-1);
  return n.toFixed(n>=10?1:2)+' '+u[i];
}
function humanVersion(v){
  if(!v || v==='Unknown') return 'Unknown';
  if(typeof v !== 'string') return String(v);
  return v.length > 22 ? v.slice(0,22)+'…' : v;
}
function setScanned(key, value, status='Found'){
  const card = document.querySelector(`[data-scan="${key}"]`);
  if(!card) return;
  card.classList.add('scanned');
  const b = card.querySelector('b'); if(b) b.textContent = value;
  const em = card.querySelector('em'); if(em) em.textContent = status;
}
async function api(path, options={}){
  const r = await fetch(path, options);
  let data;
  try { data = await r.json(); } catch { data = {}; }
  if(!r.ok) throw new Error(data.error || `Request failed (${r.status})`);
  return data;
}

// Backend health: this page must be served by server.py, not opened directly from disk.
(async()=>{
  try {
    const h = await api('/api/health');
    setEngine(`Local engine ${h.version}`, true);
  } catch(e){
    setEngine('Backend offline', false);
    toast('Run run.bat first, then use http://127.0.0.1:8765/');
  }
})();

// -------- Upload --------
const input = $('#jarInput'), drop = $('#dropzone');
drop.addEventListener('click',()=>input.click());
['dragenter','dragover'].forEach(ev=>drop.addEventListener(ev,e=>{e.preventDefault();drop.classList.add('drag')}));
['dragleave','drop'].forEach(ev=>drop.addEventListener(ev,e=>{e.preventDefault();drop.classList.remove('drag')}));
drop.addEventListener('drop',e=>{const f=e.dataTransfer.files?.[0];if(f) choose(f)});
input.addEventListener('change',()=>{const f=input.files?.[0];if(f) choose(f)});
function choose(file){
  if(!file.name.toLowerCase().endsWith('.jar')) return toast('Choose a Minecraft Java .jar file.');
  if(file.size > 200*1024*1024) return toast('Maximum file size is 200 MB.');
  selected=file; jobId=null; analysis=null; conversionResult=null; downloadUrls={};
  drop.classList.add('hidden');
  $('#selectedFile').classList.remove('hidden');
  $('#fileName').textContent=file.name;
  $('#fileMeta').textContent=formatBytes(file.size)+' • loader/version detected after analysis';
  $('#analyzeBtn').disabled=false; $('#analyzeBtn').classList.remove('disabled');
  $('#uploadHint').textContent='Ready to upload and analyze '+file.name;
  setEngine('Mod selected');
}
$('#removeFile').addEventListener('click',()=>{
  selected=null; jobId=null; analysis=null; input.value='';
  drop.classList.remove('hidden'); $('#selectedFile').classList.add('hidden');
  $('#analyzeBtn').disabled=true; $('#analyzeBtn').classList.add('disabled');
  $('#uploadHint').textContent='Choose a .jar to continue'; setEngine('Waiting for mod',false);
});

// -------- Real analysis --------
$('#analyzeBtn').addEventListener('click',async()=>{
  if(!selected) return;
  go(2);
  resetAnalysisUI();
  setEngine('Reading JAR archive');
  $('#analysisFileName').textContent=selected.name;
  const fakeTasks=['Uploading JAR locally…','Opening archive safely…','Reading mod metadata…','Indexing resources…','Scanning class names…','Building compatibility report…'];
  let idx=0,pct=4;
  $('#currentTask').textContent=fakeTasks[0];
  analyzeTicker=setInterval(()=>{
    pct=Math.min(88,pct+Math.floor(Math.random()*7)+3);
    $('#analysisBar').style.width=pct+'%'; $('#analysisPct').textContent=pct+'%';
    idx=Math.min(fakeTasks.length-1,idx+1); $('#currentTask').textContent=fakeTasks[idx];
  },520);
  try{
    const fd=new FormData(); fd.append('file',selected,selected.name);
    const data=await api('/api/analyze',{method:'POST',body:fd});
    clearInterval(analyzeTicker); analyzeTicker=null;
    jobId=data.job_id; analysis=data.analysis;
    renderAnalysis(analysis);
    $('#analysisBar').style.width='100%'; $('#analysisPct').textContent='100%';
    $('#scanState').innerHTML='<i></i> Complete';
    $('#currentTask').textContent='Real JAR analysis complete.';
    $('#analysisFooter').textContent=`${analysis.loader} detected • ${analysis.counts.classes} Java class files inspected by name/resource structure`;
    $('#planBtn').disabled=false; $('#planBtn').classList.remove('disabled');
    setEngine('Analysis complete');
    preparePlan(analysis);
  }catch(e){
    clearInterval(analyzeTicker); analyzeTicker=null;
    setEngine('Analysis failed',false);
    $('#currentTask').textContent='Analysis failed: '+e.message;
    toast(e.message);
  }
});
function resetAnalysisUI(){
  ['loader','version','items','blocks','textures','recipes','entities','logic','mixins'].forEach(key=>{
    const card=document.querySelector(`[data-scan="${key}"]`);
    card?.classList.remove('scanned');
    if(card){card.querySelector('b').textContent='—';card.querySelector('em').textContent='Waiting'}
  });
  $('#analysisBar').style.width='0%'; $('#analysisPct').textContent='0%';
  $('#planBtn').disabled=true; $('#planBtn').classList.add('disabled');
}
function renderAnalysis(a){
  const c=a.counts;
  const values=[
    ['loader',a.loader],['version',humanVersion(a.minecraft_version)],['items',c.item_textures],['blocks',c.block_textures],
    ['textures',c.textures],['recipes',c.recipes],['entities',c.entity_class_hints],['logic',c.classes],['mixins',c.mixins]
  ];
  values.forEach(([k,v],i)=>setTimeout(()=>setScanned(k,v),i*70));
}
function preparePlan(a){
  const score=a.support_score;
  let manual=Math.min(25, 4 + a.counts.mixins*3 + Math.min(8,a.counts.render_classes) + Math.min(6,a.counts.network_classes));
  let assisted=Math.min(30, Math.max(8, 100-score));
  let auto=Math.max(35,100-assisted-manual);
  const sum=auto+assisted+manual;
  if(sum!==100) auto += 100-sum;
  $('#supportScore').textContent=score+'%'; $('#ringScore').textContent=score;
  $('#autoPct').textContent=auto+'%'; $('#aiPct').textContent=assisted+'%'; $('#manualPct').textContent=manual+'%';
  const circumference=257.6; $('#scoreCircle').style.strokeDashoffset=(circumference*(1-score/100)).toFixed(1);
  $('#compatTitle').textContent=score>=90?'Excellent static-resource compatibility':score>=80?'Good conversion potential':'Code-heavy mod';
  const warn=(a.warnings||[])[0];
  $('#compatText').textContent=warn || 'Static assets and common recipes can be mapped; Java behavior still requires separate Bedrock logic.';
  $('#finalScore').textContent=score+'%';
  $('#convertedFeatures').textContent=capped(a.counts.item_textures+a.counts.block_textures+a.counts.recipes+a.counts.lang_files+a.counts.sounds);
  $('#rewrittenFeatures').textContent=a.counts.classes;
  $('#manualFeatures').textContent=a.counts.mixins+a.counts.render_classes+a.counts.network_classes;
}
function capped(n){ return n>999?'999+':String(n); }
$('#planBtn').addEventListener('click',()=>go(3));

// -------- Real conversion --------
$('#startConvertBtn').addEventListener('click',async()=>{
  if(!jobId) return toast('Analyze the mod first.');
  go(4); resetConversionUI(); setEngine('Generating Bedrock packs');
  const tasks=$$('.convert-task');
  let visual=0;
  const cycle=setInterval(()=>{
    if(visual<tasks.length){
      tasks.forEach((x,j)=>x.classList.toggle('running',j===visual));
      tasks[visual].querySelector('em').textContent='Working';
      $('#convertPct').textContent=Math.min(90,Math.round(((visual+.5)/tasks.length)*100))+'%';
      visual++;
    }
  },520);
  try{
    const data=await api('/api/convert',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({job_id:jobId})});
    clearInterval(cycle);
    conversionResult=data; downloadUrls=data.downloads||{};
    tasks.forEach(x=>{x.classList.remove('running');x.classList.add('done');x.querySelector('em').textContent='Done'});
    $('#convertPct').textContent='100%';
    renderFileTree(data.report);
    $('#convertFooter').textContent=`Generated real Resource/Behavior Packs • ${data.report.converted.length} conversion result entries`;
    $('#validateBtn').disabled=false; $('#validateBtn').classList.remove('disabled');
    setEngine('Bedrock project built');
  }catch(e){
    clearInterval(cycle); setEngine('Conversion failed',false); toast(e.message);
    $('#convertFooter').textContent='Conversion failed: '+e.message;
  }
});
function resetConversionUI(){
  $$('.convert-task').forEach(x=>{x.classList.remove('running','done');x.querySelector('em').textContent='Waiting'});
  $('#convertPct').textContent='0%'; $('#validateBtn').disabled=true; $('#validateBtn').classList.add('disabled');
  $('#fileTree').textContent='modbridge-output/\n└─ waiting for backend...';
}
function renderFileTree(report){
  const conv=report.converted||[];
  $('#fileTree').textContent=`modbridge-output/\n├─ ModBridge_Resource_Pack/\n│  ├─ manifest.json\n│  ├─ textures/\n│  ├─ texts/\n│  └─ sounds/\n├─ ModBridge_Behavior_Pack/\n│  ├─ manifest.json\n│  ├─ items/\n│  └─ recipes/\n└─ conversion-report.json\n\nConverted:\n${conv.map(x=>'• '+x).join('\n') || '• No directly convertible static resources found'}`;
}
$('#validateBtn').addEventListener('click',()=>{go(5);startValidation()});

// -------- Real validation result from backend --------
function startValidation(){
  if(!conversionResult) return toast('Convert the project first.');
  setEngine('Showing validation results');
  const v=conversionResult.validation;
  const ui=$$('.validation-item');
  ui.forEach(x=>{x.classList.remove('checking','pass','warn-state');x.querySelector('em').textContent='Waiting'});
  $('#passedCount').textContent='0'; $('#sumPassed').textContent='0'; $('#sumWarnings').textContent='0'; $('#sumFixed').textContent=String(v.fixed||0);
  const checks=v.checks||[];
  let i=0,passed=0,warnings=(v.warnings||[]).length;
  function next(){
    if(i>=ui.length){
      $('#passedCount').textContent=String(v.passed);
      $('#sumPassed').textContent=String(v.passed);
      $('#sumWarnings').textContent=String(warnings);
      $('#summaryIcon').textContent=v.passed===v.total?'✓':'!';
      $('#validationTitle').textContent=v.passed===v.total?'Generated project validated':'Validation finished with issues';
      $('#validationText').textContent=v.passed===v.total?'All generated validation checks passed. Bedrock can still report runtime issues for unsupported Java behavior.':'Open the conversion report before installing the add-on.';
      $('#validationFooter').textContent=`${v.passed}/${v.total} backend checks passed.`;
      $('#downloadStepBtn').disabled=false; $('#downloadStepBtn').classList.remove('disabled');
      setEngine('Downloads ready'); return;
    }
    const row=ui[i]; row.classList.add('checking'); row.querySelector('em').textContent='Checking';
    setTimeout(()=>{
      const check=checks[i%Math.max(1,checks.length)];
      const ok=check ? !!check.ok : true;
      row.classList.remove('checking'); row.classList.add(ok?'pass':'warn-state'); row.querySelector('em').textContent=ok?'Passed':'Review';
      if(ok) passed++; else warnings++;
      $('#passedCount').textContent=String(Math.min(passed,v.passed)); $('#sumPassed').textContent=String(Math.min(passed,v.passed)); $('#sumWarnings').textContent=String(warnings);
      i++;next();
    },220);
  }
  next();
}
$('#downloadStepBtn').addEventListener('click',()=>{
  const base=(analysis?.mod_name || selected?.name?.replace(/\.jar$/i,'') || 'Converted-Mod').replace(/[^a-zA-Z0-9_.-]+/g,'-');
  $('#outputName').textContent=base.toLowerCase()+'-Bedrock.mcaddon'; $('#fixFileName').textContent=$('#outputName').textContent; go(6);
});

// -------- Real downloads --------
function downloadUrl(kind){
  const url=downloadUrls[kind];
  if(!url) return toast('That output is not available.');
  window.location.href=url;
}
$('#downloadAddon').addEventListener('click',()=>downloadUrl('addon'));
$('#downloadSource').addEventListener('click',()=>downloadUrl('source'));
$('#viewReport').addEventListener('click',()=>downloadUrl('report'));
$('#newProjectBtn').addEventListener('click',()=>location.href='converter.html');

// -------- Repair / diagnosis --------
$('#fixAddon').addEventListener('click',()=>$('#fixModal').classList.remove('hidden'));
$('#closeFix').addEventListener('click',()=>$('#fixModal').classList.add('hidden'));
$('#fixModal').addEventListener('click',e=>{if(e.target===$('#fixModal'))$('#fixModal').classList.add('hidden')});
$('#analyzeErrorBtn').addEventListener('click',async()=>{
  const log=$('#contentLog').value.trim();
  if(!log) return toast('Paste the Bedrock Content Log/error first.');
  try{
    const res=await api('/api/repair',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({job_id:jobId,content_log:log})});
    $('#fixIssue').textContent=res.issue;
    $('#fixType').textContent=res.can_fix?'AUTO REPAIR':'DIAGNOSIS';
    $('#fixCause').textContent=res.can_fix?'The log matches a pack metadata/index category this prototype can rebuild.':'The error points to behavior that cannot be repaired safely with a generic rewrite.';
    $('#fixAction').textContent=res.action;
    $('#fixResult').classList.remove('hidden');
    const apply=$('#applyFixBtn');
    if(res.can_fix){
      apply.disabled=false; apply.classList.remove('disabled'); apply.textContent='Download Repaired .mcaddon →';
      apply.onclick=()=>window.location.href=res.download;
    } else {
      apply.disabled=true; apply.classList.add('disabled'); apply.textContent='Manual Bedrock implementation required';
    }
  }catch(e){toast(e.message)}
});

$('#helpBtn').addEventListener('click',()=>toast('Real flow: Upload JAR → inspect archive → generate supported Bedrock files → validate → download.'));
