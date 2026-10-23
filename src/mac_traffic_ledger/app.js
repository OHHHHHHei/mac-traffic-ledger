'use strict';
const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let view = 'overview', selected = '', page = 0, generation = 0, request = null, paginationEnd = null;
let theme = 'system';
try { theme = localStorage.getItem('ledger-theme') || 'system'; } catch (_) {}
function applyTheme() {
  if (theme === 'system') delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = theme;
  $('theme').textContent = '主题：' + ({system:'系统',light:'浅色',dark:'深色'}[theme] || '系统');
}
applyTheme();
$('theme').onclick = () => {theme = ({system:'light',light:'dark',dark:'system'})[theme] || 'system';try {localStorage.setItem('ledger-theme', theme);} catch (_) {}applyTheme();};
function bytes(n) {
  n = Number(n) || 0; const units = ['B','KiB','MiB','GiB','TiB']; let i = 0;
  while (n >= 1024 && i < 4) {n /= 1024;i++;}
  return n.toFixed(i ? 2 : 0) + ' ' + units[i];
}
function date(n) {return new Date(n * 1000).toLocaleString('zh-CN', {hour12:false});}
function shortDate(n) {return new Date(n * 1000).toLocaleString('zh-CN',{month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit',hour12:false});}
function params() {
  const now = new Date(); let start = new Date(now), end = now, r = $('range').value;
  if (r === 'today') start.setHours(0,0,0,0);
  else if (r === 'month') {start.setDate(1);start.setHours(0,0,0,0);}
  else if (r === 'hour') start = new Date(+now - 3600000);
  else if (r === 'custom') {start = new Date($('from').value + 'T00:00:00');end = new Date($('to').value + 'T23:59:59');}
  else start = new Date(+now - Number(r) * 86400000);
  if (!Number.isFinite(+start) || !Number.isFinite(+end) || start > end) throw Error('请选择有效的起止日期。');
  if (view === 'connections') {
    if (paginationEnd === null) paginationEnd = +end / 1000;
    end = new Date(paginationEnd * 1000);
  }
  return new URLSearchParams({start:+start/1000,end:+end/1000,route:$('route').value,search:$('search').value,view,page,...(selected ? {process:selected} : {})});
}
function table(headers, rows) {
  return rows.length ? '<table><thead><tr>' + headers.map(x=>'<th>'+x+'</th>').join('') + '</tr></thead><tbody>' + rows.join('') + '</tbody></table>' : '<p class="empty">这个范围暂无记录。试试其他日期或筛选条件。</p>';
}
function cells(values) {return '<tr>'+values.map(v=>'<td>'+v+'</td>').join('')+'</tr>';}
function updateState(d) {
  const s = d.status, live = s.state === 'recording' && Date.now()/1000 - s.last_success < 15;
  $('status').textContent = live ? '安静记录中' : '采集暂不可用';
  $('status').className = 'status' + (live ? '' : ' warning');
  $('saved').textContent = s.last_committed ? '最近保存 '+shortDate(s.last_committed)+' · 每秒采样' : '每秒采样 · 最多 10 秒保存一次';
  if (d.meta) $('scope').textContent = '自 '+date(Number(d.meta.created))+' 开始 · 明细 30 天 / 每日汇总长期保留';
  if (s.error) {$('error').textContent = '采集器：'+s.error;$('error').classList.remove('hidden');}
}
function setView(next) {
  view = next;page = 0;paginationEnd = null;
  if (view === 'daily') selected = '';
  document.querySelectorAll('[data-view]').forEach(b=>b.setAttribute('aria-current', b.dataset.view === view ? 'page' : 'false'));
  $('overview').classList.toggle('hidden', view !== 'overview');
  $('connectionView').classList.toggle('hidden', view !== 'connections');
  $('dailyView').classList.toggle('hidden', view !== 'daily');
  $('export').classList.toggle('hidden', view === 'overview');
  $('export').textContent = view === 'daily' ? '导出筛选账单 CSV' : '导出本页 CSV';
  $('search').placeholder = view === 'daily' ? '搜索进程名称或路径…' : '搜索进程、域名或 IP…';
  updateSelection();refresh();
}
function updateSelection() {
  $('filter').classList.toggle('hidden', !selected);
  $('selectedName').textContent = selected ? '进程 / '+JSON.parse(selected)[0] : '';
}
function renderOverview(d) {
  const s = d.summary;
  $('total').textContent = bytes(s.up+s.down);$('up').textContent = bytes(s.up);$('down').textContent = bytes(s.down);
  $('processCount').textContent = d.processes.length+' 个进程';
  const max = Math.max(1,...d.processes.map(r=>r.up+r.down));
  $('processes').innerHTML = d.processes.length ? d.processes.map((r,i)=>{
    const match = r.path.match(/\/([^/]+)\.app\//), app = match ? match[1] : r.process;
    return '<button class="process-row" data-process="'+i+'" aria-label="查看 '+esc(r.process)+' 的流量"><span class="app-icon" aria-hidden="true">'+esc(app.slice(0,1).toUpperCase())+'</span><span><span class="process-name">'+esc(app)+'</span><span class="process-sub" title="'+esc(r.path)+'">'+esc(r.process)+' · '+r.connections+' 条连接</span><span class="mini-bar"><i style="width:'+((r.up+r.down)/max*100)+'%"></i></span></span><span class="process-value">'+bytes(r.up+r.down)+'<span class="process-sub">↑ '+bytes(r.up)+' / ↓ '+bytes(r.down)+'</span></span></button>';
  }).join('') : '<p class="empty">等待新的网络活动。已有记录不会因关闭网页而消失。</p>';
  $('processes').querySelectorAll('[data-process]').forEach(b=>b.onclick=()=>{
    const r=d.processes[Number(b.dataset.process)];selected=JSON.stringify([r.process,r.path]);updateSelection();refresh();
  });
  $('hosts').innerHTML = table(['访问目标 / 出口','上传','下载'], d.hosts.map(r=>'<tr><td class="domain">'+esc(r.host)+'<span class="path" title="'+esc(r.node)+'">'+esc(r.route)+' · '+esc(r.node)+'</span></td><td class="num">'+bytes(r.up)+'</td><td class="num">'+bytes(r.down)+'</td></tr>'));
  // Keep chronological spacing even when no connections transferred data in a bucket.
  const points = new Map(d.trend.map(r=>[r.bucket,r]));
  const first = Math.floor(d.range[0]/d.trend_step)*d.trend_step, last = Math.min(d.range[1],Date.now()/1000);
  const bins=[];for(let bucket=first;bucket<last&&bins.length<122;bucket+=d.trend_step) bins.push(points.get(bucket)||{bucket,up:0,down:0});
  const peak=Math.max(1,...bins.map(r=>r.up+r.down));
  $('chart').innerHTML=bins.map(r=>'<span title="'+shortDate(r.bucket)+' · ↑ '+bytes(r.up)+' / ↓ '+bytes(r.down)+'" style="height:'+(r.up+r.down ? Math.max(2,(r.up+r.down)/peak*100):1)+'%;opacity:'+(r.up+r.down?'.8':'.12')+'"></span>').join('');
  $('trendUnit').textContent='每 '+Math.round(d.trend_step/60)+' 分钟合计 · 悬停查看';
  $('chartStart').textContent=shortDate(d.range[0]);$('chartEnd').textContent=shortDate(Math.min(d.range[1],Date.now()/1000));
  $('quality').textContent=(s.up+s.down ? ((1-s.unknown/(s.up+s.down))*100).toFixed(2)+'% 已识别':'尚无流量')+' · 未知 '+bytes(s.unknown);
  $('health').textContent='全部路由计数增量 '+bytes(d.health.core)+'；逐次未归属差额估计 '+bytes(d.health.missed)+'；超过 5 秒的采样间隔 '+d.health.gaps+' 次。';
}
function renderConnections(d) {
  $('connectionCount').textContent=d.count+' 条记录';
  $('connections').innerHTML=table(['进程 / PID','目标','路由 / 节点','上传','下载','连接详情'],d.connections.map(r=>{
    const facts=[['完整路径',r.path||'未识别'],['识别方式',r.attribution],['协议',r.network],['源地址',r.source+':'+r.sport],['目标 IP',r.ip],['规则',r.rule],['代理链',r.chain],['连接开始',r.started],['首次观察',date(r.first_seen)],['最后观察',date(r.last_seen)],['状态',r.active?'最后快照中活跃':'已结束或暂未观察到'],['连接 ID',r.id]];
    return cells([esc(r.process)+'<span class="path">PID '+r.pid+'</span>', '<span class="domain">'+esc(r.host||r.ip)+':'+esc(r.dport)+'</span>',esc(r.route)+'<span class="path" title="'+esc(r.node)+'">'+esc(r.node)+'</span>',bytes(r.up),bytes(r.down),'<details class="connection-details"><summary>详情</summary><dl>'+facts.map(([k,v])=>'<dt>'+esc(k)+'</dt><dd>'+esc(v)+'</dd>').join('')+'</dl></details>']);
  }));
  $('pageLabel').textContent='第 '+(d.page+1)+' / '+Math.max(1,Math.ceil(d.count/d.page_size))+' 页 · 每页 '+d.page_size+' 条';
  $('prev').disabled=page===0;$('next').disabled=(page+1)*d.page_size>=d.count;
}
function renderDaily(d) {
  $('dailyTotal').textContent=bytes(d.rows.reduce((s,r)=>s+r.up+r.down,0));
  $('daily').innerHTML=table(['日期','进程 / 路径','路由','上传','下载','合计'],d.rows.map(r=>cells([esc(r.day),esc(r.process)+'<span class="path" title="'+esc(r.path)+'">'+esc(r.path)+'</span>',esc(r.route),bytes(r.up),bytes(r.down),bytes(r.up+r.down)])));
}
async function refresh() {
  const ticket=++generation;if(request) request.abort();request=new AbortController();
  try {
    const response=await fetch('/api/data?'+params(),{signal:request.signal});
    if(!response.ok) throw Error('读取失败（'+response.status+'），请稍后重试。');
    const d=await response.json();if(ticket!==generation)return;
    $('error').classList.add('hidden');updateState(d);
    if(view==='overview')renderOverview(d);else if(view==='connections')renderConnections(d);else renderDaily(d);
  } catch(e) {
    if(e.name==='AbortError'||ticket!==generation)return;
    $('error').textContent=e.message;$('error').classList.remove('hidden');
  } finally {if(ticket===generation)request=null;}
}
function resetFilters() {page=0;paginationEnd=null;refresh();}
for(const id of ['range','route','from','to']) $(id).onchange=()=>{
  $('from').classList.toggle('hidden',$('range').value!=='custom');$('to').classList.toggle('hidden',$('range').value!=='custom');resetFilters();
};
let debounce;$('search').oninput=()=>{clearTimeout(debounce);debounce=setTimeout(resetFilters,250);};
$('clear').onclick=()=>{selected='';updateSelection();resetFilters();};
$('refresh').onclick=resetFilters;
$('prev').onclick=()=>{page=Math.max(0,page-1);refresh();};$('next').onclick=()=>{page++;refresh();};
$('export').onclick=()=>{try{location.href='/api/export?'+params();}catch(e){$('error').textContent=e.message;$('error').classList.remove('hidden');}};
document.querySelectorAll('[data-view]').forEach(b=>b.onclick=()=>setView(b.dataset.view));
const today=new Date();today.setMinutes(today.getMinutes()-today.getTimezoneOffset());$('from').value=$('to').value=today.toISOString().slice(0,10);
let refreshTimer=null;
function schedule() {
  clearTimeout(refreshTimer);if(document.hidden)return;
  refreshTimer=setTimeout(()=>{if(view==='overview'&&!request)refresh();schedule();},10000);
}
document.addEventListener('visibilitychange',()=>{if(!document.hidden&&view==='overview')refresh();else if(document.hidden&&request)request.abort();schedule();});
refresh();schedule();
