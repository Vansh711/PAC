const $ = s => document.querySelector(s);
const imageInput = $('#imageInput'), preview = $('#preview'), uploadEmpty = $('#uploadEmpty'), removeImage = $('#removeImage'), analyzeBtn = $('#analyzeBtn'), result = $('#result'), toast = $('#toast');
let uploadedFile;
function notice(message){ toast.textContent = message; toast.classList.add('show'); setTimeout(()=>toast.classList.remove('show'), 2600); }
function showImage(file){
  if(!file || !file.type.startsWith('image/')) return notice('Please choose a crop photo.');
  if(file.size > 8e6) return notice('Please choose an image under 8 MB.');
  uploadedFile=file; preview.src=URL.createObjectURL(file); preview.style.display='block'; uploadEmpty.style.display='none'; removeImage.style.display='block'; analyzeBtn.disabled=false; result.hidden=true;
}
imageInput.addEventListener('change', e=>showImage(e.target.files[0]));
$('#dropzone').addEventListener('dragover', e=>{e.preventDefault(); $('#dropzone').style.borderColor='#19382d'});
$('#dropzone').addEventListener('dragleave', ()=>$('#dropzone').style.borderColor='');
$('#dropzone').addEventListener('drop', e=>{e.preventDefault(); showImage(e.dataTransfer.files[0]);});
removeImage.addEventListener('click', e=>{e.preventDefault(); uploadedFile=null; imageInput.value=''; preview.style.display='none'; uploadEmpty.style.display='flex'; removeImage.style.display='none'; analyzeBtn.disabled=true; result.hidden=true;});
function esc(value){return String(value||'').replace(/[&<>"]/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}
function renderAnalysis(data){
  const list = (items=[])=>items.map(i=>`<li>${esc(i)}</li>`).join('');
  result.innerHTML=`<div class="result-top"><div><div class="eyebrow">SCAN RESULT · ${Math.round((data.confidence||0)*100)}% CONFIDENCE</div><h3>${esc(data.plant)}</h3><div class="status">● ${esc(data.status)} · ${esc(data.category)}</div></div><div class="score">${esc(data.health_score)}<small>/100<br>health</small></div></div>${data.demo?'<p class="demo-note">Demo assessment shown. Add your Gemini key to enable live image analysis.</p>':''}<div class="result-grid"><div><h4>WHAT WE CAN SEE</h4><ul>${list(data.observations)}</ul><h4 style="margin-top:16px">CROP CARE</h4><p>${esc(data.care)}</p></div><div><h4>YOUR NEXT 3 STEPS</h4><ol>${list(data.actions)}</ol><p class="privacy">${esc(data.disclaimer||'')}</p></div></div>`;
  result.hidden=false; result.scrollIntoView({behavior:'smooth', block:'nearest'});
}
analyzeBtn.addEventListener('click', async()=>{
  if(!uploadedFile)return; analyzeBtn.innerHTML='Checking leaf details…'; analyzeBtn.disabled=true;
  try { const fd=new FormData();fd.append('image',uploadedFile);const r=await fetch('/api/analyze',{method:'POST',body:fd}); if(!r.ok)throw Error();renderAnalysis(await r.json()); }
  catch{notice('We could not analyse this photo. Please try again.');}
  finally{analyzeBtn.innerHTML='Analyse crop <span>→</span>';analyzeBtn.disabled=false;}
});
const messages=$('#messages'), question=$('#question'), chatForm=$('#chatForm'), lang=$('#assistantLanguage'), micBtn=$('#micBtn');
function addMessage(text, who='saathi'){const el=document.createElement('div');el.className=`bubble ${who}`;el.textContent=text;messages.append(el);messages.scrollTop=messages.scrollHeight;return el;}
async function ask(text){
  if(!text.trim())return;addMessage(text,'user');question.value='';const wait=addMessage('One moment…');
  try{const r=await fetch('/api/ask',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question:text,language:lang.value})});const data=await r.json();wait.remove();addMessage(data.answer);speak(data.answer);}
  catch{wait.textContent='I could not connect. Please try again.';}
}
chatForm.addEventListener('submit',e=>{e.preventDefault();ask(question.value)});document.querySelectorAll('.quick-asks button').forEach(b=>b.addEventListener('click',()=>ask(b.textContent)));
const speechLang={English:'en-IN',Hindi:'hi-IN',Bengali:'bn-IN',Tamil:'ta-IN',Telugu:'te-IN',Marathi:'mr-IN',Punjabi:'pa-IN'};
function speak(text){if(!('speechSynthesis'in window))return;speechSynthesis.cancel();const u=new SpeechSynthesisUtterance(text);u.lang=speechLang[lang.value]||'en-IN';u.rate=.92;speechSynthesis.speak(u);}
micBtn.addEventListener('click',()=>{
  const Recognition=window.SpeechRecognition||window.webkitSpeechRecognition;if(!Recognition)return notice('Voice input works best in Chrome on a mobile or desktop browser.');
  const rec=new Recognition();rec.lang=speechLang[lang.value]||'en-IN';rec.interimResults=false;micBtn.classList.add('listening');rec.start();rec.onresult=e=>{question.value=e.results[0][0].transcript;ask(question.value)};rec.onerror=()=>notice('I could not hear that. Please try again.');rec.onend=()=>micBtn.classList.remove('listening');
});
$('#hearBtn').addEventListener('click',()=>speak('Take a clear picture of your crop. KhetSaathi identifies the plant, checks visible health signs, and suggests what to do next.'));
$('#languageBtn').addEventListener('click',()=>{lang.focus();notice('Choose your assistant language below.');document.querySelector('#assistant').scrollIntoView({behavior:'smooth'});});
