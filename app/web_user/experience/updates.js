'use strict';
(() => {
  names.updates = '系统更新';
  const section = document.createElement('section');
  section.id = 'page-updates';
  section.className = 'page';
  section.hidden = true;
  section.innerHTML = `<div class="heading"><div><p class="eyebrow">KEEP YOUR COMPANION CURRENT</p><h1>系统更新</h1><p>维护已申领化身的能力配置与执行分支技能。</p></div></div>
    <div class="panel"><div class="section-title"><h2>选择更新对象</h2><button type="button" class="secondary" id="updates-refresh">刷新智能体列表</button></div><label class="update-target-label" for="updates-target">智能体<select id="updates-target" aria-label="选择需要更新的智能体"></select></label><p id="updates-agent" class="muted">正在读取智能体列表…</p></div>
    <div id="updates-octopus" class="panel" hidden><h2>Octopus · 更新能力配置</h2><p class="muted">从原智能体提供方读取能力矩阵，选择后重新签发 PA 配置。运行中的实例请先停止；更新成功后重新启动以加载新配置。</p><div class="update-actions"><button type="button" class="secondary" id="updates-load">1. 获取当前可选能力</button><button type="button" class="primary" id="updates-submit" disabled>2. 提交能力更新</button></div><div id="updates-capabilities"></div></div>
    <div id="updates-child-octopus" class="panel" hidden><h2>Octopus 子智能体 · 更新能力</h2><p class="muted">子智能体继承主智能体身份，只能选择它支持的问答能力；此处更新该实例的运行配置，不重新签发主智能体凭证。</p><div id="updates-child-capabilities"></div><div class="update-actions"><button type="button" class="primary" id="updates-child-submit">保存子智能体能力</button></div></div>
    <div id="updates-openclaw" class="panel" hidden><h2>OpenClaw 执行分支 · 更新技能</h2><p class="muted">此页面只更新所选执行分支已安装的 ClawHub Skill，不改动 Octopus 问答能力或主身份。请先停止该分支，更新后重新启动。</p><p id="updates-openclaw-capabilities" class="muted"></p><div class="update-actions"><button type="button" class="secondary" id="updates-skills-refresh">刷新已安装技能</button><button type="button" class="primary" id="updates-skills-all" disabled>更新全部已安装技能</button></div><div id="updates-skills-list" class="update-skill-list"></div></div>
    <div class="panel"><h2>操作结果</h2><p id="updates-status" role="status" aria-live="polite" class="muted">请选择上方操作。</p><details id="updates-details" hidden><summary>查看接口详情</summary><pre id="updates-result"></pre></details></div>`;
  document.querySelector('main').append(section);
  const find = selector => section.querySelector(selector);
  let matrix = null, updateKey = null, installed = [], loading = false;
  let recordId = '', targets = new Map(), childOptions = null, targetRefresh = 0;
  const selectedTarget = () => targets.get(find('#updates-target').value);
  const status = (message, error = false, detail = null) => {
    const el = find('#updates-status');
    el.textContent = message;
    el.classList.toggle('update-error', error);
    find('#updates-details').hidden = !detail;
    find('#updates-result').textContent = detail ? JSON.stringify(detail, null, 2) : '';
  };
  function reset() {
    matrix = null; updateKey = null; installed = []; childOptions = null;
    find('#updates-capabilities').replaceChildren();
    find('#updates-child-capabilities').replaceChildren();
    find('#updates-skills-list').replaceChildren();
    find('#updates-submit').disabled = true;
    find('#updates-skills-all').disabled = true;
  }
  function refreshRecord() {
    const target = selectedTarget();
    const id = target?.id || '';
    if (id !== recordId) { recordId = id; reset(); }
    const ready = !!(target && state.pa);
    find('#updates-agent').textContent = ready ? `${target.name} · ${target.type === 'openclaw' ? 'OpenClaw 执行分支' : target.child ? 'Octopus 子智能体' : 'Octopus 主智能体'} · ${id}` : '尚未找到可更新的智能体。请先完成申领。';
    find('#updates-octopus').hidden = !ready || target.child || target.type !== 'octopus';
    find('#updates-child-octopus').hidden = !ready || !target.child || target.type !== 'octopus';
    find('#updates-openclaw').hidden = !ready || target.type !== 'openclaw';
    return ready;
  }
  async function refreshTargets() {
    const refresh = ++targetRefresh;
    const chooser = find('#updates-target');
    const previous = chooser.value;
    const nextTargets = new Map();
    if (state.phc?.id && state.pa) {
      const id = state.phc.id.replaceAll(':', '_');
      nextTargets.set(id, {id, name:'我的主智能体', child:false, type:state.type});
      if (state.type === 'octopus') {
        const data = await api('/user/children/' + encodeURIComponent(state.phc.id));
        for (const child of data.children || []) {
          if (child.stage === 'unavailable') continue;
          nextTargets.set(child.phc_id, {id:child.phc_id, name:child.name, child:true, type:child.agent_type});
        }
      }
    }
    if (refresh !== targetRefresh) return;
    targets = nextTargets; chooser.replaceChildren();
    for (const target of targets.values()) {
      const option = document.createElement('option'); option.value = target.id;
      option.textContent = `${target.name} · ${target.type === 'openclaw' ? 'OpenClaw 执行分支' : target.child ? 'Octopus 子智能体' : 'Octopus 主智能体'}`;
      chooser.append(option);
    }
    chooser.value = targets.has(previous) ? previous : targets.keys().next().value || '';
    refreshRecord();
    await loadSelectedDetails();
  }
  async function loadSelectedDetails() {
    const target = selectedTarget();
    if (!target || !target.child) return;
    const id = target.id;
    const data = await api(`/user/children/instance/${encodeURIComponent(id)}/update-options`);
    if (selectedTarget()?.id !== id) return;
    if (target.type === 'octopus') {
      childOptions = data;
      const box = find('#updates-child-capabilities'); box.replaceChildren();
      for (const item of data.options) {
        const label = document.createElement('label');
        const input = document.createElement('input'); input.type = 'checkbox'; input.value = item.id;
        input.checked = data.capabilities.includes(item.id);
        label.append(input, document.createTextNode(item.label)); box.append(label);
      }
    } else {
      find('#updates-openclaw-capabilities').textContent = '当前分支工具能力：' + (data.options.filter(item => data.capabilities.includes(item.id)).map(item => item.label).join('、') || '未配置');
    }
  }
  async function guardStopped() {
    if (!refreshRecord()) throw new Error('请先完成化身申领。');
    const id = selectedTarget().id;
    const runtime = await api(`/user/runtime/${encodeURIComponent(id)}/status`);
    if (['ready', 'checking', 'installing', 'starting', 'recovering'].includes(runtime.stage)) {
      throw new Error('请先到「我的智能体」停止所选实例，待停止完成后再更新。');
    }
  }
  async function run(button, task) {
    if (loading) return;
    loading = true;
    find('#updates-target').disabled = true;
    const label = button.textContent;
    button.disabled = true;
    button.textContent = '处理中…';
    try { await task(); }
    catch (error) { status(error.message, true); }
    finally {
      loading = false;
      find('#updates-target').disabled = false;
      button.textContent = label;
      button.disabled = button.id === 'updates-submit' ? !updateKey
        : button.id === 'updates-skills-all' ? !installed.length : false;
    }
  }
  function updateUser() {
    const identity = state.user?.pii;
    if (!identity?.id_number) throw new Error('最近的化身记录缺少身份标识，请刷新记录或检查申领资料。');
    return {pii: identity, bi: {last_login_ip: '127.0.0.1'}, cdid: 'cdid:user.placeholder', ecid: 'g'};
  }
  function drawMatrix() {
    const box = find('#updates-capabilities');
    box.replaceChildren();
    matrix.forEach((row, i) => {
      if (!Array.isArray(row) || !row.length) return;
      const group = document.createElement('div');
      group.className = 'capability-row';
      const heading = document.createElement('strong');
      heading.textContent = capabilityGroups[i] || `配置 ${i + 1}`;
      const options = document.createElement('div');
      options.className = 'update-capability-options';
      group.append(heading, options);
      row.forEach((item, j) => {
        const label = document.createElement('label');
        const input = document.createElement('input');
        input.type = i === 5 ? 'radio' : 'checkbox';
        input.name = `update-row-${i}`;
        input.dataset.row = String(i);
        input.dataset.index = String(j);
        const raw = String(item.label || item.id || '');
        input.checked = !!state.cmc?.[i]?.some(selected => selected.label === item.label);
        label.append(input, document.createTextNode(labels[raw] || raw));
        options.append(label);
      });
      box.append(group);
    });
  }
  find('#updates-refresh').onclick = async () => {
    try { await restore(); await refreshTargets(); page('updates'); status('智能体列表已刷新。'); }
    catch (error) { status(error.message, true); }
  };
  find('#updates-target').onchange = async () => {
    refreshRecord();
    try { await loadSelectedDetails(); status('已切换更新对象，请核对该实例的能力或技能。'); }
    catch (error) { status(error.message, true); }
  };
  find('#updates-load').onclick = event => run(event.currentTarget, async () => {
    if (selectedTarget()?.child || selectedTarget()?.type !== 'octopus') throw new Error('请选择 Octopus 主智能体。');
    await guardStopped();
    const id = state.phc.id;
    const result = await api('/user/update_init', {base_url: connection().ap, phc: state.phc, user: updateUser(), agent_type: 'octopus'});
    if (state.phc?.id !== id) throw new Error('当前化身已切换，请重新加载能力。');
    if (result.fallback) throw new Error('智能体提供方当前不可连接，未取得可提交的实时配置。请启动 AP 后重试。');
    if (!Array.isArray(result.cmm) || !result.sk || !result.pk) throw new Error('智能体提供方返回的配置不完整。');
    matrix = result.cmm;
    updateKey = {sk: String(result.sk), pk: String(result.pk), id};
    drawMatrix();
    find('#updates-submit').disabled = false;
    status('已加载原智能体提供方的能力。核对选择后提交更新。');
  });
  find('#updates-submit').onclick = event => run(event.currentTarget, async () => {
    if (selectedTarget()?.child || selectedTarget()?.type !== 'octopus') throw new Error('当前选择不是 Octopus 主智能体。');
    if (!matrix || !updateKey || state.phc?.id !== updateKey.id) throw new Error('请重新获取当前化身的能力配置。');
    await guardStopped();
    const cmc = matrix.map((row, i) => row.filter((_, j) => !!find(`#updates-capabilities input[data-row="${i}"][data-index="${j}"]`)?.checked));
    if (!cmc.flat().length) throw new Error('请至少选择一项能力。');
    const result = await api('/user/update_submit', {base_url: connection().ap, tp_base_url: connection().tp, cmc, hid: updateUser().pii.id_number, phc: state.phc, user_sk: updateKey.sk, user_pk: updateKey.pk, agent_type: 'octopus'});
    if (!result.PHC || !result.PA || result.verified_cmi !== true || result.verified_af_user !== true || result.verified_phc_user !== true || result.PHC?.PROOF?.needs_tp_resign) {
      status('能力或身份凭证验证未通过；请展开接口详情查看具体校验状态。', true, {verified_cmi: result.verified_cmi, verified_af_user: result.verified_af_user, verified_phc_user: result.verified_phc_user, needs_tp_resign: result.PHC?.PROOF?.needs_tp_resign});
      return;
    }
    const saved = await api('/user/last_agent', {phc: result.PHC, pa: result.PA, cmc, agent_type: 'octopus', identity: state.user.pii});
    if (!saved.success) throw new Error('配置已更新，但保存化身记录失败。请查看服务日志并联系管理员。');
    state.phc = result.PHC; state.pa = result.PA; state.cmc = cmc;
    matrix = null; updateKey = null;
    find('#updates-submit').disabled = true;
    sync();
    status('能力配置与 TP 身份凭证均已更新。请到「我的智能体」重新启动主化身。', false, {verified_cmi: result.verified_cmi, verified_af_user: result.verified_af_user, verified_phc_user: result.verified_phc_user, manifest: result.manifest});
  });
  find('#updates-child-submit').onclick = event => run(event.currentTarget, async () => {
    const target = selectedTarget();
    if (!target?.child || target.type !== 'octopus' || !childOptions) throw new Error('请选择 Octopus 子智能体并加载其能力。');
    await guardStopped();
    const capabilities = [...find('#updates-child-capabilities').querySelectorAll('input:checked')].map(input => input.value);
    const result = await api(`/user/children/instance/${encodeURIComponent(target.id)}/update`, {capabilities});
    await loadSelectedDetails();
    status(`${target.name} 的能力已更新。请重新启动这个子智能体。`, false, result);
  });
  function drawSkills() {
    const box = find('#updates-skills-list');
    box.replaceChildren();
    if (!installed.length) { box.textContent = '当前实例没有已安装的 Skill。'; return; }
    for (const skill of installed) {
      const row = document.createElement('div'); row.className = 'update-skill-row';
      const name = document.createElement('strong'); name.textContent = skill.slug;
      const button = document.createElement('button'); button.type = 'button'; button.className = 'secondary'; button.textContent = '更新';
      button.onclick = event => run(event.currentTarget, async () => {
        await guardStopped();
        const result = await api('/skills/update-one', {user_name: selectedTarget().id, skill_slug: skill.slug});
        status(`${skill.slug} 已更新。重新启动执行分支后生效。`, false, result);
      });
      row.append(name, button); box.append(row);
    }
  }
  find('#updates-skills-refresh').onclick = event => run(event.currentTarget, async () => {
    if (!refreshRecord()) throw new Error('请先完成化身申领。');
    if (selectedTarget()?.type !== 'openclaw') throw new Error('请选择 OpenClaw 执行分支。');
    const result = await api(`/skills/installed/${encodeURIComponent(selectedTarget().id)}`);
    installed = (result.installed_skills || []).filter(skill => skill && typeof skill.slug === 'string');
    drawSkills();
    find('#updates-skills-all').disabled = !installed.length;
    status(`已读取 ${installed.length} 个已安装 Skill。`);
  });
  find('#updates-skills-all').onclick = event => run(event.currentTarget, async () => {
    await guardStopped();
    if (!installed.length) throw new Error('当前没有需要更新的 Skill。');
    const result = await api('/skills/update-installed', {user_name: selectedTarget().id, selected_skills: []});
    status(result.message || '技能更新完成。重新启动执行分支后生效。', false, result);
  });
  const syncTargets = () => refreshTargets().catch(error => status(error.message, true));
  window.addEventListener('agent-record-ready', syncTargets);
  window.addEventListener('children-updated', syncTargets);
  window.addEventListener('hashchange', () => { if (location.hash === '#updates') syncTargets(); });
  syncTargets();
})();
