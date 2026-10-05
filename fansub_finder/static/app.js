const $ = (selector) => document.querySelector(selector);
const staticMode = document.querySelector('meta[name="finder-mode"]')?.content === 'static';
let publishedData, publishedPromise;
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[c]));
const sourceNames = {mikan: '蜜柑', garden: 'AnimeGarden', anibt: 'AniBT', bgm: '放送资料'};
const scopeNames = {active: '当季与续播', current: '当季首播', continuing: '跨季续播', uncertain: '放送待核实', excluded: '已排除'};
const pageNames = {anime: '番剧', changes: '近 24h 更新', blocked: '已屏蔽记录', unmatched: '未匹配资源', settings: '设置'};
let page = pageNames[location.hash.slice(1)] ? location.hash.slice(1) : 'anime';
let cfg, status, keyword = '', scope = 'active', hasGroups = true, viewVersion = 0, noticeTimer;
let updatesRefreshedAt = 0;

async function api(path, options = {}) {
  if (staticMode) return staticApi(path, options);
  const response = await fetch(path, {...options, headers: {'Content-Type': 'application/json', ...options.headers}});
  const data = await response.json();
  if (!response.ok) throw Error(typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail));
  return data;
}

async function staticApi(path, options) {
  if (options.method && options.method !== 'GET') throw Error('只读网页');
  if (!publishedPromise) publishedPromise = fetch(new URL('data.json', location.href), {cache: 'no-cache'}).then(async response => {
    if (!response.ok) throw Error('网页数据加载失败');
    publishedData = await response.json();
    return publishedData;
  }).catch(error => { publishedPromise = null; throw error; });
  const data = await publishedPromise;
  const status = structuredClone(data.status);
  for (const [name, source] of Object.entries(status.sources)) {
    const age = Date.now() - Date.parse(source.last_success || '');
    source.stale = source.stale || !Number.isFinite(age) || age > (source.stale_after_seconds || (name === 'bgm' ? 43200 : 1800)) * 1000;
  }
  const envelope = items => ({items, status});
  const url = new URL(path, 'https://finder.invalid');
  if (url.pathname === '/api/status') return status;
  if (url.pathname === '/api/anime') {
    const scope = url.searchParams.get('scope') || 'active';
    const keyword = (url.searchParams.get('keyword') || '').toLocaleLowerCase();
    return envelope(data.anime.filter(a =>
      (scope === 'all' || (scope === 'active' ? ['current', 'continuing'].includes(a.scope) : a.scope === scope)) &&
      (url.searchParams.get('include_continuing') !== 'false' || a.scope !== 'continuing') &&
      (url.searchParams.get('has_groups') !== 'true' || a.group_count > 0) &&
      [a.title, ...a.aliases].some(name => name.toLocaleLowerCase().includes(keyword))
    ));
  }
  if (url.pathname === '/api/blocked') return {...data.blocked, status};
  if (url.pathname === '/api/unmatched') return {...data.unmatched, status};
  if (url.pathname === '/api/updates') {
    const end = Date.now(), start = end - 24 * 3600000;
    const items = data.updates.items.map(item => {
      const releases = item.releases.filter(r => Date.parse(r.published_at) >= start && Date.parse(r.published_at) <= end);
      return {...item, releases, release_count: releases.length, episodes: [...new Set(releases.flatMap(r => r.episodes))].sort((a, b) => Number(a) - Number(b)), updated_at: releases[0]?.published_at};
    }).filter(item => item.release_count);
    return {...envelope(items), window_start: new Date(start).toISOString(), window_end: new Date(end).toISOString()};
  }
  const match = url.pathname.match(/^\/api\/anime\/(.+)\/(groups|releases)$/);
  if (match) {
    const id = decodeURIComponent(match[1]);
    if (match[2] === 'groups') return envelope(data.groups[id] || []);
    const group = url.searchParams.get('group');
    const lists = data.releases[id] || {};
    return envelope(group ? lists[group] || [] : [...new Map(Object.values(lists).flat().map(r => [r.id, r])).values()]);
  }
  throw Error('此功能需要本机服务');
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

function cover(title, coverUrl) {
  const url = coverUrl || '';
  const available = /^https:\/\/(lain\.bgm\.tv|r2\.anibt\.net)\//.test(url);
  const tag = available ? 'a' : 'span';
  return `<${tag} class="subjectCover cover coverPortrait finder-cover${available ? '' : ' unavailable'}" ${available ? `href="${esc(url)}" target="_blank" rel="noopener noreferrer" title="查看 ${esc(title)} 的封面"` : ''}><span class="cover-placeholder" aria-hidden="true">暂无封面</span>${available ? `<img class="cover" src="${esc(url)}" alt="${esc(title)} 封面" width="78" height="104" loading="lazy" decoding="async" referrerpolicy="no-referrer">` : ''}</${tag}>`;
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
    const working = ['catalog', 'backfill', 'incremental', 'metadata', 'inspection'].includes(value.phase);
    const phases = {catalog: '刷新目录', backfill: '补查中', incremental: '取最新', metadata: '核对放送', inspection: '核对简介'};
    const label = value.error ? '失败' : working ? phases[value.phase] : value.stale ? '过期' : '正常';
    const detail = working ? status.progress[source] || '' : value.backfill_remaining ? `剩余 ${value.backfill_remaining} 部待补查` : '';
    return `<div class="health ${value.error ? 'error' : value.stale ? '' : 'ready'}" title="最后成功：${esc(time(value.last_success))}"><b>${sourceNames[source] || esc(source)}</b><span>${label}</span>${value.error ? `<div class="source-error">${esc(value.error)}</div>` : detail ? `<div class="source-progress">${esc(detail)}</div>` : ''}</div>`;
  }).join('');
  const elapsed = Math.max(0, Math.floor((Date.now() - Date.parse(status.progress.started_at || '')) / 60000));
  $('#progress').textContent = status.progress.running ? `${status.progress.message}${elapsed ? ` · ${elapsed} 分钟` : ''}` : `更新于 ${time(status.last_scan)}`;
  $('#scan').setAttribute('aria-disabled', String(staticMode || status.progress.running));
  $('#scan').textContent = staticMode ? '只读快照' : status.progress.running ? '采集中' : '立即采集';
}

function description(r) {
  if (!r.description) return '';
  return `<details class="release-description"><summary>发布说明</summary><div class="description-meta">${r.description_checked_at ? esc(time(r.description_checked_at)) : '资源摘要'} ${link(r.description_url, '原页')}</div><pre>${esc(r.description)}</pre></details>`;
}

function resource(r) {
  return renderResource(r, true);
}

function renderResource(r, showReasons) {
  return `<div class="resource"><div class="resource-title">${esc(r.title)}</div><div class="meta">${esc((r.languages || []).join(' / ') || '语言未标注')} / ${esc(r.resolution || '画质未标注')} / ${esc(time(r.published_at))}</div>${showReasons && r.reasons?.length ? `<div class="reason">${esc(r.reasons.join('；'))}</div>` : ''}<div class="links">${(r.origins || []).map(o => link(o.url, sourceNames[o.source] || o.source)).join('')}${link(r.magnet, '磁力')}${link(r.torrent, '种子')}${r.magnet ? `<a href="#copy" role="button" class="chiiBtn copy" data-copy="${esc(r.magnet)}">复制磁力</a>` : ''}</div>${description(r)}</div>`;
}

async function animePage() {
  const version = ++viewVersion;
  const data = await api('/api/anime?' + new URLSearchParams({keyword, scope, has_groups: hasGroups}));
  if (version !== viewVersion || page !== 'anime') return;
  $('#page-title').textContent = '番剧';
  $('#content').innerHTML = `<div id="browserTools" class="clearit"><span>${data.items.length} 部 / ${scopeNames[scope]}</span><label><input type="checkbox" id="has-groups" ${hasGroups ? 'checked' : ''}>有可用组</label></div>` + (data.items.length ? `<ul id="browserItemList" class="browserFull finder-list">${data.items.map((a, i) => `<li class="item ${i % 2 ? 'even' : 'odd'} clearit">${cover(a.title, a.cover_url)}<div class="inner"><details class="anime" data-anime="${esc(a.id)}"><summary><h3 class="anime-title">${esc(a.title)}</h3><p class="info tip">${esc(a.premiere || '首播待核实')} / ${scopeNames[a.scope]}${a.total_episodes ? ' / ' + a.total_episodes + ' 话' : ''}</p><p class="group-preview">${esc(a.groups.map(g => g.name).join(' / ') || '暂无可用组')}</p><span class="group-count"><strong>${a.group_count}</strong>组</span></summary><div class="detail"></div></details></div></li>`).join('')}</ul>` : empty('没有符合条件的番剧'));
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
  const data = await api('/api/updates');
  if (version !== viewVersion || page !== 'changes') return;
  updatesRefreshedAt = Date.now();
  const subjects = new Map();
  for (const group of data.items) {
    if (!subjects.has(group.anime_id)) subjects.set(group.anime_id, {...group, groups: []});
    subjects.get(group.anime_id).groups.push(group);
  }
  const items = [...subjects.values()];
  $('#page-title').textContent = pageNames.changes;
  $('#content').innerHTML = `<div id="browserTools" class="clearit"><span>${items.length} 部 / ${data.items.length} 组更新</span><span class="tip">${esc(time(data.window_start))} — ${esc(time(data.window_end))}</span></div>` + (items.length ? `<ul id="change-items" class="browserFull finder-list">${items.map((a, i) => `<li class="item ${i % 2 ? 'even' : 'odd'} clearit">${cover(a.anime_title, a.cover_url)}<div class="inner"><details class="anime recent-update" data-update="${i}" data-update-anime="${esc(a.anime_id)}"><summary><h3 class="anime-title">${esc(a.anime_title)}</h3><p class="group-preview">${esc(a.groups.map(g => g.group_name).join(' / '))}</p><p class="info tip">${esc(time(a.updated_at))}</p><span class="group-count"><strong>${a.groups.length}</strong>组</span></summary><div class="detail recent-groups"></div></details></div></li>`).join('')}</ul>` : empty('近 24 小时暂无更新'));
  $('#content').querySelectorAll('[data-update]').forEach(el => el.addEventListener('toggle', () => {
    if (!el.open || el.dataset.loaded) return;
    el.dataset.loaded = '1';
    const anime = items[Number(el.dataset.update)];
    const area = el.querySelector('.recent-groups');
    area.innerHTML = anime.groups.map((g, i) => `<details class="group recent-group" data-update-group="${i}"><summary><b>${esc(g.group_name)}</b><span class="tip">${g.release_count} 条</span></summary><p class="episodes">更新集数：${esc(episodeText(g.episodes))} / ${esc(time(g.updated_at))}</p><div class="resources"></div></details>`).join('');
    area.querySelectorAll('[data-update-group]').forEach(group => group.addEventListener('toggle', () => {
      if (!group.open || group.dataset.loaded) return;
      group.dataset.loaded = '1';
      group.querySelector('.resources').innerHTML = anime.groups[Number(group.dataset.updateGroup)].releases.map(resource).join('');
    }));
  }));
}

async function recordsPage(blocked) {
  if (blocked) return blockedPage();
  const version = ++viewVersion;
  const data = await api(blocked ? '/api/blocked' : '/api/unmatched');
  if (version !== viewVersion || page !== (blocked ? 'blocked' : 'unmatched')) return;
  $('#page-title').textContent = blocked ? '已屏蔽记录' : '未匹配资源';
  $('#content').innerHTML = `<div id="browserTools" class="clearit"><span>${data.total} 条${data.total > data.items.length ? ' / 当前展示 ' + data.items.length : ''}</span></div>` + (data.items.length ? data.items.map(resource).join('') : empty('暂无记录'));
}

async function blockedPage() {
  const version = ++viewVersion;
  const data = await api('/api/blocked');
  if (version !== viewVersion || page !== 'blocked') return;
  $('#page-title').textContent = '已屏蔽记录';
  $('#content').innerHTML = `<div id="browserTools" class="clearit"><span>${data.items.length} 组 / ${data.total} 条</span><span class="tip">${esc(seasonName(data.season))}</span></div>` + (data.items.length ? `<ul id="blocked-groups" class="browserFull finder-list">${data.items.map((g, i) => `<li class="item ${i % 2 ? 'even' : 'odd'} clearit"><div class="inner"><details class="blocked-group" data-blocked-group="${i}"><summary><h3 class="anime-title">${esc(g.group_name)} <small class="grey">${g.anime_count} 部 / ${g.release_count} 条</small></h3><p class="group-preview">${esc(g.animes.map(a => a.title).join(' / '))}</p></summary><div class="blocked-animes"></div></details></div></li>`).join('')}</ul>` : empty('本季度暂无相关屏蔽记录'));
  $('#content').querySelectorAll('[data-blocked-group]').forEach(el => el.addEventListener('toggle', () => {
    if (!el.open || el.dataset.loaded) return;
    el.dataset.loaded = '1';
    const group = data.items[Number(el.dataset.blockedGroup)];
    const area = el.querySelector('.blocked-animes');
    area.innerHTML = `<p class="blocked-reasons">${esc([...new Set(group.animes.flatMap(a => a.reasons))].join('；'))}</p><ul class="browserFull finder-list blocked-anime-list">${group.animes.map((a, i) => `<li class="item clearit">${cover(a.title, a.cover_url)}<div class="inner"><details class="anime" data-blocked-anime="${i}"><summary><h3 class="anime-title">${esc(a.title)}</h3><p class="info tip">集数 ${esc(episodeText(a.episodes))}</p><span class="group-count"><strong>${a.releases.length}</strong>条</span></summary><div class="detail resources"></div></details></div></li>`).join('')}</ul>`;
    area.querySelectorAll('[data-blocked-anime]').forEach(detail => detail.addEventListener('toggle', () => {
      if (!detail.open || detail.dataset.loaded) return;
      detail.dataset.loaded = '1';
      detail.querySelector('.resources').innerHTML = group.animes[Number(detail.dataset.blockedAnime)].releases.map(r => renderResource(r, false)).join('');
    }));
  }));
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
  if (staticMode && next === 'settings') next = 'anime';
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
  if (staticMode) return;
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

document.addEventListener('error', event => {
  if (!event.target.matches?.('.finder-cover img')) return;
  const container = event.target.closest('.finder-cover');
  container.classList.add('unavailable');
  container.removeAttribute('href');
  container.removeAttribute('title');
}, true);
document.addEventListener('keydown', event => {
  if (event.key === ' ' && event.target.matches('a[role=button]')) { event.preventDefault(); event.target.click(); }
});
document.body.classList.toggle('static-site', staticMode);
if (staticMode) document.querySelectorAll('[data-page="settings"], #edit-season').forEach(el => el.hidden = true);
navigate(page);
setInterval(async () => {
  try {
    const wasRunning = status?.progress.running;
    await health();
    if ((wasRunning || status.progress.running) && page === 'anime' && !document.querySelector('details[open]') && document.activeElement?.id !== 'search_text') await animePage();
    if (page === 'changes' && (wasRunning || status.progress.running || Date.now() - updatesRefreshedAt >= 60000) && !document.querySelector('details[open]')) await changesPage();
  } catch (error) { notice('服务连接失败：' + error.message); }
}, 8000);
