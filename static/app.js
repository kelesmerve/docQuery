const $ = s => document.querySelector(s);
const labels = {ready:'Yüklemeye hazır',queued:'Sırada',running:'İşleniyor',approved:'Onaylı',review:'İnceleme gerekli',error:'İşlem başarısız'};
let currentJobs = [], selectedJob = null, previewData = null, raw = false;
const escapeHtml = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function api(path, options={}) {
  const response = await fetch(path, {...options, headers:{'X-CSRF-Token':$('meta[name="csrf"]').content,...options.headers}});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'İstek tamamlanamadı.');
  return data;
}
function toast(text) { $('#toast').textContent = text; $('#toast').hidden = false; clearTimeout(toast.timer); toast.timer = setTimeout(()=>$('#toast').hidden=true,8000); }
document.querySelectorAll('[data-view]').forEach(button => button.onclick = () => {
  document.querySelectorAll('[data-view]').forEach(b=>b.classList.toggle('active',b===button));
  $('#documents-view').hidden = button.dataset.view !== 'documents';
  $('#answers-view').hidden = button.dataset.view !== 'answers';
  $('#breadcrumb').textContent = button.dataset.view === 'documents' ? 'Belge stüdyosu' : 'Bilgiye sor';
});
function fileLabel() { $('#file-label').textContent = $('#document').files[0]?.name || 'Belgeni buraya sürükle'; }
$('#document').onchange = fileLabel;
$('#images').onchange = () => { $('#image-label').textContent = Array.from($('#images').files).map(f=>f.name).join(' · ') || 'Görsel dosya adları belgedeki referanslarla eşleşmeli.'; };
['dragenter','dragover'].forEach(event=>$('#dropzone').addEventListener(event,()=>$('#dropzone').classList.add('drag')));
['dragleave','drop'].forEach(event=>$('#dropzone').addEventListener(event,()=>$('#dropzone').classList.remove('drag')));
$('#upload-form').onsubmit = async event => {
  event.preventDefault(); const button = $('#upload-button'); button.disabled = true;
  try { const data = await api('/api/jobs',{method:'POST',body:new FormData(event.target)}); selectedJob=data.id; event.target.reset(); fileLabel(); $('#image-label').textContent='Görsel dosya adları belgedeki referanslarla eşleşmeli.'; await refreshJobs(); toast('Belge yüklendi. Hazır olduğunda işlemi başlat.'); }
  catch(error) { toast(error.message); } finally {button.disabled=false;}
};
async function refreshJobs() {
  currentJobs = await api('/api/jobs');
  $('#stat-total').textContent = $('#nav-count').textContent = $('#library-count').textContent = currentJobs.length;
  $('#stat-approved').textContent = currentJobs.filter(j=>j.status==='approved').length;
  $('#stat-review').textContent = currentJobs.filter(j=>j.status==='review').length;
  $('#document-list').innerHTML = currentJobs.length ? currentJobs.map(job=>`<div class="document-row"><span class="document-icon">▤</span><div class="document-info"><strong>${escapeHtml(job.name)}</strong><small>${new Date(job.created).toLocaleString('tr-TR')}</small>${job.error?`<div class="job-error">${escapeHtml(job.error)}</div>`:''}</div><span class="status-badge ${job.status}">${labels[job.status]}</span>${['ready','error'].includes(job.status)?`<button class="button secondary" data-start="${job.id}">${job.status==='error'?'Yeniden dene':'İşlemi başlat'} →</button>`:['approved','review'].includes(job.status)?`<button class="button secondary" data-preview="${job.id}">İncele ↗</button>`:`<button class="button secondary" data-track="${job.id}">Takip et</button>`}</div>`).join('') : '<div class="empty"><span>▤</span><strong>Yeni bilgiler için yer açtık.</strong><p>Henüz belge yüklenmedi. İlk belgeni ekleyerek başlayabilirsin.</p></div>';
  const job=currentJobs.find(j=>j.id===selectedJob) || currentJobs.find(j=>['running','queued'].includes(j.status));
  $('#pipeline-status').textContent=job?labels[job.status]:'Hazır';
  document.querySelectorAll('[data-step]').forEach(item=>item.classList.toggle('done',!!job?.steps.includes(item.dataset.step)));
}
$('#document-list').onclick=async event=>{
  const button=event.target.closest('button'); if(!button)return;
  if(button.dataset.track){selectedJob=button.dataset.track;await refreshJobs();$('#pipeline').scrollIntoView({behavior:'smooth',block:'center'});return;}
  if(button.dataset.start){button.disabled=true;try{selectedJob=button.dataset.start;await api(`/api/jobs/${selectedJob}/start`,{method:'POST'});await refreshJobs();}catch(error){toast(error.message);button.disabled=false;}}
  if(button.dataset.preview){try{previewData=await api(`/api/jobs/${button.dataset.preview}`);selectedJob=previewData.id;raw=false;$('#preview-title').textContent=previewData.name;$('#quality').replaceChildren();const issues=previewData.issues.length?previewData.issues:['Kalite kontrolleri geçti. Belge indekslemeye hazır.'];issues.forEach(issue=>{const p=document.createElement('p');p.textContent=issue;$('#quality').append(p);});$('#download').href=`/api/jobs/${previewData.id}/download`;renderPreview();$('#preview').showModal();}catch(error){toast(error.message);}}
};
function renderPreview(){ $('#toggle-raw').textContent=raw?'Biçimlendirilmiş görünüm':'Markdown kaynağı'; if(raw){$('#preview-content').innerHTML='<pre></pre>';$('#preview-content pre').textContent=previewData.content;}else{$('#preview-content').innerHTML=previewData.html;} }
$('#toggle-raw').onclick=()=>{raw=!raw;renderPreview();};
$('#close-preview').onclick=()=>$('#preview').close();
async function refreshServices(){const result=await api('/api/services'); const names={model:'Görsel / yanıt modeli',qdrant:'Qdrant',embedding:'Embedding'};$('#services').innerHTML=Object.entries(result).map(([key,value])=>`<span class="service ${value==='online'?'':'offline'}">${value==='online'?'●':'○'} ${names[key]} · ${value==='online'?'Erişilebilir':value==='unconfigured'?'Ayarlanmamış':'Ulaşılamıyor'}</span>`).join('');}
async function refreshIndex(){const data=await api('/api/index');$('#index-button').disabled=data.status==='running';$('#index-status').textContent=data.status==='running'?'İndeksleme sürüyor. Embedding vektörleri Qdrant’a aktarılıyor…':data.status==='done'?`${data.chunks} kaynak parçası indekslendi. Bilgiye sor ekranını kullanabilirsin.`:data.status==='error'?data.error:'Soru sormadan önce onaylı belgelerini indeksle.';}
$('#index-button').onclick=async()=>{try{await api('/api/index',{method:'POST'});await refreshIndex();}catch(error){toast(error.message);}};
$('#refresh').onclick=async()=>{try{await Promise.all([refreshJobs(),refreshServices(),refreshIndex()]);toast('Durum güncellendi.');}catch(error){toast(error.message);}};
Promise.all([refreshJobs(),refreshServices(),refreshIndex()]).catch(error=>toast(error.message));
setInterval(()=>Promise.all([refreshJobs(),refreshIndex()]).catch(()=>{}),2500);
