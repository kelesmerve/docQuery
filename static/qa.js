$('#ask-form').onsubmit=async event=>{
  event.preventDefault();
  $('#ask-button').disabled=true;
  $('#answer').textContent='Qdrant kaynakları aranıyor ve model yanıtı bekleniyor…';
  $('#sources').replaceChildren();
  try {
    const result=await api('/api/ask', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question:$('#question').value})});
    $('#answer').textContent=result.answer;
    for(const source of result.sources){
      const card=document.createElement('section');card.className='source';
      card.innerHTML=`<strong>[${source.id}] ${escapeHtml(source.title)}</strong><small>${escapeHtml(source.source)} · Parça ${source.chunk+1} · Benzerlik ${source.score.toFixed(3)}</small><p>${escapeHtml(source.text)}</p>`;
      $('#sources').append(card);
    }
    if(!result.sources.length)$('#sources').textContent='Bu soruyu destekleyen indekslenmiş kaynak bulunamadı.';
  }catch(error){$('#answer').textContent=error.message;$('#sources').textContent='Yanıt üretilemedi; kaynak gösterilemiyor.';}
  finally{$('#ask-button').disabled=false;}
};
function routeView(){if(!['#answers','#documents'].includes(location.hash))return;document.querySelector(`[data-view="${location.hash.slice(1)}"]`).click();}
document.querySelectorAll('[data-view]').forEach(button=>button.addEventListener('click',()=>history.replaceState(null,'',`#${button.dataset.view}`)));
window.addEventListener('hashchange',routeView);
routeView();
