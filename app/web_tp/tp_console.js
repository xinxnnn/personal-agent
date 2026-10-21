const TP_API = "/v1/tp";

const state = {
  activeView: "review",
  selectedId: null,
  historyStatus: "",
  // 列表分页状态：全量缓存 / 当前页 / 空态文案，按容器 id 分别记录
  cache: {},
  pages: {},
  empties: {},
};

/* 每页条数。列表容器高度固定，卡片区大小不随申请条数变化，超出部分翻页查看 */
const PAGE_SIZE = 6;

const $ = (id) => document.getElementById(id);

function pretty(obj) {
  return JSON.stringify(obj ?? null, null, 2);
}
function safeText(value) { return String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
function objectValue(value) { if(typeof value==='string'){try{return JSON.parse(value);}catch{return {};}}return value&&typeof value==='object'?value:{}; }
function booleanValue(value) { if(value===true||value===1||value==='true'||value==='1')return true;if(value===false||value===0||value==='false'||value==='0')return false;return null; }

function showAlert(message) {
  const box = $("alert");
  box.textContent = message;
  box.classList.remove("hidden");
  setTimeout(() => box.classList.add("hidden"), 4500);
}

async function request(url, options = {}) {
  const res = await fetch(url, {
    headers: { "content-type": "application/json" },
    ...options,
  });

  // 会话失效时统一送回登录页，避免界面停在一个永远拉不到数据的状态
  if (res.status === 401) {
    location.replace("/tp/login?next=" + encodeURIComponent(location.pathname));
    throw new Error("登录状态已失效");
  }

  const data = await res.json().catch(() => ({}));
  if (!res.ok || data.success === false) { const error=data.detail || data.error || `HTTP ${res.status}`; throw new Error(typeof error==='string'?error:pretty(error)); }
  return data;
}

/* ---------- 登录身份显示与退出 ---------- */

(function initAuthBar() {
  const nameEl = $("userName");
  const roleEl = $("userRole");
  const avatarEl = document.querySelector(".user-chip-avatar");
  const btn = $("logoutBtn");

  request(`${TP_API}/me`)
    .then((data) => {
      const u = (data && data.user) || {};
      // 兼容两套字段名：后端已输出 username/display，早期版本返回的是 u/r/d
      const name = u.username || u.u || "";
      const role = u.display || u.d || "";
      if (nameEl) nameEl.textContent = name || "—";
      if (roleEl) roleEl.textContent = role || "—";
      if (avatarEl && name) avatarEl.textContent = name.charAt(0).toUpperCase();
    })
    .catch(() => {
      /* 未登录情形已由 request 统一跳转，这里无需额外处理 */
    });

  if (btn) {
    let busy = false;
    btn.addEventListener("click", async () => {
      if (busy) return;          // 连点会让第二次请求带着已吊销的令牌，无谓往返
      busy = true;
      btn.disabled = true;
      try {
        await request(`${TP_API}/logout`, { method: "POST" });
      } catch (e) {
        /* 无论登出接口成败，都回到登录页 */
      }
      location.replace("/tp/login");
    });
  }
})();

function normalizeApplications(data) {
  if (!data) return [];
  if (Array.isArray(data)) return data;
  if (Array.isArray(data.applications)) return data.applications;
  if (Array.isArray(data.items)) return data.items;
  if (Array.isArray(data.data)) return data.data;
  if(data.data && typeof data.data==='object')return normalizeApplications(data.data);
  return [];
}

function getAppId(app) {
  return app.request_id || app.id || app.requestId || "";
}

function getAppStatus(app) {
  return app.status || app.review?.decision || "unknown";
}

function getPt(app) {
  return objectValue(app.pt || app.payload || app.application?.pt);
}

function getChecks(app) {
  return objectValue(app.checks || app.application?.checks);
}

function getReview(app) {
  return app.review || app.application?.review || {};
}

function getResult(app) {
  return app.result || app.application?.result || {};
}

function getPHC(obj) {
  return obj?.phc || obj?.PHC || obj?.result?.phc || obj?.application?.result?.phc || null;
}

function maskId(value) {
  const s = String(value || "");
  if (s.length <= 6) return s || "-";
  return `${s.slice(0, 3)}****${s.slice(-3)}`;
}

/* 已脱敏的证件号（含 *）直接展示，不能再过一遍 maskId，
   否则 "IDC***56" 会被二次打码成 "IDC*****56" */
function displayId(value) {
  const s = String(value || "").trim();
  if (!s) return "-";
  return s.includes("*") ? s : maskId(s);
}

/* 审核项三态：true=通过 / false=未过 / null=尚无结论。
   列表接口对 pending 单返回 false（如人脸库不可达），不能吞成 "-" */
function tri(value) {
  value = booleanValue(value);
  if (value === true) return `<span class="ok">通过</span>`;
  if (value === false) return `<span class="bad">未过</span>`;
  return `<span>-</span>`;
}

/* 列表条目字段归一化。两种数据形态并存：
   - 列表接口 /applications 返回扁平 brief：name / id_number_masked / signature_valid ...
   - 详情接口 /applications/{id} 返回嵌套对象：pt.PII.name / checks.signature_valid ...
   此前列表只按嵌套路径取值，遇到扁平 brief 全部回退成 "-"。 */
function briefOf(app) {
  const pt = getPt(app);
  const pii = objectValue(pt.PII || pt.pii);
  const checks = getChecks(app);
  const fullId = pii.id_number || pii.idNumber || pt.ID || pt.id || app.id_number || "";
  return {
    name: app.name || pii.name || pt.name || "",
    idNumber: app.id_number_masked || fullId,
    idCard: app.id_card_number_masked || pii.id_card_number || "",
    email: app.email || pii.email || "",
    signature: checks.signature_valid ?? app.signature_valid,
    face: checks.face_verified ?? app.face_verified,
    af: checks.af_valid ?? app.af_valid,
  };
}

function boolMark(value) {
  value = booleanValue(value);
  if (value === true) return `<span class="ok">通过</span>`;
  if (value === false) return `<span class="bad">失败</span>`;
  return `<span>-</span>`;
}

/* ISO 时间 → "2026-07-04 06:01"，卡片里放不下毫秒级全串 */
function fmtTime(value) {
  const s = String(value || "");
  const m = s.match(/^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/);
  return m ? `${m[1]} ${m[2]}` : (s || "-");
}
const statusNames={pending:'待审核',issued:'已通过',rejected:'已拒绝'};
function statusName(value){return statusNames[value]||value||'未知状态';}

async function fetchApplications(status = "") {
  const q = status ? `?status=${encodeURIComponent(status)}` : "";
  return normalizeApplications(await request(`${TP_API}/applications${q}`));
}

async function fetchDetail(requestId) {
  return request(`${TP_API}/applications/${encodeURIComponent(requestId)}`);
}

function renderItem(app) {
  const id = getAppId(app);
  const b = briefOf(app);
  const active = state.selectedId === id ? " active" : "";

  return `
    <article class="item${active}" data-id="${safeText(id)}">
      <div class="item-title">
        <span>${safeText(b.name || "未命名")}</span>
        <span class="badge muted">${safeText(statusName(getAppStatus(app)))}</span>
      </div>
      <div class="item-meta">
        <span>身份标识 ${safeText(displayId(b.idNumber))}</span>
        <span>证件 ${safeText(displayId(b.idCard))}</span>
        <span>邮箱 ${safeText(b.email||'-')}</span>
      </div>
      <div class="item-meta">
        <span>申请时间 ${safeText(fmtTime(app.created_at || app.createdAt))}</span>
      </div>
    </article>
  `;
}

/* 分页条常驻：即使只有一页也渲染，让 panel 底部收口、高度恒定；
   只有一页（或空列表）时两个按钮都是禁用态。total=0 时 page=1、totalPages=1，
   下面两个 disabled 判断已覆盖，无需额外分支 */
function pagerHtml(page, totalPages, total) {
  return `
    <div class="pager">
      <span class="pager-info">共 ${total} 条 · 第 ${page} / ${totalPages} 页</span>
      <button class="ghost-btn pager-btn" data-dir="prev" type="button"${page <= 1 ? " disabled" : ""}>上一页</button>
      <button class="ghost-btn pager-btn" data-dir="next" type="button"${page >= totalPages ? " disabled" : ""}>下一页</button>
    </div>
  `;
}

/* 列表数据入口：缓存全量并回到第一页（每次重新拉取数据都从头看起） */
function renderList(targetId, apps, emptyText = "暂无数据") {
  state.cache[targetId] = apps;
  state.empties[targetId] = emptyText;
  state.pages[targetId] = 1;
  renderPage(targetId);
}

/* 只重绘当前页 —— 翻页纯前端切片，不再打接口 */
function renderPage(targetId) {
  const box = $(targetId);
  const apps = state.cache[targetId] || [];
  const emptyText = state.empties[targetId] || "暂无数据";

  const totalPages = Math.max(1, Math.ceil(apps.length / PAGE_SIZE));
  const page = Math.min(Math.max(1, state.pages[targetId] || 1), totalPages);
  state.pages[targetId] = page;
  const slice = apps.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  box.className = "list";
  box.innerHTML = `
    <div class="list-body${apps.length ? "" : " empty"}">
      ${apps.length ? slice.map(renderItem).join("") : `<p class="list-empty-text">${emptyText}</p>`}
    </div>
    ${pagerHtml(page, totalPages, apps.length)}
  `;

  box.querySelectorAll(".item").forEach((node) => {
    node.addEventListener("click", async () => {
      await loadDetail(node.dataset.id);
      if(targetId==='historyList')$("detailBox").scrollIntoView({behavior:'smooth',block:'start'});
    });
  });

  box.querySelectorAll(".pager-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.pages[targetId] = btn.dataset.dir === "prev" ? page - 1 : page + 1;
      renderPage(targetId);
    });
  });
}

function kv(label, value) {
  const shown = typeof value === "object" ? pretty(value) : String(value ?? "-");
  return `<div class="kv"><b>${safeText(label)}</b><span>${safeText(shown)}</span></div>`;
}

function renderDetail(app) {
  const id = getAppId(app);
  const pt = getPt(app);
  const checks = getChecks(app);
  const review = getReview(app);
  const result = getResult(app);
  const phc = getPHC(app) || result.phc || result.PHC;
  const pii=objectValue(pt.PII || pt.pii);

  $("detailStatus").textContent = statusName(getAppStatus(app));

  $("detailBox").className = "detail";
  $("detailBox").innerHTML = `
    <div class="applicant-summary">
      <div class="section-title">申领人基本信息</div>
      ${kv("姓名", pii.name)}
      ${kv("身份标识", displayId(pii.id_number || pt.ID || pt.id))}
      ${kv("证件号码", displayId(pii.id_card_number))}
      ${kv("电子邮箱", pii.email)}
      ${kv("申请时间", fmtTime(app.created_at || app.createdAt))}
    </div>
    <div class="check-summary">
      <div class="section-title">审核检查</div>
      ${kv("申请签名", booleanValue(checks.signature_valid)===true?'通过':booleanValue(checks.signature_valid)===false?'未通过':'待检查')}
      ${kv("身份关联", booleanValue(checks.af_valid)===true?'通过':booleanValue(checks.af_valid)===false?'未通过':'待检查')}
      ${kv("人脸核验", booleanValue(checks.face_verified)===true?'通过':booleanValue(checks.face_verified)===false?'未通过':'待检查')}
    </div>
    ${phc ? '<div class="trace-shortcut"><button id="traceFromApplication" class="ghost-btn" type="button">在身份追溯中查看此凭证 ↗</button></div>' : ''}

    <div>
      <div class="section-title">审核结论</div>
      ${kv("审核人", review.operator)}
      ${kv("决定", statusName(review.decision))}
      ${kv("原因", review.reason)}
      ${kv("意见", review.comment)}
      ${kv("审核时间", fmtTime(review.reviewed_at))}
    </div>

    ${getAppStatus(app) === "pending" ? renderReviewForm(id) : ""}

    <details class="technical-details"><summary>展开凭证与技术详情</summary>
      <div class="section-title">申请记录</div>${kv("request_id", id)}${kv("status", getAppStatus(app))}${kv("updated_at", app.updated_at || app.updatedAt)}
      <div class="section-title">提交数据与检查参数</div>${kv("PII", pt.PII || pt.pii)}${kv("BI", pt.BI || pt.bi)}${kv("ID", pt.ID || pt.id)}${kv("AF", pt.AF)}${kv("AF_calc", pt.AF_calc || checks.AF_calc)}${kv("pk_ap", pt.pk_ap)}${kv("r_bind", pt.r_bind)}${kv("timestamp", pt.timestamp)}
      ${kv("signature_valid", checks.signature_valid)}${kv("af_valid", checks.af_valid)}${kv("face_verified", checks.face_verified)}${kv("db_available", checks.db_available)}${kv("face_record_found", checks.face_record_found)}${kv("face_check_ms", checks.face_check_ms)}${kv("perf_tp_verify_user_ms", checks.perf_tp_verify_user_ms)}
      <div class="section-title">签发结果</div>${phc ? renderPHCSummary(phc) : "<div class='empty'>暂无签发结果</div>"}<pre class="json-box">${safeText(pretty(phc || result))}</pre>
    </details>
  `;

  const approveBtn = $("approveBtn");
  const rejectBtn = $("rejectBtn");
  if (approveBtn) approveBtn.addEventListener("click", () => submitReview(id, "approve"));
  if (rejectBtn) rejectBtn.addEventListener("click", () => submitReview(id, "reject"));
  const traceButton=$("traceFromApplication");
  if(traceButton)traceButton.addEventListener('click',()=>openTraceFromApplication(phc));
}

function renderReviewForm() {
  return `
    <div>
      <div class="section-title">审核操作</div>
      <label>审核人</label>
      <input id="reviewOperator" value="tp_admin" />
      <label>审核原因</label>
      <select id="reviewReason">
        <option value="manual_approved">人工审核通过</option>
        <option value="face_verification_failed">人脸核验未通过</option>
        <option value="invalid_information">申请资料有误</option>
        <option value="other">其他</option>
      </select>
      <label>审核意见</label>
      <input id="reviewComment" value="人工审核通过" />
      <div class="actions">
        <button id="rejectBtn" class="primary-btn danger">拒绝申请</button>
        <button id="approveBtn" class="primary-btn">通过并签发身份凭证</button>
      </div>
    </div>
  `;
}

function renderPHCSummary(phc) {
  const scid = phc.SCID || phc.scid || {};
  const tpa = phc.TPA || phc.tpa || {};
  const aso = phc.ASO || phc.aso || {};
  return `
    ${kv("PHC.id", phc.id)}
    ${kv("DID", phc.DID || phc.did)}
    ${kv("SCID.AF", scid.AF)}
    ${kv("SCID.RF", scid.RF)}
    ${kv("SCID.CID", scid.CID)}
    ${kv("SCID.CID_enc", scid.CID_enc)}
    ${kv("SCID.CRF", scid.CRF)}
    ${kv("ASO.TPM.AF", aso.TPM?.AF)}
    ${kv("TPA.TPid", tpa.TPid)}
    ${kv("TPproof", tpa.TPproof)}
  `;
}

async function loadPending() {
  try {
    const apps = await fetchApplications("pending");
    $("pendingCount").textContent = String(apps.length);
    renderList("pendingList", apps, "暂无待审核申请");
  } catch (err) {
    showAlert(err.message);
  }
}

/* 顶部统计卡：一次拉全量列表本地计数，不额外开后端接口 */
async function loadStats() {
  try {
    const apps = await fetchApplications();
    const count = (s) => apps.filter((a) => getAppStatus(a) === s).length;
    const set = (id, value) => {
      const el = $(id);
      if (el) el.textContent = String(value);
    };
    set("statPending", count("pending"));
    set("statIssued", count("issued"));
    set("statRejected", count("rejected"));
    set("statTotal", apps.length);
    const bars=$("applicationBars");
    if(bars){
      bars.replaceChildren();
      for(const [status,label] of [['pending','待审核'],['issued','已通过'],['rejected','已拒绝']]){
        const amount=count(status);const row=document.createElement('div');row.className='status-bar';
        const title=document.createElement('span');title.textContent=label;
        const track=document.createElement('div');track.className='status-track';
        const fill=document.createElement('span');fill.className='status-fill '+status;fill.style.width=`${apps.length?amount/apps.length*100:0}%`;track.append(fill);
        const value=document.createElement('b');value.textContent=String(amount);
        row.append(title,track,value);bars.append(row);
      }
    }
  } catch (err) {
    /* 统计失败不阻断主流程，界面上保留 "-" */
  }
}

async function loadHistory() {
  try {
    const apps = await fetchApplications(state.historyStatus);
    renderList("historyList", apps, "暂无历史申请");
  } catch (err) {
    showAlert(err.message);
  }
}

async function loadDetail(requestId) {
  try {
    state.selectedId = requestId;
    const detail = await fetchDetail(requestId);
    const app = detail.application || detail;
    renderDetail(app);
    // 只重绘选中态，保留当前页码；重新拉数据会把用户从第 N 页拽回第 1 页
    renderPage("pendingList");
    if(state.cache.historyList)renderPage("historyList");
  } catch (err) {
    showAlert(err.message);
  }
}

async function submitReview(requestId, action) {
  const operator = $("reviewOperator").value.trim() || "tp_admin";
  const reason = $("reviewReason").value.trim() || "manual_approved";
  const comment = $("reviewComment").value.trim();
  const url = `${TP_API}/applications/${encodeURIComponent(requestId)}/${action}`;

  try {
    const data = await request(url, {
      method: "POST",
      body: JSON.stringify({ operator, reason, comment }),
    });
    showAlert(action === "approve" ? "审核通过，身份凭证已签发" : "已拒绝申请");
    await loadDetail(requestId);
    await loadPending();
    await loadHistory();
    await loadStats();
  } catch (err) {
    showAlert(err.message);
  }
}

async function loadKeys() {
  const button=$("keysBtn");button.disabled=true;
  $("keysStatus").textContent='正在读取当前公钥…';
  try{
    $("keysResult").textContent=pretty(await request(`${TP_API}/public_keys`));
    $("keysResult").hidden=false;$("keysStatus").textContent='公钥参数已更新。';
  }catch(err){$("keysStatus").textContent='读取失败：'+err.message;showAlert(err.message);}
  finally{button.disabled=false;}
}

function setTraceMode(mode){
  document.querySelectorAll('.trace-tab').forEach(tab=>{
    const active=tab.dataset.trace===mode;tab.classList.toggle('active',active);
    tab.setAttribute('aria-selected',String(active));tab.tabIndex=0;
  });
  document.querySelectorAll('[data-trace-panel]').forEach(panel=>panel.hidden=panel.dataset.tracePanel!==mode);
  if(mode==='keys'&&$("keysResult").hidden)loadKeys();
}

function traceError(error){
  const code=String(error.message||'');
  const messages={did_not_found:'没有找到这个 DID 对应的身份记录。',invalid_scid_rf:'凭证关联信息无法解读。',missing_cid:'凭证缺少身份记录位置。',secinfo_not_found:'没有找到身份记录内容。',secinfo_decrypt_failed:'身份记录无法解密。','Invalid PHC structure or missing proof':'凭证结构或签名信息不完整。'};
  return messages[code]||code;
}

async function queryIdentity(){
  const did=$("revealDid").value.trim();
  if(!did.startsWith('did:')){ $("revealStatus").textContent='请输入完整的 DID（以 did: 开头）。';$("revealStatus").dataset.state='error';$("revealDid").focus();return; }
  const button=$("revealBtn");button.disabled=true;
  $("revealStatus").textContent='正在查询身份记录…';$("revealStatus").dataset.state='loading';$("revealSummary").hidden=true;$("revealRaw").hidden=true;
  try{
    const data=await request(`${TP_API}/reveal`,{method:'POST',body:JSON.stringify({did})});
    const pii=objectValue(data.pii);const box=$("revealSummary");box.replaceChildren();
    for(const [label,value] of [['姓名',pii.name],['身份标识',displayId(pii.id_number||data.id)],['证件号码',displayId(pii.id_card_number)],['电子邮箱',pii.email],['DID',data.did||did]]){
      const row=document.createElement('div');row.className='kv';const key=document.createElement('b');key.textContent=label;const val=document.createElement('span');val.textContent=String(value||'—');row.append(key,val);box.append(row);
    }
    box.hidden=false;$("revealResult").textContent=pretty(data);$("revealRaw").hidden=false;
    $("revealStatus").textContent='身份记录已找到。';$("revealStatus").dataset.state='success';
  }catch(err){$("revealStatus").textContent=traceError(err);$("revealStatus").dataset.state='error';}
  finally{button.disabled=false;}
}

async function verifyCredential(){
  const raw=$("phcInput").value.trim();let parsed;
  try{parsed=JSON.parse(raw);}catch{$("verifyStatus").textContent='JSON 格式有误，请检查括号和引号。';$("verifyStatus").dataset.state='error';$("verifyResult").hidden=true;return;}
  const phc=parsed?.PHC||parsed?.phc||parsed;
  if(!phc||typeof phc!=='object'||Array.isArray(phc)){$("verifyStatus").textContent='请输入完整的 PHC 对象。';$("verifyStatus").dataset.state='error';$("verifyResult").hidden=true;return;}
  const button=$("verifyBtn");button.disabled=true;$("verifyStatus").textContent='正在核验凭证…';$("verifyStatus").dataset.state='loading';$("verifyResult").hidden=true;
  try{
    const data=await request(`${TP_API}/verify_phc`,{method:'POST',body:JSON.stringify({phc})});
    $("verifyStatus").textContent=data.verified===true?'核验通过：凭证结构与签名有效。':'核验未通过。';$("verifyStatus").dataset.state=data.verified===true?'success':'error';
    $("verifyResult").textContent=pretty(data);$("verifyResult").hidden=false;
  }catch(err){$("verifyStatus").textContent='核验失败：'+traceError(err);$("verifyStatus").dataset.state='error';}
  finally{button.disabled=false;}
}

function openTraceFromApplication(phc){
  const did=phc.DID||phc.did||phc.ASO?.TPM?.CDID||'';
  $("phcInput").value=pretty(phc);
  switchView('trace');
  if(did){$("revealDid").value=String(did);setTraceMode('identity');queryIdentity();}
  else{setTraceMode('credential');$("verifyStatus").textContent='凭证已带入，可以直接核验。';$("verifyStatus").dataset.state='loading';}
  $("view-trace").scrollIntoView({behavior:'smooth',block:'start'});
}

function switchView(view) {
  state.activeView = view;
  document.querySelectorAll(".nav-btn").forEach((b) => b.classList.toggle("active", b.dataset.view === view));
  document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
  $(`view-${view}`).classList.add("active");

  // 统计卡常驻视图上方，切视图时顺手刷新，数字不会停在旧值
  loadStats();
  if (view === "review") {loadPending();loadHistory();}
}

function bindEvents() {
  document.querySelectorAll(".nav-btn").forEach((btn) => {
    btn.addEventListener("click", () => switchView(btn.dataset.view));
  });

  document.querySelectorAll(".filter").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".filter").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      state.historyStatus = btn.dataset.status || "";
      loadHistory();
    });
  });

  $("refreshBtn").addEventListener("click", () => {
    switchView(state.activeView);
    if(state.activeView==='trace'){
      const mode=document.querySelector('.trace-tab.active')?.dataset.trace;
      if(mode==='keys')loadKeys();
      else if(mode==='identity'&&$("revealDid").value.trim())queryIdentity();
      else if(mode==='credential'&&$("phcInput").value.trim())verifyCredential();
    }
  });
  $("keysBtn").addEventListener("click", loadKeys);
  const traceTabs=[...document.querySelectorAll('.trace-tab')];
  traceTabs.forEach((tab,index)=>{
    tab.addEventListener('click',()=>setTraceMode(tab.dataset.trace));
    tab.addEventListener('keydown',event=>{
      const offset=event.key==='ArrowRight'?1:event.key==='ArrowLeft'?-1:0;
      if(!offset)return;event.preventDefault();
      const next=traceTabs[(index+offset+traceTabs.length)%traceTabs.length];setTraceMode(next.dataset.trace);next.focus();
    });
  });
  $("revealBtn").addEventListener("click",queryIdentity);
  $("revealDid").addEventListener('input',()=>{$("revealSummary").hidden=true;$("revealRaw").hidden=true;$("revealStatus").textContent='DID 已更新，请重新查询。';delete $("revealStatus").dataset.state;});
  $("revealDid").addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();queryIdentity();}});
  $("verifyBtn").addEventListener("click",verifyCredential);
  $("phcInput").addEventListener('input',()=>{$("verifyResult").hidden=true;$("verifyStatus").textContent='凭证已更新，请重新核验。';delete $("verifyStatus").dataset.state;});
  $("clearPhcBtn").addEventListener('click',()=>{$("phcInput").value='';$("verifyStatus").textContent='已清空，请粘贴需要核验的凭证。';$("verifyResult").hidden=true;$("phcInput").focus();});
}

bindEvents();
switchView("review");   // 初次进入：激活审核中心并拉取统计与待审核列表
