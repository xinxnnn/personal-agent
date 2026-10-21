'use strict';
// OpenClaw 分身：介绍卡片、申领流程（复用已审核身份）以及与「系统更新」共用的能力矩阵渲染。
(() => {
  names.claw = '申领 OpenClaw 分身';
  const CLAW_GROUPS = {0: '核心能力', 3: '基本功能', 4: 'Skill', 5: '大模型'};
  // 与原用户控制台 /user 中的 Hook 说明一致；可选项本身仍以 AP 能力矩阵为准。
  const CLAW_HOOKS = {
    'session-memory': ['会话记忆备份', '执行 /new 或 /reset 时，自动保存上一轮对话的最后 15 条消息到记忆文件'],
    'bootstrap-extra-files': ['额外引导文件注入', 'Agent 启动时自动注入额外的 AGENTS.md、TOOLS.md 等引导文件'],
    'command-logger': ['命令审计日志', '将所有斜杠命令记录到 ~/.openclaw/logs/commands.log，JSONL 格式'],
    'boot-md': ['启动脚本执行', 'Gateway 启动时自动执行 BOOT.md 中的指令，适合初始化检查'],
  };
  const HOOK_FIELDS = {'session-memory': 'session_memory', 'command-logger': 'command_logger', 'bootstrap-extra-files': 'bootstrap_extra_files', 'boot-md': 'boot_md'};
  let catalogCache = null;

  async function catalog() {
    if (catalogCache) return catalogCache;
    const [skills, providers] = await Promise.all([
      api('/skills/recommended').catch(() => ({skills: []})),
      api('/user/llm_providers', undefined, true).catch(() => ({providers: []})),
    ]);
    catalogCache = {
      skills: Object.fromEntries((skills.skills || []).map(item => [item.slug, item])),
      providers: Object.fromEntries((providers.providers || []).map(item => [item.key, item.name])),
    };
    return catalogCache;
  }
  function describe(row, item, info) {
    const params = item.params || {};
    if (row === 0) return ['OpenClaw 本地执行核心', '分身的运行核心，必选'];
    if (params.hook_type && CLAW_HOOKS[params.hook_type]) return CLAW_HOOKS[params.hook_type];
    if (params.skill_slug) {
      const skill = info.skills[params.skill_slug];
      return [skill?.name || params.skill_slug, skill?.description || `ClawHub Skill：${params.skill_slug}`];
    }
    if (item.label === 'llm-model') {
      const model = String(params.model || '').replace(/^openai\//, '');
      return [`${info.providers[params.provider] || params.provider || '模型'} · ${model}`, params.base_url ? `服务地址：${params.base_url}` : '使用服务商默认地址'];
    }
    return [String(item.label || item.id || ''), ''];
  }
  // selected：已绑定的 CMC，用于预选；installedSkills：给定时 Skill 一栏只读，按已安装情况勾选。
  function renderMatrix(box, matrix, info, {selected = null, installedSkills = null, skillsEnabled = true} = {}) {
    box.replaceChildren();
    matrix.forEach((row, i) => {
      if (!Array.isArray(row) || !row.length) return;
      const group = document.createElement('div'); group.className = 'capability-row claw-capability-row';
      const heading = document.createElement('strong'); heading.textContent = CLAW_GROUPS[i] || `配置 ${i + 1}`;
      const options = document.createElement('div'); options.className = 'claw-options';
      let llmChecked = false;
      row.forEach((item, j) => {
        const [title, detail] = describe(i, item, info);
        const label = document.createElement('label'); label.className = 'claw-option';
        const input = document.createElement('input');
        input.type = item.label === 'llm-model' ? 'radio' : 'checkbox';
        input.name = `${box.id}-row-${i}`; input.dataset.row = String(i); input.dataset.index = String(j);
        const slug = item.params?.skill_slug;
        if (i === 0) { input.checked = true; input.disabled = true; }
        else if (slug && installedSkills) { input.checked = installedSkills.includes(slug); input.disabled = true; }
        else if (selected) input.checked = !!selected[i]?.some(chosen => chosen.id === item.id);
        if (slug && !skillsEnabled) { input.checked = false; input.disabled = true; }
        if (input.type === 'radio' && input.checked) llmChecked = true;
        const text = document.createElement('span');
        const strong = document.createElement('b'); strong.textContent = title;
        const small = document.createElement('small'); small.textContent = detail;
        text.append(strong, small); label.append(input, text); options.append(label);
      });
      if (row.some(item => item.label === 'llm-model') && !llmChecked) options.querySelector('input[type=radio]').checked = true;
      group.append(heading, options); box.append(group);
    });
  }
  function collect(box, matrix) {
    return matrix.map((row, i) => (row || []).filter((_, j) => !!box.querySelector(`input[data-row="${i}"][data-index="${j}"]`)?.checked));
  }
  function extras(cmc) {
    const chosen = cmc.flat(); const hooks = {};
    chosen.forEach(item => { const field = HOOK_FIELDS[item.params?.hook_type]; if (field) hooks[field] = true; });
    const llm = chosen.find(item => item.label === 'llm-model')?.params;
    return {hooks_config: hooks, skills_config: chosen.map(item => item.params?.skill_slug).filter(Boolean),
            llm_config: llm ? {provider: llm.provider, model: llm.model, base_url: llm.base_url} : null};
  }
  async function installSkills(instanceId, skills, progress = () => {}) {
    const started = await api('/skills/install', {user_name: instanceId, selected_skills: skills});
    for (let attempt = 0; attempt < 450; attempt++) {
      await new Promise(resolve => setTimeout(resolve, 2000));
      const current = await api('/skills/status/' + encodeURIComponent(started.session_id));
      progress(current.message || '正在安装 Skill…');
      if (current.status === 'completed') return current;
    }
    throw new Error('Skill 安装仍未完成，可稍后在「系统更新」中查看已安装技能。');
  }
  window.clawKit = {catalog, renderMatrix, collect, extras, installSkills};

  // ---------- 「我的 OpenClaw 分身」尚未申领时的介绍 ----------
  const intro = document.createElement('div');
  intro.id = 'claw-intro'; intro.className = 'panel claw-intro'; intro.hidden = true;
  intro.innerHTML = `<div class="claw-intro-copy"><span class="pill">OpenClaw · 本地执行型分身</span>
    <h2>让分身直接在你的电脑上工作</h2>
    <p>OpenClaw 运行在你的电脑本机，定位是能动手做事的执行型分身：在执行控制台中，经你配置和授权后，它可以调用浏览器、文件、命令等本机工具，直接帮你在电脑上完成工作。</p>
    <ul><li>沿用你已审核的可信身份，由智能体服务单独签发 OpenClaw 能力凭证</li><li>可按需启用基本功能、安装 ClawHub Skill，模型连接可在运行管理中调整</li><li>独立部署与运行，不支持创建子智能体</li></ul></div>
    <div class="claw-intro-status"><span class="empty-icon">✳</span><h3>您现在还没有创建 OpenClaw 分身</h3>
    <p class="muted">申领前会先检测电脑是否已具备 Node.js、Git 等运行环境，缺少时可一键安装。</p>
    <button type="button" class="primary" id="claw-start">申领 OpenClaw 分身 →</button></div>`;
  // 位置由 placeIntro() 决定：首次申领时在「我的化身」页，已有分身后在「我的分身 · OpenClaw」。
  intro.querySelector('#claw-start').onclick = () => page('claw');

  // ---------- 申领页 ----------
  const section = document.createElement('section');
  section.id = 'page-claw'; section.className = 'page'; section.hidden = true;
  section.innerHTML = `<div class="heading"><div><p class="eyebrow">CLAIM YOUR OPENCLAW AVATAR</p><h1>申领 OpenClaw 分身</h1><p>沿用已审核的可信身份，按流程为 OpenClaw 分身绑定能力并生成本机实例。</p></div><button type="button" class="secondary" id="claw-back">← 返回我的分身</button></div>
    <div class="steps"><span id="claw-step1">01 身份确认</span><span id="claw-step2">02 环境检测</span><span id="claw-step3">03 选择能力</span><span id="claw-step4">04 生成分身</span></div>
    <div class="panel"><div class="section-title"><h2>1. 确认可信身份</h2><span id="claw-identity-status">读取中</span></div><p class="muted">OpenClaw 分身沿用 Octopus 化身申领时已通过审核的身份凭证（PHC），无需重新提交身份资料；智能体服务会为 OpenClaw 单独签发能力凭证（PA）。</p><dl id="claw-identity"></dl></div>
    <div class="panel"><div class="section-title"><h2>2. 检测本机运行环境</h2><button type="button" class="secondary" id="claw-env-check">重新检测</button></div><p class="muted">OpenClaw 在你的电脑本机运行，需要 Node.js（含 npm）和 Git；安装 Skill 还需要 ClawHub 命令行工具。一键安装会在本机打开安装窗口，完成后点击「重新检测」。</p><div id="claw-env" class="claw-env" aria-live="polite"></div><p id="claw-env-note" class="claw-note" role="status"></p></div>
    <div class="panel"><h2>3. 选择分身能力</h2><p class="muted">以下选项均来自智能体服务提供的 OpenClaw 能力矩阵。确认后，能力配置会与你的身份绑定并签发凭证。</p><button type="button" class="secondary" id="claw-load">加载可选能力</button><div id="claw-capabilities"></div><button type="button" class="primary" id="claw-confirm" disabled>确认能力并绑定身份</button></div>
    <div class="panel"><h2>4. 生成 OpenClaw 分身</h2><p class="muted">生成后到「我的分身 · 我的 OpenClaw 分身」中部署并启动。首次部署会下载 OpenClaw 运行组件，可能需要几分钟。</p><button type="button" class="primary" id="claw-create" disabled>生成我的 OpenClaw 分身</button><p id="claw-progress" class="recovery-progress" role="status" aria-live="polite" hidden></p></div>`;
  document.querySelector('main').append(section);
  const find = selector => section.querySelector(selector);
  const flow = {env: null, matrix: null, sk: '', pk: '', draft: null, info: null};

  function progress(message, status = 'working') {
    const el = find('#claw-progress'); el.textContent = message; el.dataset.state = status; el.hidden = false;
  }
  document.querySelector('#page-partners .avatar-tabs').after(intro);
  function render() {
    const identityReady = !!(state.phc && state.user?.pii?.id_number);
    const envReady = !!flow.env?.deps?.ready_for_openclaw;
    const claimed = !!state.claw;
    find('#claw-identity-status').textContent = claimed ? '已申领' : identityReady ? '身份已确认' : '尚未完成化身申领';
    const did = state.phc?.DID || state.phc?.ASO?.TPM?.CDID || '尚未生成';
    find('#claw-identity').innerHTML = [['身份凭证编号', state.phc?.id || '尚未签发'], ['去中心化身份', did], ['申请人', state.user?.pii?.name || '未读取到']]
      .map(([key, value]) => `<dt>${escapeHTML(key)}</dt><dd>${escapeHTML(value)}</dd>`).join('');
    find('#claw-load').disabled = claimed || !identityReady || !envReady || !!flow.draft;
    find('#claw-confirm').disabled = claimed || !flow.matrix || !!flow.draft;
    find('#claw-create').disabled = claimed || !flow.draft;
    const done = [identityReady, envReady, !!flow.draft, claimed];
    done.forEach((value, index) => find(`#claw-step${index + 1}`).classList.toggle('done', value));
    // 介绍卡片只在「我的分身 · OpenClaw」标签下、尚未申领时显示。
    intro.hidden = claimed || (state.avatarTab || 'octopus') !== 'openclaw';
    if (document.querySelector('#claw-intro')?.parentElement?.closest('#page-partners')) {
      document.querySelector('#page-partners .partner-workspace').hidden = !intro.hidden;
    }
  }
  function envRow(name, ok, detail, action) {
    const row = document.createElement('div'); row.className = 'claw-env-row'; row.dataset.ready = String(ok);
    const text = document.createElement('div');
    const title = document.createElement('strong'); title.textContent = name;
    const info = document.createElement('small'); info.textContent = detail;
    text.append(title, info);
    const badge = document.createElement('span'); badge.className = 'claw-env-badge'; badge.textContent = ok ? '已就绪' : '未就绪';
    row.append(text, badge);
    if (!ok && action) row.append(action);
    return row;
  }
  function installButton(label, task) {
    const button = document.createElement('button'); button.type = 'button'; button.className = 'secondary'; button.textContent = label;
    button.onclick = () => busy(button, task);
    return button;
  }
  function downloadLinks(result) {
    const links = [['Node.js 下载页', result.node_download_url], ['Git 下载页', result.git_download_url]].filter(([, url]) => url && /^https:\/\//.test(url));
    const note = find('#claw-env-note'); note.replaceChildren(document.createTextNode((result.detail || result.error || '无法自动安装') + '。可手动下载安装：'));
    links.forEach(([text, url]) => { const a = document.createElement('a'); a.href = url; a.target = '_blank'; a.rel = 'noopener noreferrer'; a.textContent = text + ' ↗'; note.append(' ', a); });
  }
  async function installDependency(target) {
    const result = await api('/user/openclaw/install_dependencies', {target}, true);
    if (result.success) { find('#claw-env-note').textContent = (result.message || '已打开安装窗口') + '安装完成后请点击「重新检测」。'; return; }
    downloadLinks(result);
  }
  async function installClawhub() {
    find('#claw-env-note').textContent = '正在通过 npm 安装 ClawHub，可能需要几分钟…';
    try {
      const result = await api('/skills/install-clawhub', {}, true);
      find('#claw-env-note').textContent = result.success ? 'ClawHub 已安装，正在重新检测。' : (result.message || 'ClawHub 安装失败，请检查 Node.js/npm 与网络。');
    } catch (error) {
      find('#claw-env-note').textContent = error.message.includes('超时') ? '安装仍在进行，请稍后点击「重新检测」。' : error.message;
      return;
    }
    await checkEnvironment();
  }
  async function checkEnvironment() {
    const box = find('#claw-env');
    box.textContent = '正在检测 Node.js、Git 与 ClawHub…';
    try {
      const [deps, hub] = await Promise.all([
        api('/user/openclaw/dependencies'),
        api('/skills/check-clawhub').catch(() => ({ready: false, installed: false})),
      ]);
      flow.env = {deps, hub};
      const node = deps.node || {}, git = deps.git || {};
      const missing = [!node.installed && 'node', !git.installed && 'git'].filter(Boolean);
      box.replaceChildren(
        envRow('Node.js（含 npm）', !!node.installed && !node.error, node.version || '运行 OpenClaw 网关与安装组件', installButton('一键安装 Node.js', () => installDependency('node'))),
        envRow('Git', !!git.installed && !git.error, git.version || 'OpenClaw 安装运行组件时需要', installButton('一键安装 Git', () => installDependency('git'))),
        envRow('ClawHub CLI（安装 Skill 时需要）', !!hub.ready, hub.version || '用于从 ClawHub 安装和更新 Skill', node.installed ? installButton('安装 ClawHub', installClawhub) : null),
      );
      if (missing.length === 2) box.append(installButton('一键安装全部缺失环境', () => installDependency('all')));
      find('#claw-env-note').textContent = deps.ready_for_openclaw
        ? (hub.ready ? '运行环境已就绪，可以继续选择能力。' : '运行环境已就绪。尚未安装 ClawHub，申领时将无法选择 Skill，可稍后在「系统更新」中安装。')
        : '运行环境尚未就绪，请先安装缺少的组件，再点击「重新检测」。';
    } catch (error) {
      box.textContent = '环境检测失败：' + error.message;
    } finally { render(); }
  }
  find('#claw-back').onclick = () => {
    // 首次申领时回到申领页，避免被工作台守卫弹回；否则返回「我的分身 · OpenClaw」。
    if (!state.avatarReady && !state.created && !state.claw) page('create');
    else window.dispatchEvent(new CustomEvent('open-avatar-tab', {detail: 'openclaw'}));
  };
  find('#claw-env-check').onclick = event => busy(event.currentTarget, checkEnvironment);
  find('#claw-load').onclick = event => busy(event.currentTarget, async () => {
    if (!flow.env?.deps?.ready_for_openclaw) throw new Error('请先完成运行环境检测。');
    if (!state.user?.pii?.id_number) throw new Error('最近的化身记录缺少身份标识，请刷新记录后重试。');
    const [data, info] = await Promise.all([
      api('/user/cmm_init', {base_url: connection().ap, phc: state.phc, user: state.user, agent_type: 'openclaw'}),
      catalog(),
    ]);
    if (!Array.isArray(data.cmm) || !data.sk || !data.pk) throw new Error('能力列表或绑定信息不完整。');
    flow.matrix = data.cmm; flow.sk = String(data.sk); flow.pk = String(data.pk); flow.info = info;
    renderMatrix(find('#claw-capabilities'), flow.matrix, info, {skillsEnabled: !!flow.env?.hub?.ready});
    notice('OpenClaw 能力列表已加载，请选择需要的能力。');
    return data.cmm;
  });
  find('#claw-confirm').onclick = event => busy(event.currentTarget, async () => {
    const cmc = collect(find('#claw-capabilities'), flow.matrix);
    if (!cmc[0]?.length) throw new Error('需要包含 OpenClaw 核心能力。');
    if (flow.matrix.some(row => row?.some(item => item.label === 'llm-model')) && !cmc.flat().some(item => item.label === 'llm-model')) throw new Error('请选择一个大模型。');
    const options = extras(cmc);
    const data = await api('/user/cmm_submit', {base_url: connection().ap, cmc, hid: state.user.pii.id_number, phc: state.phc,
      user_sk: flow.sk, user_pk: flow.pk, agent_type: 'openclaw', hooks_config: options.hooks_config, llm_config: options.llm_config});
    if (!data.PHC || !data.PA) throw new Error('未收到完整凭证，绑定尚未完成。');
    flow.draft = {phc: data.PHC, pa: data.PA, cmc, options}; flow.sk = ''; flow.pk = '';
    find('#claw-capabilities').querySelectorAll('input').forEach(input => input.disabled = true);
    notice('能力与身份绑定完成，可以生成 OpenClaw 分身。');
  });
  find('#claw-create').onclick = event => busy(event.currentTarget, async () => {
    try { await createAvatar(); }
    catch (error) { progress(error.message, 'error'); throw error; }
  });
  async function createAvatar() {
    const draft = flow.draft;
    if (!draft) throw new Error('请先确认能力并绑定身份。');
    progress('正在检查运行环境并生成 OpenClaw 分身…');
    const deps = await api('/user/openclaw/dependencies');
    if (!deps.ready_for_openclaw) throw new Error('运行环境尚未就绪，请回到第 2 步检测并安装 Node.js 和 Git。');
    const created = await api('/user/create_agent', {phc: draft.phc, pa: draft.pa, cmc: draft.cmc, agent_type: 'openclaw',
      hid: state.user.pii.id_number, hooks_config: draft.options.hooks_config, skills_config: [], llm_config: draft.options.llm_config});
    if (!created.success || !created.instance_id) throw new Error(created.message || created.error || '生成未完成。');
    const record = {phc: draft.phc, pa: draft.pa, cmc: draft.cmc, agent_type: 'openclaw', instance_id: created.instance_id,
      identity: state.user.pii, skills: {user_name: created.instance_id, openclaw_path: created.openclaw_package || ''}};
    const saved = await api('/user/last_agent', record);
    if (!saved.success) throw new Error('分身已生成，但申领记录保存失败；请查看用户服务日志。');
    state.claw = {phc: draft.phc, pa: draft.pa, cmc: draft.cmc, instanceId: created.instance_id};
    flow.draft = null;
    let message = 'OpenClaw 分身已生成。';
    const skills = draft.options.skills_config;
    if (skills.length) {
      progress(`分身已生成，正在安装 ${skills.length} 个 Skill…`);
      try {
        const result = await installSkills(created.instance_id, skills, text => progress(text));
        message += result.failed?.length ? ` ${result.failed.length} 个 Skill 未安装成功，可在「系统更新」中重试。` : ' Skill 已安装。';
      } catch (error) { message += ' Skill 安装未完成：' + error.message; }
    }
    progress(message + '请在「我的分身」中部署并启动。', 'success');
    window.dispatchEvent(new Event('claw-record-ready'));
    notice(message + '请部署并启动。');
    window.dispatchEvent(new CustomEvent('open-avatar-tab', {detail: 'openclaw'}));
  }

  let checkedOnce = false;
  window.addEventListener('hashchange', () => {
    if (location.hash !== '#claw') return;
    render();
    if (!checkedOnce && !state.claw) { checkedOnce = true; checkEnvironment(); }
  });
  window.addEventListener('agent-record-ready',render);
  window.addEventListener('claw-record-ready',render);
  // busy() 结束时会恢复按钮可用并触发 avatar-flow-sync，这里按流程状态重新校正。
  window.addEventListener('avatar-flow-sync',render);
  render();
  if (location.hash === '#claw' && !state.claw) { checkedOnce = true; checkEnvironment(); }
})();
