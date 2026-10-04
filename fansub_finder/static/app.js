const $ = (selector) => document.querySelector(selector);
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[c]));
const sourceNames = {mikan: '蜜柑', garden: 'AnimeGarden', anibt: 'AniBT', bgm: '放送资料'};
const scopeNames = {active: '当季与续播', current: '当季首播', continuing: '跨季续播', uncertain: '放送待核实', excluded: '已排除'};
const pageNames = {anime: '番剧', changes: '新增字幕组', blocked: '已屏蔽记录', unmatched: '未匹配资源', settings: '设置'};
let page = pageNames[location.hash.slice(1)] ? location.hash.slice(1) : 'anime';
let cfg, status, keyword = '', scope = 'active', hasGroups = true, viewVersion = 0, noticeTimer;

async function api(path, options = {}) {
  const response = await fetch(path, {...options, headers: {'Content-Type': 'application/json', ...options.headers}});
  const data = await response.json();
  if (!response.ok) throw Error(typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail));
  return data;
}

function notice(text) {
  clearTimeout(noticeTimer);
  $('#notice').textContent = text;
  $('#notice').hidden = false;
  noticeTimer = setTimeout(() => $('#notice').hidden = true, 5000);
}

function time(value) {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString('zh-CN', {year:'numeric', month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit', hour12:false});
}

function seasonName(value) {
  const [year, month] = value.split('-');
  return `${year} 年${({'01':'一', '04':'四', '07':'七', '10':'十'})[month]}月`;
}

function episodeText(values = []) {
  if (!values.length) return '—';
  const parts = [];
  for (let i = 0; i < values.length;) {
    let end = i;
    while (end + 1 < values.length && Number.isInteger(Number(values[end])) && Number(values[end + 1]) === Number(values[end]) + 1) end++;
    if (end - i >= 2) parts.push(`${values[i]}–${values[end]}`);
    else for (let j = i; j <= end; j++) parts.push(values[j]);
    i = end + 1;
  }
  return parts.join('、');
}

function link(url, label) {
  return /^(https?:\/\/|magnet:\?)/i.test(url || '') ? `<a class="l" href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(label)}</a>` : '';
}

function empty(label) {
  return `<div class="empty"><strong>${esc(label)}</strong></div>`;
}

function filters() {
  $('#filters').innerHTML = Object.entries(scopeNames).map(([value, label]) => `<li><a href="#anime" data-scope="${value}" class="l ${scope === value && page === 'anime' ? 'focus' : ''}" ${scope === value && page === 'anime' ? 'aria-current="true"' : ''}>${label}</a></li>`).join('');
  $('#filters').querySelectorAll('[data-scope]').forEach(a => a.onclick = event => {
    event.preventDefault();
    scope = a.dataset.scope;
    if (page === 'anime') { filters(); animePage().catch(showError); }
    else navigate('anime');
  });
}

async function health() {
  status = await api('/api/status');
  $('#quarter').textContent = seasonName(status.season);
  $('#health').innerHTML = Object.entries(status.sources).map(([source, value]) => {
    const working = ['catalog', 'backfill', 'incremental', 'metadata'].includes(value.phase);
    const label = value.error ? '失败' : working ? '采集中' : value.stale ? '过期' : '正常';
    return `<div class="health ${value.error ? 'error' : value.stale ? '' : 'ready'}" title="最后成功：${esc(time(value.last_success))}"><b>${sourceNames[source] || esc(source)}</b><span>${label}</span>${value.error ? `<div class="source-error">${esc(value.error)}</div>` : ''}</div>`;
  }).join('');
  $('#progress').textContent = status.progress.running ? status.progress.message : `更新于 ${time(status.last_scan)}`;
  $('#scan').setAttribute('aria-disabled', String(status.progress.running));
  $('#scan').textContent = status.progress.running ? '采集中' : '立即采集';
}

function description(r) {
  if (!r.description) return '';
  return `<details class="release-description"><summary>发布说明</summary><div class="description-meta">${r.description_checked_at ? esc(time(r.description_checked_at)) : '资源摘要'} ${link(r.description_url, '原页')}</div><pre>${esc(r.description)}</pre></details>`;
}

function resource(r) {
  return `<div class="resource"><div class="resource-title">${esc(r.title)}</div><div class="meta">${esc((r.languages || []).join(' / ') || '语言未标注')} / ${esc(r.resolution || '画质未标注')} / ${esc(time(r.published_at))}</div>${r.reasons?.length ? `<div class="reason">${esc(r.reasons.join('；'))}</div>` : ''}<div class="links">${(r.origins || []).map(o => link(o.url, sourceNames[o.source] || o.source)).join('')}${link(r.magnet, '磁力')}${link(r.torrent, '种子')}${r.magnet ? `<a href="#copy" role="button" class="chiiBtn copy" data-copy="${esc(r.magnet)}">复制磁力</a>` : ''}</div>${description(r)}</div>`;
}

async function animePage() {
  const version = ++viewVersion;
  const data = await api('/api/anime?' + new URLSearchParams({keyword, scope, has_groups: hasGroups}));
  if (version !== viewVersion || page !== 'anime') return;
  $('#page-title').textContent = '番剧';
  $('#content').innerHTML = `<div id="browserTools" class="clearit"><span>${data.items.length} 部 / ${scopeNames[scope]}</span><label><input type="checkbox" id="has-groups" ${hasGroups ? 'checked' : ''}>有可用组</label></div>` + (data.items.length ? `<ul id="browserItemList" class="browserFull finder-list">${data.items.map((a, i) => `<li class="item ${i % 2 ? 'even' : 'odd'} clearit"><div class="inner"><details class="anime" data-anime="${esc(a.id)}"><summary><h3 class="anime-title">${esc(a.title)}</h3><p class="info tip">${esc(a.premiere || '首播待核实')} / ${scopeNames[a.scope]}${a.total_episodes ? ' / ' + a.total_episodes + ' 话' : ''}</p><p class="group-preview">${esc(a.groups.map(g => g.name).join(' / ') || '暂无可用组')}</p><span class="group-count"><strong>${a.group_count}</strong>组</span></summary><div class="detail"></div></details></div></li>`).join('')}</ul>` : empty('没有符合条件的番剧'));
  $('#has-groups').onchange = event => { hasGroups = event.target.checked; animePage().catch(showError); };
  $('#content').querySelectorAll('[data-anime]').forEach(el => el.addEventListener('toggle', async () => {
    if (!el.open || el.dataset.loaded) return;
    el.dataset.loaded = '1';
    const id = el.dataset.anime;
    const area = el.querySelector('.detail');
    const anime = data.items.find(a => a.id === id);
    try {
      const groups = await api(`/api/anime/${encodeURIComponent(id)}/groups`);
      area.innerHTML = groups.items.map(g => `<details class="group" data-group="${esc(g.id)}"><summary><b>${esc(g.name)}</b><span class="tip">${g.release_count} 条</span></summary><p class="episodes">集数：${esc(episodeText(g.episodes))}</p><div class="links">${g.rss.map(url => link(url, 'RSS')).join('')}</div><div class="resources"></div></details>`).join('') + `<details class="scope-editor"><summary>放送归属</summary><div class="scope-controls"><select class="override" aria-label="放送归属">${[['', '自动'], ['current', '当季'], ['continuing', '续播'], ['excluded', '排除'], ['uncertain', '待核实']].map(([value, name]) => `<option value="${value}" ${(anime.override || '') === value ? 'selected' : ''}>${name}</option>`).join('')}</select><a class="chiiBtn save-override" href="#apply" role="button">应用</a>${anime.bgm_id ? link(`https://bgm.tv/subject/${anime.bgm_id}`, 'Bangumi') : ''}</div></details>`;
      area.querySelector('.save-override').onclick = async event => {
        event.preventDefault();
        try {
          await api(`/api/anime/${encodeURIComponent(id)}/scope`, {method: 'PUT', body: JSON.stringify({value: area.querySelector('.override').value || null})});
          notice('已保存');
          await animePage();
        } catch (error) { notice(error.message); }
      };
      area.querySelectorAll('[data-group]').forEach(g => g.addEventListener('toggle', async () => {
        if (!g.open || g.dataset.loaded) return;
        g.dataset.loaded = '1';
        const target = g.querySelector('.resources');
        try {
          const releases = await api(`/api/anime/${encodeURIComponent(id)}/releases?group=${encodeURIComponent(g.dataset.group)}`);
          target.innerHTML = releases.items.map(resource).join('');
        } catch (error) { target.textContent = error.message; g.dataset.loaded = ''; }
      }));
    } catch (error) { area.textContent = error.message; el.dataset.loaded = ''; }
  }));
}

async function changesPage() {
  const version = ++viewVersion;
  $('#page-title').textContent = '新增字幕组';
  $('#content').innerHTML = '<ul id="change-items" class="browserFull finder-list"></ul><a href="#more" class="chiiBtn" id="more-changes" role="button" hidden>更多</a>';
  let cursor = 0, count = 0, loading = false;
  async function load() {
    if (loading) return;
    loading = true;
    try {
      const data = await api('/api/changes?after=' + cursor);
      if (version !== viewVersion || page !== 'changes') return;
      cursor = data.cursor;
      $('#change-items').insertAdjacentHTML('beforeend', data.items.map((c, i) => `<li class="item ${(count + i) % 2 ? 'even' : 'odd'} clearit"><div class="inner"><h3 class="anime-title">${esc(c.anime_title)} <small class="grey">${esc(c.group_name)}</small></h3><p class="info tip">${esc(time(c.discovered_at))} / 集数 ${esc(episodeText(c.episodes))}</p></div></li>`).join(''));
      count += data.items.length;
      $('#more-changes').hidden = !data.has_more;
      if (!count && !data.has_more) $('#change-items').innerHTML = empty('暂无新增组');
    } catch (error) { notice(error.message); }
    finally { loading = false; }
  }
  $('#more-changes').onclick = event => { event.preventDefault(); load(); };
  await load();
}

async function recordsPage(blocked) {
  const version = ++viewVersion;
  const data = await api(blocked ? '/api/blocked' : '/api/unmatched');
  if (version !== viewVersion || page !== (blocked ? 'blocked' : 'unmatched')) return;
  $('#page-title').textContent = blocked ? '已屏蔽记录' : '未匹配资源';
  $('#content').innerHTML = `<div id="browserTools" class="clearit"><span>${data.total} 条${data.total > data.items.length ? ' / 当前展示 ' + data.items.length : ''}</span></div>` + (data.items.length ? data.items.map(resource).join('') : empty('暂无记录'));
}

async function settingsPage() {
  const version = ++viewVersion;
  const data = await api('/api/config');
  if (version !== viewVersion || page !== 'settings') return;
  cfg = data;
  $('#page-title').textContent = '设置';
  const field = (id, label, control) => `<div class="field"><label for="${id}">${label}</label>${control}</div>`;
  const listField = (id, label, values) => field(id, label, `<textarea id="${id}" class="quick" spellcheck="false">${esc(values.join('\n'))}</textarea>`);
  $('#content').innerHTML = `<div class="settings"><form id="settings-form"><h2 class="subtitle">采集</h2>${field('season', '季度', `<input id="season" class="inputtext" value="${esc(cfg.season)}" pattern="[0-9]{4}-(01|04|07|10)" required>`)}${field('proxy', '代理', `<input id="proxy" class="inputtext" value="${esc(cfg.proxy)}" placeholder="留空直连">`)}${field('poll', '采集间隔 / 分钟', `<input id="poll" class="inputtext" type="number" min="5" max="1440" value="${cfg.poll_minutes}">`)}${field('catalog', '目录刷新 / 小时', `<input id="catalog" class="inputtext" type="number" min="1" max="168" value="${cfg.catalog_hours}">`)}<h2 class="subtitle">筛选 <small class="field-hint tip">每行一个名称</small></h2>${listField('groups', '组黑名单', cfg.groups)}${listField('review-groups', '待核实发布者', cfg.review_groups || [])}${listField('platforms', '平台标签', cfg.platforms)}<div class="settings-actions"><a href="#save" id="save-settings" class="chiiBtn" role="button">保存设置</a><a href="#backfill" id="full-scan" class="chiiBtn" role="button">完整补查</a></div></form><h2 class="subtitle">采集状态</h2>${Object.entries(status.sources).map(([source, value]) => `<div class="status-detail"><b>${sourceNames[source] || esc(source)}</b><div><span class="${value.error ? 'status-error' : 'status-ok'}">${esc(value.error || (!value.baseline_complete ? '首次采集中' : value.stale ? '数据过期' : '正常'))}</span><p class="tip">最后成功 ${esc(time(value.last_success))}</p></div></div>`).join('')}<h2 class="subtitle">MCP</h2><div class="connection"><input id="mcp-url" class="inputtext" value="${esc(location.origin)}/mcp" readonly aria-label="MCP 地址"><a href="#copy" role="button" class="chiiBtn copy" data-copy="${esc(location.origin)}/mcp">复制</a></div></div>`;
  $('#save-settings').onclick = event => { event.preventDefault(); $('#settings-form').requestSubmit(); };
  $('#settings-form').onsubmit = async event => {
    event.preventDefault();
    const save = $('#save-settings');
    if (save.getAttribute('aria-disabled') === 'true') return;
    save.setAttribute('aria-disabled', 'true');
    const lines = selector => $(selector).value.split('\n').map(s => s.trim()).filter(Boolean);
    try {
      await api('/api/config', {method: 'PUT', body: JSON.stringify({...cfg, season: $('#season').value, proxy: $('#proxy').value, poll_minutes: Number($('#poll').value), catalog_hours: Number($('#catalog').value), groups: lines('#groups'), review_groups: lines('#review-groups'), platforms: lines('#platforms')})});
      cfg = await api('/api/config');
      notice('已保存');
      await health();
    } catch (error) { notice(error.message); }
    finally { save.setAttribute('aria-disabled', 'false'); }
  };
  $('#full-scan').onclick = event => { event.preventDefault(); startScan(true); };
}

function showError(error) {
  notice(error.message);
  $('#content').setAttribute('aria-busy', 'false');
}

async function render() {
  const expectedPage = page;
  $('#content').setAttribute('aria-busy', 'true');
  try {
    await health();
    if (page !== expectedPage) return;
    if (page === 'anime') await animePage();
    else if (page === 'changes') await changesPage();
    else if (page === 'settings') await settingsPage();
    else await recordsPage(page === 'blocked');
  } catch (error) { showError(error); }
  finally { if (page === expectedPage) $('#content').setAttribute('aria-busy', 'false'); }
}

function navigate(next) {
  page = next;
  viewVersion++;
  document.querySelectorAll('nav [data-page]').forEach(a => {
    const active = a.dataset.page === page;
    a.classList.toggle('selected', active);
    a.classList.toggle('focus', active);
    a.classList.toggle('top', !active);
    if (active) a.setAttribute('aria-current', 'page');
    else a.removeAttribute('aria-current');
  });
  history.replaceState(null, '', '#' + page);
  filters();
  render();
}

async function startScan(full = false) {
  if (status?.progress.running) return;
  try {
    const data = await api('/api/scan?full=' + full, {method: 'POST'});
    if (!data.started) notice('采集正在进行');
    await health();
  } catch (error) { notice(error.message); }
}

document.querySelectorAll('nav [data-page]').forEach(a => a.onclick = event => { event.preventDefault(); navigate(a.dataset.page); });
$('.finder-logo').onclick = event => { event.preventDefault(); navigate('anime'); };
$('#edit-season').onclick = event => { event.preventDefault(); navigate('settings'); };
$('#scan').onclick = event => { event.preventDefault(); startScan(); };
$('#search-form').onsubmit = event => { event.preventDefault(); keyword = $('#search_text').value.trim(); if (page === 'anime') animePage().catch(showError); else navigate('anime'); };
document.addEventListener('click', async event => {
  const button = event.target.closest('.copy');
  if (!button) return;
  event.preventDefault();
  try { await navigator.clipboard.writeText(button.dataset.copy); notice('已复制'); }
  catch { notice('复制失败，可直接打开链接'); }
});
document.addEventListener('keydown', event => {
  if (event.key === ' ' && event.target.matches('a[role=button]')) { event.preventDefault(); event.target.click(); }
});
navigate(page);
setInterval(async () => {
  try {
    const wasRunning = status?.progress.running;
    await health();
    if ((wasRunning || status.progress.running) && page === 'anime' && !document.querySelector('details[open]') && document.activeElement?.id !== 'search_text') await animePage();
  } catch (error) { notice('服务连接失败：' + error.message); }
}, 8000);
