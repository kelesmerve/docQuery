let exampleData = null;
let exampleRequest = 0;
function showExample(raw) {
  $('#example-raw').setAttribute('aria-pressed', String(raw));
  $('#example-rendered').setAttribute('aria-pressed', String(!raw));
  if (raw) {
    $('#example-body').innerHTML = '<pre></pre>';
    $('#example-body pre').textContent = exampleData.content;
  } else $('#example-body').innerHTML = exampleData.html;
}
async function selectExample(id) {
  const sequence = ++exampleRequest;
  $('#example-result').hidden = true;
  document.querySelectorAll('[data-example]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.example === id)));
  try {
    const data = await api(`/api/examples/${id}`);
    if (sequence !== exampleRequest) return;
    exampleData = data;
    $('#example-title').textContent = data.title;
    $('#example-path').textContent = `Okunan dosya: ${data.path}`;
    $('#example-download').href = `/api/examples/${id}/download`;
    $('#example-warnings').replaceChildren();
    data.warnings.forEach(text => {const p=document.createElement('p');p.textContent=text;$('#example-warnings').append(p);});
    $('#example-metadata').replaceChildren();
    Object.entries(data.metadata).forEach(([key,value])=>{
      const term=document.createElement('dt'), definition=document.createElement('dd');
      term.textContent=key;definition.textContent=typeof value==='object'?JSON.stringify(value,null,2):String(value);
      $('#example-metadata').append(term,definition);
    });
    if (!Object.keys(data.metadata).length) $('#example-metadata').textContent='Bu dosyada okunabilir metadata yok.';
    $('#example-images').innerHTML=data.images.map(image=>`<button class="example-image" data-image="${image.url}"><img src="${image.url}" alt="${escapeHtml(image.name)}" loading="lazy"><span>${escapeHtml(image.name)}</span><small>${image.referenced?'Markdown referansı eşleşti':'Aynı belge adına ait dosya; metindeki konumu doğrulanmadı'}</small></button>`).join('') || '<p>İlişkili yerel görsel bulunamadı.</p>';
    showExample(false);
    $('#example-result').hidden=false;
  } catch(error) {if(sequence===exampleRequest)toast(error.message);}
}
function openExampleImage(url, alt) {
  $('#image-full').src=url;$('#image-full').alt=alt;$('#image-title').textContent=alt;
  $('#image-download').href=url;$('#image-preview').showModal();
}
$('#example-selector').onclick=event=>{const button=event.target.closest('[data-example]');if(button)selectExample(button.dataset.example);};
$('#example-images').onclick=event=>{const button=event.target.closest('[data-image]');if(button)openExampleImage(button.dataset.image,button.querySelector('img').alt);};
$('#example-body').onclick=event=>{if(event.target.tagName==='IMG')openExampleImage(event.target.src,event.target.alt);};
$('#close-image').onclick=()=>$('#image-preview').close();
$('#example-raw').onclick=()=>showExample(true);
$('#example-rendered').onclick=()=>showExample(false);
api('/api/examples').then(items=>{
  $('#example-selector').innerHTML=items.map(item=>`<button class="button secondary" data-example="${item.id}" aria-pressed="false" ${item.available?'':'disabled'}>${escapeHtml(item.title)}${item.available?'':' · Dosya bulunamadı'}</button>`).join('');
  const first=items.find(item=>item.available);if(first)selectExample(first.id);
}).catch(error=>toast(error.message));
