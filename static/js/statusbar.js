;(function(){
  const bar = document.getElementById('app-status-bar');
  const buffer = [];
  const MAX_ITEMS = 50;
  function ensureVisible(){ if(bar.classList.contains('hidden')) bar.classList.remove('hidden'); }
  function compact(obj){
    try { return JSON.stringify(obj); } catch { return String(obj); }
  }
  function push(entry){
    buffer.push(entry);
    if(buffer.length > MAX_ITEMS) buffer.shift();
  }
  function render(entry){
    ensureVisible();
    bar.innerHTML = '<span class="font-semibold">状态</span>: ' + compact(entry);
  }
  window.AppStatusBar = {
    update(entry){ push(entry); render(entry); },
    show(){ ensureVisible(); },
    hide(){ bar.classList.add('hidden'); },
    setLevel(level){
      bar.classList.remove('bg-red-800','bg-yellow-800','bg-gray-800');
      if(level==='error') bar.classList.add('bg-red-800');
      else if(level==='warn') bar.classList.add('bg-yellow-800');
      else bar.classList.add('bg-gray-800');
    },
    items(){ return buffer.slice(); }
  };
})();

