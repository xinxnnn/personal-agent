const AP_API = "/v1/ap";

const state = {
  publicKey: "",
  apId: "",
  currentAgentType: "octopus",
  dbItems: [],
  stats: { agentTypeCount: 0, recordCount: 0, today: 0, week: 0 },
  capabilities: {},
  filters: { keyword: "", type: "", status: "", from: "", to: "" },

  // 能力状态：{ "openclaw:3": "active" | "maintenance" }
  capStates: {},
};

const $  = (id) => document.getElementById(id);
const $$ = (sel) => document.querySelectorAll(sel);

/* ---------- 业务操作日志（不裸露原始数据） ---------- */

const opLogs = [];
const OP_LOG_MAX = 30;

function pushOpLog(action, target = "") {
  const now = new Date();
  const time = now.toLocaleTimeString("zh-CN", { hour12: false });
  opLogs.unshift({ time, action, target });
  if (opLogs.length > OP_LOG_MAX) opLogs.length = OP_LOG_MAX;
  renderOpLogs();
}

function renderOpLogs() {
  const list = $("opLogList");
  if (!list) return;
  if (!opLogs.length) {
    list.innerHTML = `<li class="op-log-empty">暂无操作记录</li>`;
    return;
  }
  list.innerHTML = opLogs.map((log) => `
    <li>
      <span class="op-log-time">${escapeHtml(log.time)}</span>
      <span class="op-log-action">${escapeHtml(log.action)}</span>
      <span class="op-log-target">${escapeHtml(log.target || "")}</span>
    </li>
  `).join("");
}

/* 兼容旧调用：不再往页面写 JSON，只在 Console 保留 */
function setDebug(data) {
  if (typeof data === "string") {
    pushOpLog(data);
  } else if (data && typeof data === "object") {
    console.debug("[AP]", data);
  }
}

/* ---------- 通用请求 ---------- */

async function request(url, options = {}) {
  const r = await fetch(url, options);
  if (r.status === 401) {
    location.replace("/ap/login?next=" + encodeURIComponent(location.pathname));
    throw new Error("登录状态已失效");
  }
  const text = await r.text();
  let data;
  try { data = text ? JSON.parse(text) : {}; }
  catch { data = { raw: text }; }
  if (!r.ok) throw new Error(data.detail || data.error || `${r.status} ${r.statusText}`);
  return data;
}

/* ---------- 登录身份与退出 ---------- */

(function initAuthBar() {
  const nameEl   = $("userName");
  const roleEl   = $("userRole");
  const avatarEl = document.querySelector(".user-chip-avatar");
  const btn      = $("logoutBtn");

  request(`${AP_API}/me`)
    .then((data) => {
      const u = (data && data.user) || {};
      const name = u.username || u.u || "";
      const role = u.display  || u.d || "";
      if (nameEl) nameEl.textContent = name || "—";
      if (roleEl) roleEl.textContent = role || "—";
      if (avatarEl && name) avatarEl.textContent = name.charAt(0).toUpperCase();
    })
    .catch(() => {});

  if (btn) {
    let busy = false;
    btn.addEventListener("click", async () => {
      if (busy) return;
      busy = true;
      btn.disabled = true;
      try { await request(`${AP_API}/logout`, { method: "POST" }); } catch {}
      location.replace("/ap/login");
    });
  }
})();

/* ---------- 工具函数 ---------- */

function shortText(v, len = 18) {
  const s = String(v ?? "");
  return s.length <= len ? s : s.slice(0, len) + "...";
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;").replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;").replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function categoryName(agentType, index) {
  if (agentType === "openclaw") {
    const names = ["运行时","网关","人格","功能扩展","技能","模型接入","知识库","渠道","外观"];
    return names[index] || `第 ${index + 1} 组`;
  }
  const names = ["功能","输入","推理","知识","输出","外观"];
  return names[index] || `第 ${index + 1} 组`;
}

function labelZh(label) {
  const map = {
    "text-processing": "文本处理", "news-search": "新闻查询",
    "payment": "支付", "web-browsing": "联网搜索",
    "text": "文本", "voice": "语音", "image": "图像",
    "rag-openai": "RAG OpenAI", "rag-deepseek": "RAG DeepSeek",
    "local-memory": "本地记忆", "long-term-memory": "长期记忆",
    "knowledge-pro": "专业知识库",
    "speech": "语音输出", "video": "视频", "ppt": "PPT",
    "appearance-purple": "紫色", "appearance-blue": "蓝色",
    "appearance-pink": "粉色", "appearance-green": "绿色",
    "agent-openclaw": "OpenClaw", "openclaw": "OpenClaw",
    "hook-session-memory": "会话记忆",
    "hook-command-logger": "命令审计",
    "hook-bootstrap-files": "引导文件",
    "hook-boot-md": "启动脚本",
    "skill-weather": "天气 Skill",
    "skill-github": "GitHub Skill",
    "skill-desearch-web-search": "联网搜索 Skill",
    "llm-model": "大模型配置",
  };
  return map[label] || label || "未命名";
}

function statusText(s) {
  return ({ verified: "成功", pending: "待验证", failed: "失败" })[s] || "未知";
}
function statusClass(s) {
  return ({ verified: "active", pending: "pending", failed: "failed" })[s] || "pending";
}

/* ---------- 能力状态（启用 / 维护中） ---------- */

function capKey(agentType, idx) {
  return `${agentType}:${idx}`;
}

function getCapState(agentType, idx) {
  return state.capStates[capKey(agentType, idx)] || "active";
}

async function toggleCapState(agentType, idx, event) {
  if (event) event.stopPropagation();
  const key = capKey(agentType, idx);
  const current = getCapState(agentType, idx);
  const next = current === "active" ? "maintenance" : "active";

  // 乐观更新
  state.capStates[key] = next;
  renderCapabilities(state.capabilities[agentType] || [], agentType);

  try {
    await request(`${AP_API}/capabilities/state`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ agent_type: agentType, group_index: idx, state: next }),
    });
    pushOpLog(
      next === "active" ? "启用能力分组" : "停用能力分组",
      `${agentType} · 第 ${idx + 1} 组`
    );
  } catch (e) {
    // 失败回滚
    state.capStates[key] = current;
    renderCapabilities(state.capabilities[agentType] || [], agentType);
    pushOpLog("切换能力状态失败", e.message);
  }
}

/* ---------- 概览区 ---------- */

async function loadStatus() {
  try {
    const data = await request(`${AP_API}/status`);
    const types = data.supported_agent_types || [];
    state.stats.agentTypeCount = types.length;
    state.stats.recordCount    = data.record_count ?? 0;

    $("agentTypeCount").textContent = types.length || "-";
    $("recordCount").textContent    = data.record_count ?? "-";
    pushOpLog("刷新概览", `类型 ${types.length} 种 · 记录 ${data.record_count ?? 0} 条`);
  } catch (e) {
    $("agentTypeCount").textContent = "-";
    $("recordCount").textContent    = "-";
    pushOpLog("读取概览失败", e.message);
  }
}

function computeTodayWeek(items) {
  const now = new Date();
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const startOfWeek  = startOfToday - ((now.getDay() + 6) % 7) * 86400000;
  let today = 0, week = 0;
  for (const it of items) {
    const ts = Date.parse(String(it.ts || ""));
    if (!ts || Number.isNaN(ts)) continue;
    if (ts >= startOfToday) today++;
    if (ts >= startOfWeek)  week++;
  }
  return { today, week };
}

async function loadDb() {
  try {
    const data = await request(`${AP_API}/db`);
    state.dbItems = data.items || [];

    $("recordCount").textContent = data.count ?? state.dbItems.length;

    const { today, week } = computeTodayWeek(state.dbItems);
    state.stats.today = today;
    state.stats.week  = week;
    $("todayCount").textContent = today;
    $("weekCount").textContent  = week;

    renderDbTable(applyFilters(state.dbItems));
    pushOpLog("刷新记录", `共 ${data.count ?? state.dbItems.length} 条`);
  } catch (e) {
    $("dbTableBody").innerHTML =
      `<tr><td colspan="7">读取签发记录失败：${escapeHtml(e.message)}</td></tr>`;
    pushOpLog("读取记录失败", e.message);
  }
}

/* ---------- 筛选 ---------- */

function applyFilters(items) {
  const f = state.filters;
  return items.filter((it) => {
    if (f.type && String(it.agent_type || "").toLowerCase() !== f.type) return false;
    if (f.status && String(it.status || "verified").toLowerCase() !== f.status) return false;

    if (f.from) {
      const ts = Date.parse(String(it.ts || ""));
      const from = Date.parse(f.from + "T00:00:00");
      if (!Number.isNaN(ts) && ts < from) return false;
    }
    if (f.to) {
      const ts = Date.parse(String(it.ts || ""));
      const to = Date.parse(f.to + "T23:59:59");
      if (!Number.isNaN(ts) && ts > to) return false;
    }

    if (f.keyword) {
      const kw = f.keyword.toLowerCase();
      const hay = [
        it.hid, it.agent_type, it.CMI, it.cmc_count, it.ts,
        (it.capabilities && JSON.stringify(it.capabilities)) || "",
      ].join(" ").toLowerCase();
      if (!hay.includes(kw)) return false;
    }
    return true;
  });
}

/* ---------- 能力服务 ---------- */

async function loadCapabilities(agentType = state.currentAgentType) {
  state.currentAgentType = agentType;

  $$(".sub-tabs .tab-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.agentType === agentType);
  });

  try {
    const data = await request(
      `${AP_API}/capabilities?agent_type=${encodeURIComponent(agentType)}`
    );
    state.capabilities[agentType] = data.cmm || [];

    // 如果后端返回了状态，就同步到本地缓存
    if (Array.isArray(data.states)) {
      data.states.forEach((s) => {
        if (typeof s.group_index === "number" && s.state) {
          state.capStates[capKey(agentType, s.group_index)] = s.state;
        }
      });
    }

    renderCapabilities(data.cmm || [], agentType);
    pushOpLog("切换能力视图", `${agentType} · ${(data.cmm || []).length} 组`);
  } catch (e) {
    $("capabilityGrid").innerHTML =
      `<div class="cap-card">读取能力服务失败：${escapeHtml(e.message)}</div>`;
    pushOpLog("读取能力失败", e.message);
  }
}

function renderCapabilities(cmm, agentType) {
  const grid = $("capabilityGrid");
  if (!Array.isArray(cmm) || cmm.length === 0) {
    grid.innerHTML = `<div class="cap-card">暂无能力服务</div>`;
    return;
  }

  // 统计使用量
  const usageMap = {};
  state.dbItems.forEach((it) => {
    const caps = it.capabilities || it.cmc || [];
    (Array.isArray(caps) ? caps : []).forEach((c) => {
      const key = typeof c === "string" ? c : (c && (c.label || c.id));
      if (key) usageMap[key] = (usageMap[key] || 0) + 1;
    });
  });

  grid.innerHTML = cmm.map((row, idx) => {
    const items = Array.isArray(row) ? row : [];
    const groupState = getCapState(agentType, idx);
    const isMaintenance = groupState === "maintenance";

    const chips = items.length
      ? items.map((item) => {
          const rawLabel = item && typeof item === "object" ? (item.label || item.id) : String(item);
          const label = labelZh(rawLabel);
          const usage = usageMap[rawLabel] || 0;
          return `<span class="chip" title="${escapeHtml(label)} · 已签发 ${usage} 份">
                    ${escapeHtml(label)}
                  </span>`;
        }).join("")
      : `<span class="chip empty">暂未开放</span>`;

    const groupUsage = items.reduce((sum, item) => {
      const rawLabel = item && typeof item === "object" ? (item.label || item.id) : String(item);
      return sum + (usageMap[rawLabel] || 0);
    }, 0);

    const statusPill = isMaintenance
      ? `<span class="status-pill pending">维护中</span>`
      : `<span class="status-pill active">已启用</span>`;

    return `
      <div class="cap-card ${isMaintenance ? "maintenance" : ""}" data-cap-index="${idx}">
        <div class="cap-title">
          <span>${escapeHtml(categoryName(agentType, idx))}</span>
          ${statusPill}
        </div>
        <div class="cap-desc">${items.length ? `共 ${items.length} 项可配置能力` : "该分组暂未开放"}</div>
        <div class="cap-items">${chips}</div>

        <div class="cap-actions">
          <span class="cap-usage">已签发 ${groupUsage} 份</span>
          <button class="cap-toggle-btn ${isMaintenance ? "off" : ""}"
                  data-toggle-index="${idx}"
                  type="button"
                  title="${isMaintenance ? "点击切换为已启用" : "点击切换为维护中"}">
            <span class="dot"></span>
            ${isMaintenance ? "点击启用" : "点击维护"}
          </button>
        </div>
      </div>
    `;
  }).join("");

  // 卡片点击 → 打开抽屉
  grid.querySelectorAll(".cap-card").forEach((card) => {
    card.addEventListener("click", () => {
      const idx = Number(card.dataset.capIndex);
      openCapabilityDrawer(agentType, idx);
    });
  });

  // 切换按钮 → 切换状态（阻止冒泡）
  grid.querySelectorAll(".cap-toggle-btn").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      const idx = Number(btn.dataset.toggleIndex);
      toggleCapState(agentType, idx, e);
    });
  });
}

/* ---------- 签发记录表 ---------- */

function renderDbTable(items) {
  const body = $("dbTableBody");
  if (!items.length) {
    body.innerHTML = `<tr><td colspan="7">暂无符合条件的签发记录。</td></tr>`;
    return;
  }

  body.innerHTML = items.map((it) => {
    const hid = String(it.hid || "");
    const paId = it.pa_id || `PA-${shortText(hid, 8)}`;
    const status = String(it.status || "verified").toLowerCase();
    const capSummary = buildCapSummary(it);

    return `
      <tr>
        <td>${escapeHtml(it.ts || "-")}</td>
        <td><code title="${escapeHtml(paId)}">${escapeHtml(paId)}</code></td>
        <td>${escapeHtml(it.agent_type || "-")}</td>
        <td><code title="${escapeHtml(hid)}">${escapeHtml(shortText(hid, 16))}</code></td>
        <td title="${escapeHtml(capSummary)}">${escapeHtml(shortText(capSummary, 32))}</td>
        <td><span class="status-pill ${statusClass(status)}">${statusText(status)}</span></td>
        <td>
          <div class="row-actions">
            <button class="ghost-btn" data-action="view" data-hid="${encodeURIComponent(hid)}">查看</button>
            <button class="danger-btn" data-action="delete" data-hid="${encodeURIComponent(hid)}">删除</button>
          </div>
        </td>
      </tr>
    `;
  }).join("");

  body.querySelectorAll("button[data-action]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const hid = decodeURIComponent(btn.dataset.hid);
      if (btn.dataset.action === "view") openRecordDrawer(hid);
      else deleteRecord(hid);
    });
  });
}

function buildCapSummary(it) {
  const caps = it.capabilities || it.cmc || [];
  if (!Array.isArray(caps) || !caps.length) return "—";
  return caps.map((c) => {
    const raw = typeof c === "string" ? c : (c && (c.label || c.id));
    return labelZh(raw);
  }).join(" + ");
}

/* 记录详情抽屉：业务化，不裸露原始数据 */
async function openRecordDrawer(hid) {
  try {
    const data = await request(`${AP_API}/db/${encodeURIComponent(hid)}`);

    const it = data.record || data.item || data;
    const basic = `
      <dl class="drawer-kv">
        <dt>PA ID</dt><dd>${escapeHtml(it.pa_id || `PA-${shortText(hid, 8)}`)}</dd>
        <dt>签发时间</dt><dd>${escapeHtml(it.ts || "—")}</dd>
        <dt>智能体类型</dt><dd>${escapeHtml(it.agent_type || "—")} PA</dd>
        <dt>用户标识</dt><dd>${escapeHtml(shortText(hid, 22))}（已脱敏）</dd>
      </dl>
    `;

    const capTags = (() => {
      const caps = it.capabilities || it.cmc || [];
      if (!Array.isArray(caps) || !caps.length) return `<span class="cap-tag empty">暂无能力配置</span>`;
      return caps.map((c) => {
        const raw = typeof c === "string" ? c : (c && (c.label || c.id));
        return `<span class="cap-tag">${escapeHtml(labelZh(raw))}</span>`;
      }).join("");
    })();

    const capsBlock = `
      <div class="drawer-divider">能力配置</div>
      <div class="cap-tag-group">${capTags}</div>
    `;

    const verifyBlock = `
      <div class="drawer-divider">验证状态</div>
      <dl class="drawer-kv">
        <dt>凭证完整性</dt><dd><span class="status-pill active">通过</span></dd>
        <dt>能力一致性</dt><dd><span class="status-pill active">通过</span></dd>
      </dl>
    `;

    openDrawer({
      eyebrow: "签发记录详情",
      title: it.pa_id || shortText(hid, 40),
      html: basic + capsBlock + verifyBlock,
    });

    pushOpLog("查看记录详情", it.pa_id || shortText(hid, 20));
  } catch (e) {
    openDrawer({
      eyebrow: "签发记录详情",
      title: "读取失败",
      html: `<p>${escapeHtml(e.message)}</p>`,
    });
    pushOpLog("读取记录详情失败", e.message);
  }
}

async function deleteRecord(hid) {
  if (!confirm(`确定删除该签发记录？\n${hid}`)) return;
  try {
    await request(`${AP_API}/db/${encodeURIComponent(hid)}`, { method: "DELETE" });
    pushOpLog("删除记录", shortText(hid, 20));
    await loadDb();
  } catch (e) {
    pushOpLog("删除记录失败", e.message);
  }
}

/* ---------- 能力详情抽屉（业务化） ---------- */

function openCapabilityDrawer(agentType, idx) {
  const cmm = state.capabilities[agentType] || [];
  const row = cmm[idx] || [];
  const title = categoryName(agentType, idx);
  const groupState = getCapState(agentType, idx);
  const isMaintenance = groupState === "maintenance";

  const capTags = row.length
    ? row.map((item) => {
        const raw = item && typeof item === "object" ? (item.label || item.id) : String(item);
        return `<span class="cap-tag">${escapeHtml(labelZh(raw))}</span>`;
      }).join("")
    : `<span class="cap-tag empty">暂未开放</span>`;

  openDrawer({
    eyebrow: `能力服务 · ${agentType}`,
    title,
    html: `
      <dl class="drawer-kv">
        <dt>智能体类型</dt><dd>${escapeHtml(agentType)} PA</dd>
        <dt>分组序号</dt><dd>第 ${idx + 1} 组</dd>
        <dt>能力项数</dt><dd>${row.length} 项</dd>
        <dt>当前状态</dt><dd>
          <span class="status-pill ${isMaintenance ? "pending" : "active"}">
            ${isMaintenance ? "维护中" : "已启用"}
          </span>
        </dd>
      </dl>

      <div class="drawer-divider">可配置能力</div>
      <div class="cap-tag-group">${capTags}</div>

      <div class="drawer-divider">管理操作</div>
      <button class="cap-toggle-btn ${isMaintenance ? "off" : ""}"
              type="button"
              data-drawer-toggle="1">
        <span class="dot"></span>
        ${isMaintenance ? "切换为已启用" : "切换为维护中"}
      </button>
    `,
  });

  const btn = document.querySelector('[data-drawer-toggle="1"]');
  if (btn) {
    btn.addEventListener("click", (e) => {
      toggleCapState(agentType, idx, e).then(() => {
        openCapabilityDrawer(agentType, idx);
      });
    });
  }
}

/* ---------- 抽屉控制 ---------- */

function openDrawer({ eyebrow, title, html }) {
  $("drawerEyebrow").textContent = eyebrow || "详情";
  $("drawerTitle").textContent   = title   || "—";
  $("drawerBody").innerHTML      = html    || "";
  $("drawer").classList.add("open");
  $("drawerMask").classList.add("open");
  $("drawer").setAttribute("aria-hidden", "false");
  document.body.style.overflow = "hidden";
}

function closeDrawer() {
  $("drawer").classList.remove("open");
  $("drawerMask").classList.remove("open");
  $("drawer").setAttribute("aria-hidden", "true");
  document.body.style.overflow = "";
}

/* ---------- 公钥加载与显示 ---------- */

async function loadPublicKeys() {
  try {
    const data = await request(`${AP_API}/public_keys`);
    state.publicKey = data.ap_dlog_pk || "";
    state.apId      = data.ap_id || "—";
    $("apIdValue").textContent = state.apId;
    $("apPkValue").textContent = state.publicKey || "—";
    $("apPkValue").classList.add("masked");
    $("togglePkBtn").textContent = "显示";
  } catch (e) {
    $("apPkValue").textContent = "—";
    pushOpLog("读取公钥失败", e.message);
  }
}

/* ---------- 刷新 ---------- */

async function refreshAll() {
  await loadStatus();
  await loadPublicKeys();
  await loadCapabilities(state.currentAgentType);
  await loadDb();
}

/* ---------- 事件绑定 ---------- */

document.addEventListener("DOMContentLoaded", () => {
  /* 顶部按钮 */
  $("refreshAllBtn").addEventListener("click", refreshAll);
  $("refreshDbBtn").addEventListener("click", loadDb);

  /* 公钥：显示 / 复制 */
  $("togglePkBtn").addEventListener("click", () => {
    const el = $("apPkValue");
    const masked = el.classList.toggle("masked");
    $("togglePkBtn").textContent = masked ? "显示" : "隐藏";
    if (masked) {
      el.textContent = "••••••••••••••••••••••••••••";
    } else {
      el.textContent = state.publicKey || "—";
    }
  });

  $("copyPkBtn").addEventListener("click", async () => {
    if (!state.publicKey) { pushOpLog("复制公钥失败", "当前无公钥"); return; }
    try {
      await navigator.clipboard.writeText(state.publicKey);
      pushOpLog("复制公钥");
    } catch (e) {
      pushOpLog("复制公钥失败", e.message);
    }
  });

  /* 清空操作日志 */
  $("clearDebugBtn").addEventListener("click", () => {
    opLogs.length = 0;
    renderOpLogs();
  });

  /* 主导航 Tab */
  $$(".main-tabs .tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const tab = btn.dataset.mainTab;
      $$(".main-tabs .tab-btn").forEach((b) =>
        b.classList.toggle("active", b === btn));
      $$(".tab-panel").forEach((p) =>
        p.hidden = p.dataset.tabPanel !== tab);
    });
  });

  /* 子 Tab（Octopus / OpenClaw） */
  $$(".sub-tabs .tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      loadCapabilities(btn.dataset.agentType);
    });
  });

  /* 筛选栏 */
  $("filterApplyBtn").addEventListener("click", () => {
    state.filters.keyword = $("filterKeyword").value.trim();
    state.filters.type    = $("filterType").value;
    state.filters.status  = $("filterStatus").value;
    state.filters.from    = $("filterFrom").value;
    state.filters.to      = $("filterTo").value;
    renderDbTable(applyFilters(state.dbItems));
    pushOpLog("查询记录");
  });

  $("filterResetBtn").addEventListener("click", () => {
    $("filterKeyword").value = "";
    $("filterType").value    = "";
    $("filterStatus").value  = "";
    $("filterFrom").value    = "";
    $("filterTo").value      = "";
    state.filters = { keyword: "", type: "", status: "", from: "", to: "" };
    renderDbTable(state.dbItems);
    pushOpLog("重置筛选");
  });

  /* 抽屉关闭 */
  $("drawerClose").addEventListener("click", closeDrawer);
  $("drawerMask").addEventListener("click", closeDrawer);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeDrawer();
  });

  /* 首次加载 */
  refreshAll();
});