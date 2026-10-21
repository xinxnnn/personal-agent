<template>
  <div class="app-wrapper">
    <!-- Top Navigation Bar -->
    <header class="app-header">
      <div class="header-inner">
        <div class="brand">
          <span class="logo-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24">
              <path d="M12 2.6 L19.2 5.5 V11.3 C19.2 15.4 16.3 18.8 12 20.2 C7.7 18.8 4.8 15.4 4.8 11.3 V5.5 Z"
                    fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/>
              <circle cx="12" cy="10.1" r="2.2" fill="none" stroke="currentColor" stroke-width="1.7"/>
              <path d="M7.9 16.9 C8.7 15.0 10.2 14.0 12 14.0 C13.8 14.0 15.3 15.0 16.1 16.9"
                    fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/>
            </svg>
          </span>
          <h1 class="app-title">个人 Agent 申领与管理系统</h1>
        </div>
        <div class="header-right">
          <!-- 当前操作者：账号 + 角色 + 退出合成一个整体。
               原先「表单姓名 / 登录账号 / 退出按钮」三块并排，
               姓名与账号信息重复，视觉上也散。 -->
          <div class="user-block">
            <div class="user-avatar">{{ (loginUser || 'U').charAt(0).toUpperCase() }}</div>
            <div class="user-meta">
              <span class="user-name">{{ loginUser || '—' }}</span>
              <span class="user-role">{{ loginRole || '本地用户' }}</span>
            </div>
            <button class="icon-logout" type="button" title="退出登录"
                    aria-label="退出登录" @click="logout">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                   stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
                <polyline points="16 17 21 12 16 7" />
                <line x1="21" y1="12" x2="9" y2="12" />
              </svg>
            </button>
          </div>
        </div>
      </div>
    </header>

    <main class="app-content">
      <!-- User Information Section -->
      <el-card class="box-card section-card" shadow="hover">
        <template #header>
          <div class="card-header">
            <span class="header-title">用户基本信息</span>
            <p class="card-desc">填写姓名与证件信息，作为 PHC 申请时的身份核验依据。</p>
          </div>
        </template>
        <el-form label-position="top" size="default">
          <el-row :gutter="20">
            <el-col :span="12"><el-form-item label="姓名"><el-input v-model="name" placeholder="请输入姓名" /></el-form-item></el-col>
            <el-col :span="12"><el-form-item label="ID"><el-input v-model="idnum" placeholder="请输入ID" /></el-form-item></el-col>
            <el-col :span="12"><el-form-item label="身份证号"><el-input v-model="idcard" placeholder="请输入身份证号" /></el-form-item></el-col>
            <el-col :span="12"><el-form-item label="Email"><el-input v-model="email" placeholder="请输入邮箱" /></el-form-item></el-col>
            <el-col :span="12"><el-form-item label="Passport"><el-input v-model="passport" placeholder="请输入护照号" /></el-form-item></el-col>
            <el-col :span="12">
              <el-form-item label="人脸照片">
                <div class="file-upload-wrapper">
                  <input ref="picfile" type="file" accept="image/*" class="custom-file-input" />
                </div>
              </el-form-item>
            </el-col>
          </el-row>
        </el-form>
      </el-card>

      <!-- Agent Configuration Process -->
      <el-card class="box-card section-card" shadow="hover">
        <template #header>
          <div class="card-header">
            <span class="header-title">配置个人智能体流程</span>
            <p class="card-desc">按步骤申领 PHC、选择 PA 配置并完成智能体绑定。</p>
          </div>
        </template>
        <el-timeline class="custom-timeline">
          <!-- Step 1: Request PHC -->
          <el-timeline-item :type="statusType(1)" :color="statusColor(1)" :hollow="stage < 1">
            <div class="timeline-content">
              <h3 class="step-title">1. 请求 PHC</h3>
              <div class="action-area phc-actions">
                <el-button size="small" @click="toggleShow('phc')">
                  {{ showPhc ? '收起详情' : '查看详情' }}
                </el-button>

                <el-button
                  type="primary"
                  :disabled="phcPending || successIssue || stage > 1"
                  :loading="loadingIssue"
                  @click="issue"
                  round
                >
                  请求 PHC
                </el-button>

                <el-button
                  v-if="phcPending && phcRequestId"
                  type="warning"
                  :loading="loadingCheckPhc"
                  @click="checkPhcApplication"
                  round
                >
                  查询 TP 审核结果
                </el-button>

                <el-tag
                  v-if="phcPending"
                  type="warning"
                  effect="plain"
                  class="status-tag phc-status-tag"
                >
                  待 TP 审核
                </el-tag>

                <el-tag
                  v-else-if="successIssue"
                  type="success"
                  effect="plain"
                  class="status-tag phc-status-tag"
                >
                  已签发
                </el-tag>
              </div>
            </div>
            <div v-if="showPhc" class="detail-box">
              <pre>{{ phcText || '暂无数据' }}</pre>
            </div>
          </el-timeline-item>

          <!-- Step 2: Select Configuration -->
          <el-timeline-item :type="statusType(2)" :color="statusColor(2)" :hollow="stage < 2">
            <div class="timeline-content">
              <h3 class="step-title">2. 选择 PA 的配置信息</h3>
              <div class="action-area">
                <el-button type="primary" :disabled="!canFetchCmm || stage>2" :loading="loadingCmm" @click="fetchcmm" round>
                 加载配置
                </el-button>
                <el-tag type="success" effect="dark" v-if="successCmm" class="status-tag">成功</el-tag>
              </div>
             </div>

             <!-- 新增：PA 类型选择 -->
             <div class="agent-type-box">
               <div class="agent-type-title">请选择要生成的 PA 类型</div>
               <el-radio-group v-model="agentType" :disabled="stage >= 3">
                 <el-radio-button label="octopus">Octopus PA</el-radio-button>
                 <el-radio-button label="openclaw">OpenClaw PA</el-radio-button>
               </el-radio-group>

             <div class="agent-type-desc">
                 <span v-if="agentType === 'octopus'">
                   Octopus：普通能力型个人智能体，适合文本处理、新闻查询、支付、联网搜索等能力。
                 </span>
               <span v-else>
                   OpenClaw：本地设备控制型个人智能体，适合 Gateway、文件访问、Shell、浏览器、聊天渠道等能力。
                 </span>
               </div>

               <div v-if="agentType === 'openclaw'" class="dependency-panel">
                 <div class="dependency-panel-header">
                   <div>
                     <div class="dependency-title">OpenClaw 安装前环境检查</div>
                     <div class="dependency-subtitle">检测本机是否已安装 Node.js、Git 和 clawhub；缺失时请先补齐环境，再继续创建和安装 skills。</div>
                   </div>
                   <div class="dependency-actions">
                     <el-button
                       v-if="dependencyMessage"
                       size="small"
                       @click="toggleShow('openclawDeps')"
                     >
                       {{ showOpenClawDeps ? '收起详情' : '查看详情' }}
                     </el-button>
                     <el-button size="small" :loading="loadingDeps" @click="checkOpenClawDependencies">
                       检测环境
                     </el-button>
                     <el-tag
                       v-if="dependencyStatus.ready_for_openclaw"
                       type="success"
                       effect="dark"
                     >
                       可安装 OpenClaw
                     </el-tag>
                     <el-tag
                       v-else-if="dependencyStatus.checked"
                       type="warning"
                       effect="dark"
                     >
                       依赖未齐全
                     </el-tag>
                   </div>
                 </div>

                 <div class="dependency-grid">
                   <div class="dependency-item">
                     <div class="dependency-name">Node.js</div>
                     <div class="dependency-meta">
                       <el-tag :type="dependencyTagType(dependencyStatus.node.installed)">
                         {{ dependencyLabel(dependencyStatus.node.installed) }}
                       </el-tag>
                       <span class="dependency-version">{{ dependencyStatus.node.version || '未检测到版本' }}</span>
                     </div>
                   </div>

                   <div class="dependency-item">
                     <div class="dependency-name">Git</div>
                     <div class="dependency-meta">
                       <el-tag :type="dependencyTagType(dependencyStatus.git.installed)">
                         {{ dependencyLabel(dependencyStatus.git.installed) }}
                       </el-tag>
                       <span class="dependency-version">{{ dependencyStatus.git.version || '未检测到版本' }}</span>
                     </div>
                   </div>

                   <div class="dependency-item">
                     <div class="dependency-name">ClawHub CLI</div>
                     <div class="dependency-meta">
                       <el-tag :type="dependencyTagType(clawhubStatus.ready)">
                         {{ clawhubStatus.ready ? '可用' : (clawhubStatus.installed ? '已安装但不可用' : '未安装') }}
                       </el-tag>
                       <span class="dependency-version">{{ clawhubStatus.version || '未检测到版本' }}</span>
                     </div>
                   </div>
                 </div>

                 <div class="dependency-install-actions">
                   <el-button
                     plain
                     :disabled="dependencyStatus.node.installed"
                     @click="openDependencyDownload('node')"
                    >
                     下载 Node.js
                   </el-button>
                   <el-button
                     plain
                     :disabled="dependencyStatus.git.installed"
                     @click="openDependencyDownload('git')"
                    >
                     下载 Git
                   </el-button>
                   <el-button
                     v-if="!dependencyStatus.ready_for_openclaw"
                     type="primary"
                     plain
                     :loading="loadingDeps"
                     @click="checkOpenClawDependencies"
                   >
                     下载完成后重新检测
                   </el-button>
                   <el-button
                     type="primary"
                     plain
                     :loading="installingClawhub"
                     :disabled="clawhubStatus.ready"
                     @click="installClawhub"
                   >
                     安装 ClawHub
                   </el-button>
                   <el-button
                     plain
                     @click="openClawhubDownload"
                   >
                     查看 ClawHub 安装说明
                   </el-button>
                 </div>

                 <div v-if="showOpenClawDeps" class="dependency-result">
                   <pre>{{ dependencyMessage || '暂无 OpenClaw 环境检测详情' }}</pre>
                   <pre v-if="clawhubMessage" style="margin-top: 12px;">{{ clawhubMessage }}</pre>
                 </div>
               </div>

               <div v-if="agentType === 'openclaw' && !successCmm" class="inline-config-hint">
                 <el-alert
                   title="请先完成安装环境检查，然后点击“加载配置”，加载成功后才会展开基本功能和安装 Skill 配置。"
                   type="info"
                   :closable="false"
                   show-icon
                 />
               </div>

               <div v-if="agentType === 'openclaw' && successCmm" class="llm-config-area">
                 <div class="config-category">
                   <div class="config-group-title">🧠 选择大模型提供商与模型</div>
                   <el-form :inline="true" size="small" class="llm-form">
                     <el-form-item label="提供商">
                       <el-select v-model="llmConfig.provider" placeholder="选择提供商" @change="onLlmProviderChange" style="width: 200px;">
                         <el-option
                           v-for="p in llmProviders"
                           :key="p.key"
                           :label="p.name"
                           :value="p.key"
                         />
                       </el-select>
                     </el-form-item>
                     <el-form-item label="模型">
                       <el-select v-model="llmConfig.model" placeholder="选择模型" style="width: 220px;">
                         <el-option
                           v-for="m in currentProviderModels"
                           :key="m"
                           :label="m"
                           :value="m"
                         />
                       </el-select>
                     </el-form-item>
                
                     <el-form-item label="Base URL (可选)">
                       <el-input
                         v-model="llmConfig.base_url"
                         placeholder="留空则使用默认"
                         style="width: 280px;"
                       />
                     </el-form-item>
                   </el-form>
                   <div class="llm-hint">
                     {{ currentProviderName }} · 默认 Base URL：{{ currentProviderBaseUrl || '(官方默认)' }}
                   </div>
                 </div>
               </div>

               <div v-if="agentType === 'openclaw' && successCmm" class="hooks-selection-area">
                 <div class="config-category">
                   <div class="config-group-title">⚙️ 选择要启用的基本功能</div>
                   <div class="hooks-grid">
                     <div
                       v-for="hook in AVAILABLE_HOOKS"
                       :key="hook.id"
                       class="hook-item"
                       :class="{ 'hook-selected': openclawHooksSelected[hook.field] }"
                       @click="toggleOpenClawHook(hook.field)"
                     >
                       <div class="hook-header">
                         <span class="hook-emoji">{{ hook.emoji }}</span>
                         <span class="hook-name">{{ hook.name }}</span>
                         <el-tag v-if="hook.recommended" size="small" type="success">推荐</el-tag>
                       </div>
                       <div class="hook-desc" v-html="hook.desc"></div>
                     </div>
                   </div>
                 </div>
               </div>

               <div v-if="agentType === 'openclaw' && successCmm" class="inline-skills-panel">
                 <div class="config-category">
                   <div class="config-group-title">🔧 安装 Skill</div>

                   <div class="skills-user-row">
                     <el-tag type="info">当前为预选模式，创建 OpenClaw 时会自动一起安装</el-tag>
                     <el-tag v-if="currentPhcId" type="success">当前 PHC ID：{{ currentPhcId }}</el-tag>
                   </div>

                   <div class="skills-hint">
                     这里选择的是创建时要自动安装的 skills，不需要先有 PHC，也不需要先创建实例。
                   </div>

                   <div class="skills-grid">
                     <div
                       v-for="skill in availableSkills"
                       :key="skill.slug"
                       class="skill-card-item"
                       :class="{ 'skill-selected': skillsSelected.includes(skill.slug) }"
                       @click="toggleSkill(skill.slug)"
                     >
                       <div class="skill-header">
                         <span class="skill-emoji">{{ skill.emoji || '🔧' }}</span>
                         <span class="skill-name">{{ skill.name }}</span>
                         <el-tag v-if="skill.recommended" size="small" type="success">推荐</el-tag>
                       </div>
                       <div class="skill-desc">{{ skill.description }}</div>
                     </div>
                   </div>

                   <div class="skills-actions">
                     <el-button
                       type="primary"
                       @click="applySkillsInstall"
                       :disabled="!clawhubStatus.ready"
                       round
                     >
                       📦 预选这些 Skill
                     </el-button>
                     <el-button
                       v-if="skillsInstallDetail"
                       text
                       bg
                       @click="toggleShow('skillsInstallDetail')"
                     >
                       {{ showSkillsInstallDetail ? '收起详情' : '查看详情' }}
                     </el-button>
                     <el-button
                       plain
                       @click="openSkillsSearchPage"
                       round
                     >
                       🔍 前往 ClawHub 搜索页
                     </el-button>
                     <el-button
                       plain
                       @click="refreshInstalledSkills"
                       :disabled="!skillsUserName"
                       round
                     >
                       🔄 刷新 Skill 状态
                     </el-button>
                   </div>

                   <div class="skills-search-section">
                     <div class="search-input-group">
                       <el-input
                         v-model="searchKeyword"
                         placeholder="搜索 ClawHub 上的技能..."
                         :disabled="!clawhubStatus.ready"
                         style="flex: 1"
                         size="default"
                       >
                         <template #append>
                           <el-button @click="searchClawHub" :loading="searchLoading" :disabled="!clawhubStatus.ready">搜索</el-button>
                         </template>
                       </el-input>
                     </div>
                     <div v-if="searchResults" class="search-results">
                       <pre>{{ searchResults }}</pre>
                     </div>
                   </div>

                   <div v-if="skillsProgress" class="skills-progress">
                     <el-progress :percentage="skillsProgress.percent" :status="skillsProgress.status"></el-progress>
                     <p class="progress-message">{{ skillsProgress.message }}</p>
                   </div>

                   <div
                     v-if="installResult"
                     class="skills-install-result"
                     :class="installResult.success ? 'result-success' : 'result-error'"
                   >
                     <div class="result-header">
                       <strong>{{ installResult.success ? '✅ 安装完成' : '❌ 安装失败' }}</strong>
                       <span v-if="installResult.installed && installResult.installed.length">
                         已安装: {{ installResult.installed.join(', ') }}
                       </span>
                     </div>
                     <div v-if="installResult.failed && installResult.failed.length" class="result-detail">
                       <span>失败: {{ installResult.failed.join(', ') }}</span>
                     </div>
                   </div>

                   <div v-if="skillsInstallDetail && showSkillsInstallDetail" class="dependency-result">
                     <pre>{{ skillsInstallDetail }}</pre>
                   </div>
                 </div>
               </div>
             </div>

             <div v-if="agentType === 'octopus' && successCmm" id="cmm_ui" v-html="cmmHtml" class="dynamic-form-area"></div>
            </el-timeline-item>

          <!-- Step 3: Submit Configuration -->
          <el-timeline-item :type="statusType(3)" :color="statusColor(3)" :hollow="stage < 3">
            <div class="timeline-content">
              <h3 class="step-title">3. 提交 PA 的配置信息</h3>
              <div class="action-area">
                <el-button size="small" @click="toggleShow('pa')">
                  {{ showPa ? '收起详情' : '查看详情' }}
                </el-button>
                <el-button type="primary" :disabled="!canSubmitCmc || stage>3" :loading="loadingSubmit" @click="submitcmc" round>
                  提交配置
                </el-button>
                <el-tag type="success" effect="dark" v-if="successSubmit" class="status-tag">成功</el-tag>
              </div>
            </div>
            <div v-if="showPa" class="detail-box">
              <pre>{{ paCmmText || '暂无数据' }}</pre>
            </div>
          </el-timeline-item>

          <!-- Step 4: Create Agent -->
          <el-timeline-item :type="statusType(4)" :color="statusColor(4)" :hollow="stage < 4">
            <div class="timeline-content">
              <h3 class="step-title">4. 创建个人智能体</h3>
              <div class="action-area">
                <el-button size="small" @click="toggleShow('agent')">
                  {{ showAgent ? '收起详情' : '查看详情' }}
                </el-button>
                <el-button type="success" :disabled="!canCreateAgent || stage>4" :loading="loadingCreate" @click="createAgent" round>
                  立即创建
                </el-button>
                <el-tag type="success" effect="dark" v-if="successCreate" class="status-tag">成功</el-tag>
              </div>
            </div>
            <div v-if="showAgent" class="detail-box">
              <pre>{{ agentOut || '暂无数据' }}</pre>
            </div>
            <div v-if="successCreate && createdAgentInfo" class="created-agent-info">
              <div class="created-agent-info-header">
                <div>
                  <span class="created-agent-eyebrow">CREATED AGENT</span>
                  <h4>个人智能体已创建</h4>
                </div>
                <el-tag type="success">{{ createdAgentInfo.agentType }}</el-tag>
              </div>
              <p class="created-agent-summary">以下信息可用于后续更新、故障恢复和本地运行定位。</p>
              <div class="created-agent-grid">
                <div><span>智能体 ID</span><strong>{{ createdAgentInfo.agentId || '未返回' }}</strong></div>
                <div><span>个人身份 DID</span><strong>{{ createdAgentInfo.did || '未返回' }}</strong></div>
                <div><span>PHC ID</span><strong>{{ createdAgentInfo.phcId || '未返回' }}</strong></div>
                <div><span>AP ID</span><strong>{{ createdAgentInfo.apId || '未返回' }}</strong></div>
                <div><span>能力模块</span><strong>{{ createdAgentInfo.features || '未配置' }}</strong></div>
              </div>
              <div class="created-agent-paths" v-if="createdAgentInfo.agentPath || createdAgentInfo.launcher">
                <div v-if="createdAgentInfo.agentPath"><span>本地目录</span><code>{{ createdAgentInfo.agentPath }}</code></div>
                <div v-if="createdAgentInfo.launcher"><span>启动入口</span><code>{{ createdAgentInfo.launcher }}</code></div>
              </div>
            </div>
          </el-timeline-item>
        </el-timeline>
      </el-card>

      <!-- Update Configuration -->
      <el-card class="box-card section-card" shadow="hover">
        <template #header>
          <div class="card-header">
            <span class="header-title">更新 PA 配置</span>
            <p class="card-desc">已绑定智能体后，可在此提交新的 PA 配置更新。</p>
          </div>
        </template>
        <div class="update-type-selector" style="margin-bottom: 12px;">
          <el-radio-group v-model="updateAgentType" size="small">
            <el-radio-button label="octopus">Octopus PA</el-radio-button>
            <el-radio-button label="openclaw">OpenClaw PA</el-radio-button>
          </el-radio-group>
        </div>
        <div class="update-actions">
          <div class="action-group">
            <el-button :disabled="!idnum" :loading="loadingUpdateInit" @click="updatepa" plain type="primary">
              {{ updateAgentType === 'openclaw' ? '1. 获取已安装技能' : '1. 获取配置' }}
            </el-button>
            <el-tag type="success" effect="plain" v-if="successUpdateInit">已获取</el-tag>
          </div>
          <div class="arrow-divider">➜</div>
          <div class="action-group">
            <el-button type="primary" :disabled="!canSubmitUpdate" :loading="loadingUpdateSubmit" @click="submitUpdate" round>
              {{ updateAgentType === 'openclaw' ? '2. 更新已安装技能' : '2. 提交更新' }}
            </el-button>
            <el-tag type="success" effect="dark" v-if="successUpdateSubmit">更新成功</el-tag>
          </div>
        </div>

        <div v-if="updateAgentType === 'octopus'" id="upd_cmm_ui" v-html="updCmmHtml" class="dynamic-form-area" style="margin-top: 20px;"></div>
        <div v-else class="dynamic-form-area" style="margin-top: 20px;">
          <div class="config-category">
            <div class="config-group-title">当前实例已安装 Skill</div>
            <div v-if="installedSkillsList.length === 0" class="empty-config-tip">当前还没有已安装的 skill。可先在上面的安装 Skill 区预选或安装新 skill。</div>
            <div v-else class="installed-skills-list">
              <div v-for="skill in installedSkillsList" :key="skill.slug" class="installed-skill-row">
                <span class="skill-pill">{{ skill.slug }}</span>
                <div class="installed-skill-actions">
                  <el-button
                    size="small"
                    plain
                    :loading="singleSkillActionLoading === `update:${skill.slug}`"
                    @click="updateOneInstalledSkill(skill.slug)"
                  >
                    更新
                  </el-button>
                  <el-button
                    size="small"
                    plain
                    type="danger"
                    :loading="singleSkillActionLoading === `remove:${skill.slug}`"
                    @click="uninstallOneInstalledSkill(skill.slug)"
                  >
                    卸载
                  </el-button>
                </div>
              </div>
            </div>
          </div>

          <div class="config-category">
            <div class="config-group-title">搜索并安装新 Skill</div>
            <div class="skills-search-section" style="margin-top: 0;">
              <div class="search-input-group">
                <el-input
                  v-model="updateSearchKeyword"
                  placeholder="搜索 ClawHub 上的新技能..."
                  :disabled="!clawhubStatus.ready"
                  style="flex: 1"
                  size="default"
                >
                  <template #append>
                    <el-button @click="searchClawHubForUpdate" :loading="updateSearchLoading" :disabled="!clawhubStatus.ready">搜索</el-button>
                  </template>
                </el-input>
              </div>
              <div v-if="updateSearchResults" class="search-results">
                <pre>{{ updateSearchResults }}</pre>
              </div>
            </div>

            <div class="skills-actions">
              <el-input
                v-model="updateInstallSkillSlug"
                placeholder="输入要安装的新 skill slug，例如 weather"
                :disabled="!clawhubStatus.ready || !skillsOpenclawPath"
                style="width: 320px"
                size="default"
              />
              <el-button
                type="primary"
                :loading="updateInstallLoading"
                :disabled="!clawhubStatus.ready || !skillsOpenclawPath || !updateInstallSkillSlug.trim()"
                @click="installNewSkillForUpdate"
                round
              >
                安装新 Skill
              </el-button>
            </div>
          </div>
        </div>

        <transition name="el-fade-in">
          <div v-if="updateText" class="result-section">
            <el-divider content-position="left">更新结果详情</el-divider>
            <div class="result-header">
              <span class="result-label">服务器返回信息</span>
              <el-button text bg size="small" @click="toggleShow('update')">
                {{ showUpdate ? '收起' : '展开' }}
              </el-button>
            </div>
            <div v-show="showUpdate" class="detail-box">
              <pre>{{ updateText }}</pre>
            </div>
          </div>
        </transition>
      </el-card>

      <!-- Recovery Section -->
      <el-card class="box-card section-card warning-card" shadow="hover">
        <template #header>
          <div class="card-header warning-header">
            <span class="header-title">故障恢复 (Recovery)</span>
            <p class="card-desc">PHC 或绑定关系丢失时，通过恢复流程重新取回。</p>
          </div>
        </template>

        <div class="recovery-item recovery-independent">
          <div class="recovery-info">
            <h4>1. 提交恢复身份</h4>
            <p class="sub-text">填写创建 PA 时使用的身份信息。系统会校验 PII/BI 是否与签发时一致，身份通过后才允许恢复 PA。</p>
          </div>
          <div class="recovery-form">
            <div class="recovery-form-section">
              <div class="recovery-section-heading">
                <span class="recovery-section-index">PII</span>
                <div><strong>身份识别信息</strong><small>用于派生 HID 并定位身份记录</small></div>
              </div>
              <div class="recovery-form-grid">
                <label class="recovery-field"><span>姓名 <em>必填</em></span><el-input v-model="recoveryName" placeholder="请输入姓名" clearable /></label>
                <label class="recovery-field"><span>身份证号 <em>必填</em></span><el-input v-model="recoveryIdnum" placeholder="请输入身份证号" clearable /></label>
                <label class="recovery-field"><span>证件编号</span><el-input v-model="recoveryIdcard" placeholder="请输入证件编号" clearable /></label>
                <label class="recovery-field"><span>邮箱</span><el-input v-model="recoveryEmail" placeholder="请输入邮箱" clearable /></label>
              </div>
            </div>
            <div class="recovery-form-section">
              <div class="recovery-section-heading">
                <span class="recovery-section-index bi-index">BI</span>
                <div><strong>生物与辅助信息</strong><small>必须与创建时提交的信息一致</small></div>
              </div>
              <div class="recovery-form-grid">
                <label class="recovery-field"><span>Passport</span><el-input v-model="recoveryPassport" placeholder="请输入 Passport" clearable /></label>
                <label class="recovery-field recovery-upload-field"><span>生物特征照片</span><input ref="recoveryPicfile" type="file" accept="image/*" class="recovery-file-input" /><small>如签发时提交过照片，请重新上传</small></label>
              </div>
            </div>
            <div class="recovery-form-section recovery-index-section">
              <div class="recovery-section-heading">
                <span class="recovery-section-index did-index">DID</span>
                <div><strong>辅助索引</strong><small>已有 DID 时填写，HID 无法命中时用于定位历史 PHC</small></div>
              </div>
              <label class="recovery-field recovery-did-field"><span>已有 DID</span><el-input v-model="recoveryDid" placeholder="可选，不填写则仅用 HID 定位" clearable /></label>
            </div>
          </div>
        </div>

        <el-divider></el-divider>

        <div class="recovery-item">
          <div class="recovery-info">
            <h4>2A. PHC 与 PA 都丢失</h4>
            <p class="sub-text">先校验 PII/BI 身份并恢复 PHC，通过后再恢复对应的 PA。</p>
          </div>
          <div class="recovery-actions">
            <el-button type="warning" :loading="loadingRecoverBoth" @click="recoverboth" plain>恢复 PHC & PA</el-button>
            <el-tag type="success" effect="dark" v-if="successRecoverBoth">成功</el-tag>
            <el-button text bg size="small" v-if="paRecoverBothText" @click="toggleShow('recoverBoth')">{{ showRecoverBoth ? '收起详情' : '查看详情' }}</el-button>
          </div>
          <div v-if="showRecoverBoth && paRecoverBothText" class="detail-box"><pre>{{ paRecoverBothText }}</pre></div>
        </div>

        <el-divider></el-divider>

        <div class="recovery-item">
          <div class="recovery-info">
            <h4>2B. 仅 PA 丢失</h4>
            <p class="sub-text">已持有 PHC 时，直接提交 PHC + HID 恢复 PA，无需再次校验身份。</p>
          </div>
          <div class="recovery-actions">
            <el-button type="warning" :loading="loadingRecoverPa" @click="recoverpa" plain>仅恢复 PA</el-button>
            <el-tag type="success" effect="dark" v-if="successRecoverPa">成功</el-tag>
            <el-button text bg size="small" v-if="paRecoverPaText" @click="toggleShow('recoverPa')">{{ showRecoverPa ? '收起详情' : '查看详情' }}</el-button>
          </div>
          <div v-if="showRecoverPa && paRecoverPaText" class="detail-box"><pre>{{ paRecoverPaText }}</pre></div>
        </div>
      </el-card>

      <!-- Multi-Agent Management Section - 添加在 Recovery Section 后面 -->
<el-card
  v-if="agentType === 'openclaw' && successCreate"
  class="box-card section-card"
  shadow="hover"
>
  <template #header>
    <div class="card-header">
      <span class="header-title">多智能体管理</span>
      <p class="card-desc">管理同一账号下的多个 Personal Agent 及其父级关系。</p>
    </div>
  </template>

  <!-- 创建子 Agent -->
  <div class="sub-agent-create">
    <h4>创建子智能体</h4>
    <el-form :inline="true" size="small">
      <el-form-item label="名称">
        <el-input v-model="newSubAgent.name" placeholder="如: helper, researcher" style="width: 150px" />
      </el-form-item>
      <el-form-item label="描述">
        <el-input v-model="newSubAgent.description" placeholder="智能体描述" style="width: 200px" />
      </el-form-item>
      <el-form-item label="能力">
        <el-select v-model="newSubAgent.capabilities" multiple placeholder="选择能力" style="width: 250px">
          <el-option label="浏览器控制" value="browser" />
          <el-option label="文件访问" value="file_access" />
          <el-option label="Shell 执行" value="shell" />
          <el-option label="画布" value="canvas" />
          <el-option label="WebChat" value="webchat" />
          <el-option label="记忆" value="memory" />
        </el-select>
      </el-form-item>
      <el-form-item>
        <el-button type="primary" :loading="creatingSubAgent" @click="createSubAgent">
          创建子智能体
        </el-button>
      </el-form-item>
    </el-form>
  </div>

  <el-divider />

  <!-- Agent 组列表 -->
  <div v-if="agentGroups.length === 0" class="empty-config-tip">
    暂无子智能体，请先创建
  </div>

  <div v-for="group in agentGroups" :key="group.group_id" class="agent-group-panel">
    <div class="group-header">
      <h4>{{ group.group_name }}</h4>
      <el-tag type="info">主 Agent: {{ group.parent_agent_id }}</el-tag>
    </div>

    <div class="sub-agents-list">
      <div v-for="agent in group.sub_agents" :key="agent.id" class="sub-agent-card">
        <div class="agent-header">
          <span class="agent-name">{{ agent.name }}</span>
          <el-tag :type="getStatusType(agent.status)" size="small">{{ agent.status }}</el-tag>
        </div>
        <div class="agent-info">
          <div><strong>ID:</strong> {{ agent.id }}</div>
          <div><strong>PHC ID:</strong> {{ agent.phc_id }}</div>
          <div><strong>网关端口:</strong> {{ agent.gateway_port }}</div>
          <div><strong>Token:</strong> {{ agent.token ? agent.token.substring(0, 16) + '...' : 'N/A' }}</div>
        </div>
        <div class="agent-actions">
          <el-button size="small" plain @click="deploySubAgent(agent.id)">部署</el-button>
          <el-button size="small" plain @click="startSubAgent(agent.id)">启动</el-button>
          <el-button size="small" plain type="danger" @click="deleteSubAgent(agent.id)">删除</el-button>
        </div>
      </div>
    </div>

    <div class="group-actions">
      <el-button size="small" plain @click="downloadBridgeScript(group.group_id)">
        下载通信桥接脚本
      </el-button>
      <el-button size="small" plain @click="viewGroupConfig(group)">
        查看组配置
      </el-button>
    </div>

    <!-- 组配置详情 -->
    <div v-if="showGroupConfig === group.group_id" class="detail-box">
      <pre>{{ JSON.stringify(group, null, 2) }}</pre>
    </div>
  </div>
</el-card>



    </main>
  </div>
</template>

<script>
// ==================== 全局 401 兜底 ====================
// 会话过期时统一回登录页，避免界面停在一个永远拉不到数据的状态。
// 置于组件定义之前，覆盖本文件后续全部 fetch 调用。
(function () {
  const originalFetch = window.fetch;
  window.fetch = function (...args) {
    return originalFetch.apply(this, args).then(function (res) {
      if (res.status === 401) {
        location.replace('/user/login');
      }
      return res;
    });
  };
})();

const AVAILABLE_HOOKS = [
  {
    id: 'session-memory',
    field: 'session_memory',
    emoji: '💾',
    name: '会话记忆备份',
    desc: '执行 <code>/new</code> 或 <code>/reset</code> 时，自动保存上一轮对话的最后15条消息到记忆文件',
    recommended: true
  },
  {
    id: 'bootstrap-extra-files',
    field: 'bootstrap_extra_files',
    emoji: '📎',
    name: '额外引导文件注入',
    desc: 'Agent 启动时自动注入额外的 <code>AGENTS.md</code>、<code>TOOLS.md</code> 等引导文件',
    recommended: false
  },
  {
    id: 'command-logger',
    field: 'command_logger',
    emoji: '📝',
    name: '命令审计日志',
    desc: '将所有斜杠命令记录到 <code>~/.openclaw/logs/commands.log</code>，JSONL 格式',
    recommended: true
  },
  {
    id: 'boot-md',
    field: 'boot_md',
    emoji: '🚀',
    name: '启动脚本执行',
    desc: 'Gateway 启动时自动执行 <code>BOOT.md</code> 中的指令，适合初始化检查',
    recommended: false
  }
];

export default {
  name: 'UserApp',
  data(){
    return {
      loginUser: '',
      loginRole: '',
      tpBase: 'http://127.0.0.1:8111',
      apBase: 'http://127.0.0.1:8112',
      // 新增：当前选择的 PA 类型
      agentType: 'openclaw',
      // 更新 PA 配置区独立选择的 PA 类型（octopus / openclaw）
      updateAgentType: 'octopus',
      name: 'Alice', idnum: 'ID123', idcard: 'IDCARD123456', email: 'alice@example.com', passport: 'P123456789',
      phcObj: null, paObj: null, cmmObj: null, cmcObj: null,
      phcText: '', paCmmText: '', hashCH: '', hashCCH: '', hashStatus: '', paRecoverPaText: '', paRecoverBothText: '', updateText: '', agentOut: '',
      createdAgentInfo: null,
      canFetchCmm: false, canCreateAgent: false, canRecoverPa: false, canSubmitCmc: false, canSubmitUpdate: false,
      cmmSk: '', cmmPk: '', updSk: '', updPk: '', lastCMM: null,
      cmmHtml: '', updCmmHtml: '',
      stage: 0,
      phcRequestId: '',
      phcPending: false,
      loadingCheckPhc: false,
      showPhc: false,
      showPa: false,
      showAgent: false,
      showOpenClawDeps: false,
      showUpdate: false,
      showRecoverBoth: false,
      showRecoverPa: false,
      showSkillsInstallDetail: false,
      loadingIssue: false,
      loadingCmm: false,
      loadingSubmit: false,
      loadingCreate: false,
      loadingUpdateInit: false,
      loadingUpdateSubmit: false,
      loadingRecoverBoth: false,
      loadingRecoverPa: false,
      loadingClawhub: false,
      installingClawhub: false,
      successIssue: false,
      successCmm: false,
      successSubmit: false,
      successCreate: false,
      successUpdateInit: false,
      successUpdateSubmit: false,
      successRecoverBoth: false,
      successRecoverPa: false,
      recoveryName: '',
      recoveryIdnum: '',
      recoveryIdcard: '',
      recoveryEmail: '',
      recoveryPassport: '',
      recoveryDid: '',
      loadingDeps: false,
      installingDeps: '',
      dependencyMessage: '',
      clawhubMessage: '',
      skillsUserName: '',
      skillsSelected: [],
      skillsInstallLoading: false,
      searchKeyword: '',
      searchLoading: false,
      searchResults: null,
      updateSearchKeyword: '',
      updateSearchLoading: false,
      updateSearchResults: null,
      updateInstallSkillSlug: '',
      updateInstallLoading: false,
      singleSkillActionLoading: '',
      skillsProgress: null,
      installResult: null,
      skillsInstallDetail: '',
      skillsOpenclawPath: '',
      installedSkillsList: [],
      availableSkills: [],
      openclawHooksSelected: {
        session_memory: false,
        bootstrap_extra_files: false,
        command_logger: false,
        boot_md: false
      },
      llmProviders: [],
      llmConfig: {
        provider: 'deepseek',
        model: 'deepseek-v4-pro',
      },
      dependencyStatus: {
        checked: false,
        ready_for_openclaw: false,
        winget: { installed: false, path: '' },
        node: { installed: false, version: '', path: '', download_url: 'https://nodejs.org/en/download' },
        git: { installed: false, version: '', path: '', download_url: 'https://git-scm.com/download/win' }
      },
      clawhubStatus: {
        checked: false,
        installed: false,
        ready: false,
        version: '',
        path: '',
        download_url: 'https://www.npmjs.com/package/clawhub',
        install_command: 'npm install -g clawhub --registry=https://registry.npmmirror.com'
      },
      newSubAgent: {
        name: '',
        description: '',
        capabilities: []
      },
      creatingSubAgent: false,
      agentGroups: [],
      showGroupConfig: null,


    }
  },
  computed: {
    AVAILABLE_HOOKS() {
      return AVAILABLE_HOOKS;
    },
    currentPhcId() {
      return (this.phcObj && this.phcObj.id) ? this.phcObj.id : '';
    },
    currentProviderModels() {
      const p = this.llmProviders.find(x => x.key === this.llmConfig.provider);
      return p ? p.models : [];
    },
    currentProviderName() {
      const p = this.llmProviders.find(x => x.key === this.llmConfig.provider);
      return p ? p.name : (this.llmConfig.provider || '');
    },
    currentProviderBaseUrl() {
      const p = this.llmProviders.find(x => x.key === this.llmConfig.provider);
      return p ? p.default_base_url : '';
    }
  },
  mounted() {
    this.loadLoginUser();
    this.loadLastAgent();
    if (this.agentType === 'openclaw') {
      this.checkOpenClawDependencies();
      this.checkClawhub();
      this.loadRecommendedSkills();
    }
  },
  watch: {
    agentType(){
      // 如果还没提交配置，可以切换类型并清空旧 CMM
      if (this.stage < 3) {
        this.cmmObj = null;
        this.cmcObj = null;
        this.cmmHtml = '';
        this.canSubmitCmc = false;
        this.successCmm = false;
      }

      if (this.agentType !== 'openclaw') {
        this.showOpenClawDeps = false;
      }

      if (this.agentType === 'openclaw' && !this.dependencyStatus.checked) {
        this.checkOpenClawDependencies();
      }

      if (this.agentType === 'openclaw' && !this.clawhubStatus.checked) {
        this.checkClawhub();
      }

      if (this.agentType === 'openclaw' && this.availableSkills.length === 0) {
        this.loadRecommendedSkills();
      }
    }
  },
  methods: {
    // ---------- 登录身份 ----------
    async loadLoginUser() {
      try {
        const r = await fetch('/user/api/me', { credentials: 'same-origin' });
        if (!r.ok) return;
        const d = await r.json();
        const u = (d && d.user) || {};
        // 兼容两套字段名：后端已输出 username/display，早期版本返回的是 u/r/d
        this.loginUser = u.username || u.u || '';
        this.loginRole = u.display || u.d || '';
      } catch (e) {
        // 未登录场景由全局 401 兜底处理
      }
    },

    async logout() {
      if (this._loggingOut) return;   // 连点会让第二次请求带着已吊销的令牌
      this._loggingOut = true;
      try {
        await fetch('/user/api/logout', { method: 'POST', credentials: 'same-origin' });
      } catch (e) {
        // 无论登出接口成败，都回到登录页
      }
      location.replace('/user/login');
    },

    normalizeInstalledSkillsPayload(data) {
      if (!data) return [];

      if (Array.isArray(data.installed_skills)) {
        return data.installed_skills.map(item => {
          if (typeof item === 'string') {
            return {
              slug: item,
              path: '',
              has_skill_md: true
            };
          }
          return {
            slug: item.slug || '',
            path: item.path || '',
            has_skill_md: item.has_skill_md !== false
          };
        }).filter(item => item.slug);
      }

      if (Array.isArray(data.installed_skill_slugs)) {
        return data.installed_skill_slugs.map(slug => ({
          slug,
          path: '',
          has_skill_md: true
        }));
      }

      return [];
    },

    dependencyTagType(installed){
      return installed ? 'success' : 'danger';
    },

    dependencyLabel(installed){
      return installed ? '已安装' : '未安装';
    },

    async fetchLlmProviders(){
      try {
        const r = await fetch('/user/llm_providers');
        const data = await r.json();
        if (data && data.success && Array.isArray(data.providers)) {
          this.llmProviders = data.providers;
          const cur = this.llmProviders.find(x => x.key === this.llmConfig.provider);
          if (cur) {
            if (!this.llmConfig.model || !cur.models.includes(this.llmConfig.model)) {
              this.llmConfig.model = cur.default_model;
            }
          }
        }
      } catch (e) {
        console.warn('fetchLlmProviders failed', e);
      }
    },
    onLlmProviderChange(val){
      const cur = this.llmProviders.find(x => x.key === val);
      if (cur) {
        this.llmConfig.model = cur.default_model;
        
      }
    },

    async checkOpenClawDependencies(){
      this.loadingDeps = true;
      this.dependencyMessage = '';

      try {
        await this.fetchLlmProviders();
        
        const r = await fetch('/user/openclaw/dependencies');
        const data = await r.json();

        this.dependencyStatus = {
          checked: true,
          ready_for_openclaw: !!data.ready_for_openclaw,
          winget: data.winget || { installed: false, path: '' },
          node: data.node || { installed: false, version: '', path: '', download_url: 'https://nodejs.org/en/download' },
          git: data.git || { installed: false, version: '', path: '', download_url: 'https://git-scm.com/download/win' }
        };

        this.dependencyMessage = JSON.stringify(data, null, 2);
      } catch (e) {
        this.dependencyMessage = '环境检测失败：' + (e && e.message ? e.message : 'unknown');
      } finally {
        this.loadingDeps = false;
      }
    },

    async installDependencies(target){
      this.installingDeps = target;

      try {
        const r = await fetch('/user/openclaw/install_dependencies', {
          method: 'POST',
          headers: {'content-type': 'application/json'},
          body: JSON.stringify({ target })
        });
        const data = await r.json();
        this.dependencyMessage = JSON.stringify(data, null, 2);
      } catch (e) {
        this.dependencyMessage = '拉起安装器失败：' + (e && e.message ? e.message : 'unknown');
      } finally {
        this.installingDeps = '';
      }
    },

    openDependencyDownloads(){
      const nodeUrl = this.dependencyStatus.node.download_url || 'https://nodejs.org/en/download';
      const gitUrl = this.dependencyStatus.git.download_url || 'https://git-scm.com/download/win';
      window.open(nodeUrl, '_blank', 'noopener');
      window.open(gitUrl, '_blank', 'noopener');
    },

    openDependencyDownload(target){
      const urlMap = {
        node: this.dependencyStatus.node.download_url || 'https://nodejs.org/en/download',
        git: this.dependencyStatus.git.download_url || 'https://git-scm.com/download/win'
      };
      const url = urlMap[target];
      if (url) {
        window.open(url, '_blank', 'noopener');
        this.dependencyMessage = '下载安装完成后，请点击“下载完成后重新检测”确认环境是否已就绪。';
      }
    },

    async checkClawhub(){
      this.loadingClawhub = true;
      this.clawhubMessage = '';
      try {
        const r = await fetch('/skills/check-clawhub');
        const data = await r.json();
        this.clawhubStatus = {
          checked: true,
          installed: !!data.installed,
          ready: !!data.ready,
          version: data.version || '',
          path: data.path || '',
          download_url: data.download_url || 'https://www.npmjs.com/package/clawhub',
          install_command: data.install_command || 'npm install -g clawhub --registry=https://registry.npmmirror.com'
        };
        this.clawhubMessage = JSON.stringify(data, null, 2);
        if (data.installed && !data.ready) {
          this.clawhubMessage += '\n\n[ERROR] 当前机器虽然检测到了 clawhub，但它无法正常执行。通常是 node 环境、PATH 或 PowerShell 启动方式有问题。请重新安装后再检测。';
        }
      } catch (e) {
        this.clawhubMessage = 'ClawHub 检测失败：' + (e && e.message ? e.message : 'unknown');
      } finally {
        this.loadingClawhub = false;
      }
    },

    async installClawhub(){
      this.installingClawhub = true;
      try {
        const r = await fetch('/skills/install-clawhub', {
          method: 'POST',
          headers: {'content-type': 'application/json'}
        });
        const data = await r.json();
        this.clawhubMessage = JSON.stringify(data, null, 2);
        if (data.success) {
          this.$message && this.$message.success ? this.$message.success('ClawHub 安装完成，请重新检测。') : null;
        }
      } catch (e) {
        this.clawhubMessage = 'ClawHub 安装失败：' + (e && e.message ? e.message : 'unknown');
      } finally {
        this.installingClawhub = false;
      }
    },

    openClawhubDownload(){
      window.open(this.clawhubStatus.download_url || 'https://www.npmjs.com/package/clawhub', '_blank', 'noopener');
      this.clawhubMessage = '如果自动安装失败，请手动执行：npm install -g clawhub --registry=https://registry.npmmirror.com ，安装完成后点击“安装完成后重新检测”。';
    },

    toggleOpenClawHook(field) {
      this.openclawHooksSelected[field] = !this.openclawHooksSelected[field];
    },

    async loadRecommendedSkills() {
      try {
        const response = await fetch('/skills/recommended');
        const data = await response.json();
        if (data.success && Array.isArray(data.skills)) {
          this.availableSkills = data.skills;
          const validSlugs = new Set(data.skills.map(skill => skill.slug));
          this.skillsSelected = this.skillsSelected.filter(slug => validSlugs.has(slug));
          return;
        }
      } catch (e) {
      }
      this.availableSkills = [
        { slug: 'weather', name: '天气查询', description: '查询实时天气和天气预报（无需API密钥）', recommended: true, emoji: '🌤️' },
        { slug: 'github', name: 'GitHub集成', description: 'Issues管理、PR查看、CI状态查询', recommended: true, emoji: '🐙' },
        { slug: 'desearch-web-search', name: '联网搜索', description: 'Desearch 网络搜索', recommended: true, emoji: '🔍' }
      ];
      const validSlugs = new Set(this.availableSkills.map(skill => skill.slug));
      this.skillsSelected = this.skillsSelected.filter(slug => validSlugs.has(slug));
    },

    toggleSkill(slug) {
      const index = this.skillsSelected.indexOf(slug);
      if (index > -1) {
        this.skillsSelected.splice(index, 1);
      } else {
        this.skillsSelected.push(slug);
      }
    },

    async searchClawHub() {
      if (!this.searchKeyword.trim()) {
        this.$message && this.$message.warning ? this.$message.warning('请输入搜索关键词') : null;
        return;
      }
      if (!this.clawhubStatus.ready) {
        this.$message && this.$message.warning ? this.$message.warning('请先安装 ClawHub') : null;
        return;
      }
      this.searchLoading = true;
      this.searchResults = null;
      try {
        const response = await fetch(`/skills/search?keyword=${encodeURIComponent(this.searchKeyword)}`);
        const data = await response.json();
        if (data.success) {
          this.searchResults = data.output;
        } else {
          const message = data.error || '搜索失败';
          this.searchResults = message;
          this.$message && this.$message.error ? this.$message.error(message) : null;
        }
      } catch (error) {
        this.$message && this.$message.error ? this.$message.error('请求失败: ' + error.message) : null;
      } finally {
        this.searchLoading = false;
      }
    },

    async applySkillsInstall() {
      if (this.skillsSelected.length === 0) {
        this.$message && this.$message.warning ? this.$message.warning('请至少选择一个技能') : null;
        return;
      }
      if (!this.clawhubStatus.ready) {
        this.$message && this.$message.warning ? this.$message.warning('请先安装 ClawHub') : null;
        return;
      }
      this.skillsInstallDetail = JSON.stringify({
        mode: 'preselect',
        selected_skills: this.skillsSelected
      }, null, 2);
      this.$message && this.$message.success ? this.$message.success(`已预选 ${this.skillsSelected.length} 个 skills，创建 OpenClaw 时会自动安装。`) : null;
    },

    pollInstallStatus(sessionId) {
      const interval = setInterval(async () => {
        try {
          const response = await fetch(`/skills/status/${sessionId}`);
          const data = await response.json();
          if (data.status === 'installing') {
            this.skillsProgress = { percent: 60, message: data.message, status: null };
          } else if (data.status === 'completed') {
            clearInterval(interval);
            const hasInstalled = !!data.installed && data.installed.length > 0;
            const hasFailed = !!data.failed && data.failed.length > 0;
            this.skillsProgress = { percent: 100, message: hasFailed ? '安装已结束（含失败项）' : '安装完成！', status: hasFailed ? 'warning' : 'success' };
            if (data.failed && data.failed.length > 0) {
              const failedNames = data.failed.map(f => f.slug).join(', ');
              this.$message && this.$message.error ? this.$message.error(`${data.failed.length} 个技能安装失败: ${failedNames}`) : null;
            }
            if (data.installed && data.installed.length > 0) {
              this.$message && this.$message.success ? this.$message.success(`成功安装 ${data.installed.length} 个技能`) : null;
            }
            this.installResult = {
              success: !!data.installed && data.installed.length > 0,
              installed: data.installed || [],
              failed: (data.failed || []).map(f => f.slug)
            };
            this.skillsInstallDetail = JSON.stringify(data, null, 2);
            this.skillsInstallLoading = false;
            this.skillsSelected = [];
          } else if (data.status === 'failed') {
            clearInterval(interval);
            this.skillsProgress = { percent: 100, message: data.message || '安装失败', status: 'exception' };
            this.skillsInstallDetail = JSON.stringify(data, null, 2);
            this.$message && this.$message.error ? this.$message.error('技能安装失败') : null;
            this.skillsInstallLoading = false;
          }
        } catch (error) {
          clearInterval(interval);
          this.skillsProgress = { percent: 100, message: '查询状态失败: ' + error.message, status: 'exception' };
          this.skillsInstallDetail = '查询状态失败: ' + error.message;
          this.skillsInstallLoading = false;
        }
      }, 2000);
    },

    openSkillsSearchPage() {
      window.open('https://clawhub.ai/', '_blank', 'noopener');
    },

    async refreshInstalledSkills() {
      if (!this.skillsUserName) {
        return;
      }
      try {
        const response = await fetch(`/skills/installed/${encodeURIComponent(this.skillsUserName)}`);
        const data = await response.json();
        if (data.success) {
          this.installedSkillsList = this.normalizeInstalledSkillsPayload(data);
          if (!this.skillsOpenclawPath && data.instance_dir) {
            this.skillsOpenclawPath = data.instance_dir;
          }
        } else {
          this.$message && this.$message.error ? this.$message.error(data.error || '获取已安装 skills 失败') : null;
        }
      } catch (error) {
        this.$message && this.$message.error ? this.$message.error('刷新 skills 状态失败: ' + error.message) : null;
      }
    },

    normalizeLabel(opt){
    const val = opt && (opt.label !== undefined && opt.label !== null ? opt.label : opt.id);
    const raw = val ? String(val) : '';
    return raw.toLowerCase().trim().replace(/\s+/g, '').replace(/_/g, '-');
  },

  getRawLabel(opt){
    const val = opt && (opt.label !== undefined && opt.label !== null ? opt.label : opt.id);
    return val ? String(val) : '';
  },

  isAppearanceOpt(opt){
    const norm = this.normalizeLabel(opt);
    return norm.includes('appearance');
  },

  labelToZh(opt){
    const raw = this.getRawLabel(opt);
    const norm = this.normalizeLabel(opt);

    const zhLabelMap = {
      'text': '文本',
      'voice': '语音',
      'image': '图像',
      'video': '视频',
      'sensor': '传感器',
      'system-event': '系统事件',
      'rule-engine': '规则引擎',
      'bayesian-net': '贝叶斯网络',
      'fuzzy-logic': '模糊逻辑',
      'llm': '大模型',
      'retrieval': '检索',
      'neural-network': '神经网络',
      'planner': '规划',
      'safety-filter': '安全过滤',
      'local-memory': '本地记忆',
      'long-term-memory': '长期记忆',
      'vector-index': '向量索引',
      'knowledge-base': '知识库',
      'shared-org-data': '组织共享数据',
      'browser': '浏览器',
      'external-api': '外部API',
      'database': '数据库',
      'blockchain': '区块链',
      'ipfs': 'IPFS',
      'iot-device': '物联网设备',
      'cloud-storage': '云存储',
      'speech': '语音',
      'notification': '通知',
      'json-api': 'JSON API',
      'actuation': '执行',

      // Octopus
      'text-processing': '文本处理',
      'news-search': '新闻查询',
      'payment': '支付',
      'web-browsing': '联网搜索',
      'rag-openai': 'RAG+OPENAI',
      'rag-deepseek': 'RAG+deepseek',
      'knowledge-pro': '专业知识库',
      'ppt': 'ppt',

      // OpenClaw
      'openclaw': 'OpenClaw',
      'localhost-gateway': 'localhost-gateway',
      'tailscale-gateway': 'tailscale-gateway',
      'shared-secret': 'shared-secret',
      'default-soul': 'default-soul',
      'strict-privacy': 'strict-privacy',
      'browser-control': 'browser-control',
      'file-access': 'file-access',
      'shell-run': 'shell-run',
      'camera': 'camera',
      'canvas': 'canvas',
      'webchat': 'webchat',
      'telegram': 'telegram',
      'discord': 'discord',
      'slack': 'slack',

      // 外观
      'appearance-purple': '紫色',
      'appearance-blue': '蓝色',
      'appearance-pink': '粉色',
      'appearance-green': '绿色'
    };

    let label = zhLabelMap[norm] || zhLabelMap[raw];

    if (!label && norm.includes('appearance')) {
      if (norm.includes('purple')) label = '紫色';
      else if (norm.includes('blue')) label = '蓝色';
      else if (norm.includes('pink')) label = '粉色';
      else if (norm.includes('green')) label = '绿色';
    }

    return label || raw || '未定义';
  },

  isOpenClawOption(opt, rowIndex){
  const norm = this.normalizeLabel(opt);

  const appearance = new Set([
    'appearance-purple',
    'appearance-blue',
    'appearance-pink',
    'appearance-green'
  ]);

  const openclawByRow = {
    0: new Set([
      'openclaw'
    ]),

    1: new Set([
      'localhost-gateway',
      'tailscale-gateway',
      'shared-secret'
    ]),

    2: new Set([
      'default-soul',
      'strict-privacy'
    ]),

    3: new Set([
      'local-memory',
      'long-term-memory',
      'browser-control',
      'file-access',
      'shell-run',
      'camera',
      'canvas'
    ]),

    4: new Set([
      'text',
      'webchat',
      'telegram',
      'discord',
      'slack'
    ]),

    5: appearance
  };

  if (appearance.has(norm)) return rowIndex === 5;

  return openclawByRow[rowIndex] && openclawByRow[rowIndex].has(norm) || false;
},

  isOctopusOption(opt, rowIndex){
      const norm = this.normalizeLabel(opt);

      const appearance = new Set([
        'appearance-purple',
        'appearance-blue',
        'appearance-pink',
        'appearance-green'
      ]);

      const octopusByRow = {
        0: new Set([
          'text-processing',
          'news-search',
          'payment',
          'web-browsing'
        ]),

        1: new Set([
          'text',
          'voice',
          'image'
        ]),

        2: new Set([
          'rag-openai',
          'rag-deepseek',
          'llm',
          'retrieval',
          'planner',
          'safety-filter'
        ]),

        3: new Set([
          'local-memory',
          'long-term-memory',
          'knowledge-pro',
          'knowledge-base',
          'vector-index'
        ]),

        4: new Set([
          'text',
          'speech',
          'image',
          'video',
          'ppt'
        ]),

        5: appearance
      };

      if (appearance.has(norm)) return rowIndex === 5;

      return octopusByRow[rowIndex] && octopusByRow[rowIndex].has(norm) || false;
    },

    isAllowedOption(opt, rowIndex){
      if (this.agentType === 'openclaw') {
        return this.isOpenClawOption(opt, rowIndex);
      }
      return this.isOctopusOption(opt, rowIndex);
    },

  getCategoryName(row, i){
    const hasAppearance = row.some(opt => this.isAppearanceOpt(opt));

    if (this.agentType === 'openclaw') {
      const names = [
        '运行时',
        '网关访问方式',
        '人格与安全策略',
        '记忆与工具权限',
        '通信渠道',
        '外观'
      ];
      if (hasAppearance) return '外观';
      return names[i] || 'OpenClaw 配置';
    }

    const names = ['功能', '输入', '推理', '知识', '输出', '外观'];
    if (hasAppearance) return '外观';
    return names[i] || '其他配置';
  },

    renderCmmHtml(cmm, prefix) {
      console.log('renderCmmHtml called with cmm:', cmm);
      console.log('prefix:', prefix);
      if (!cmm || !cmm.length) {
        console.warn('cmm is empty, returning empty string');
        return '';
      }
      const rows = cmm || [];
      const htmlRows = rows.map((row, i) => {
        const filtered = row
          .map((opt, j) => ({ opt, j }))
          .filter(item => this.isAllowedOption(item.opt, i));

        if (filtered.length === 0) {
          return '';
        }

        const isAppearanceRow = filtered.some(item => this.isAppearanceOpt(item.opt));
        const cat = this.getCategoryName(row, i);
        const inputType = isAppearanceRow ? 'radio' : 'checkbox';

        const opts = filtered.map(({ opt, j }) => {
          const label = this.labelToZh(opt);
          const norm = this.normalizeLabel(opt);
          const checked = (this.agentType === 'openclaw' && norm === 'openclaw') ? 'checked' : '';
          return `
            <label class="option-chip">
              <input type="${inputType}" name="${prefix}_${i}" value="${j}" ${checked}>
              <span class="chip-content">${label}</span>
            </label>
          `;
        }).join(' ');

        return `
          <div class="config-category">
            <div class="config-group-title">${cat}</div>
            <div class="config-options">${opts}</div>
          </div>
        `;
      }).join('');

      console.log('Generated HTML:', htmlRows);
      return htmlRows || '<div class="empty-config-tip">当前 PA 类型下暂无可用配置，请检查 AP 返回的 CMM。</div>';
    },

      
    async issue(){
      if (this.phcPending || this.successIssue || this.stage > 1) {
        return;
      }

      this.loadingIssue = true;
      this.successIssue = false;
      const f = this.$refs.picfile && this.$refs.picfile.files && this.$refs.picfile.files[0];
      if (!f) { this.phcText='请先选择照片再申请 PHC'; this.loadingIssue = false;return; }
      const fd=new FormData(); fd.append('file', f);
      let picString=null;
      try {
        const rUpload=await fetch('/v1/pic/upload',{method:'POST',body:fd});
        const dUpload=await rUpload.json();
        picString = dUpload.string_part || null;
        if (!picString) { this.phcText='图片上传失败，请重试';this.loadingIssue = false; return; }
      } catch (e) { this.phcText='图片上传失败：'+(e&&e.message?e.message:'unknown'); this.loadingIssue = false;return; }
      const user={pii:{name:this.name,id_number:this.idnum,id_card_number:(this.idcard||''),email:this.email},bi:{last_login_ip:'127.0.0.1',passport_number:(this.passport||''),pic_string:picString},cdid:'cdid:user.placeholder',ecid:'g'};
      const payload={base_url:this.tpBase,user};
      try{
        const r=await fetch('/user/request_phc',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(payload)});
        const data=await r.json();
        this.phcObj = data.phc || data.PHC || null;
        this.phcRequestId = data.request_id || '';
        this.phcPending = data.status === 'pending' && !!this.phcRequestId;
        this.phcText = JSON.stringify(data, null, 2);

        if (this.phcPending) {
          this.phcObj = null;
          this.canFetchCmm = false;
          this.canRecoverPa = false;
          this.cmmObj = null;
          this.cmcObj = null;
          this.canSubmitCmc = false;
          this.stage = 0;
          this.successIssue = false;
          this.phcText += '\n\n[WAITING] PHC 申请已提交，等待 TP 管理端审核。请到 http://127.0.0.1:8001/tp 审核后，再点击“查询 TP 审核结果”。';
          return;
        }

        this.canFetchCmm = !!this.phcObj;
        this.canRecoverPa = !!this.phcObj;

        if (!this.phcObj) {
          this.canFetchCmm = false;
          this.canRecoverPa = false;
          this.cmmObj = null;
          this.cmcObj = null;
          this.canSubmitCmc = false;
          this.stage = 0;
          this.successIssue = false;
          this.phcText += '\n\n[ERROR] 后端没有返回有效的 PHC/ phc 字段，因此当前无法点击“加载配置”。';
          return;
        }

        this.stage = 1;
        this.successIssue = true;

        this.stage = 1;
        this.successIssue = true;
      }catch(e){ this.phcText='Request PHC failed: '+(e&&e.message?e.message:'unknown'); }
      finally { this.loadingIssue = false; }
    },
    async checkPhcApplication() {
      if (!this.phcRequestId) {
        this.phcText = '没有 request_id，无法查询审核结果。';
        return;
      }

      this.loadingCheckPhc = true;

      try {
        const r = await fetch('/user/check_phc_application', {
          method: 'POST',
          headers: {'content-type': 'application/json'},
          body: JSON.stringify({
            base_url: this.tpBase,
            request_id: this.phcRequestId
          })
        });

        const data = await r.json();
        this.phcText = JSON.stringify(data, null, 2);

        const application = data.application || data.app || null;
        const status = data.status || (application && application.status) || '';
        const phc = data.phc || data.PHC || (application && (application.phc || application.PHC)) || null;

        if ((status === 'issued' || status === 'approved' || status === 'signed') && phc) {
          this.phcObj = phc;
          this.phcPending = false;
          this.phcRequestId = '';
          this.canFetchCmm = true;
          this.canRecoverPa = true;
          this.stage = 1;
          this.successIssue = true;
          this.phcText += '\n\n[SUCCESS] TP 已审核并签发 PHC，现在可以继续加载配置。';
          return;
        }

        if (status === 'rejected' || status === 'denied') {
          this.phcPending = false;
          this.successIssue = false;
          this.canFetchCmm = false;
          this.canRecoverPa = false;
          this.phcText += '\n\n[REJECTED] TP 已拒绝该 PHC 申请。';
          return;
        }

        this.phcPending = true;
        this.successIssue = false;
        this.canFetchCmm = false;
        this.canRecoverPa = false;
        this.phcText += '\n\n[WAITING] 仍在等待 TP 审核。';
      } catch (e) {
        this.phcText = '查询 TP 审核结果失败：' + (e && e.message ? e.message : 'unknown');
      } finally {
        this.loadingCheckPhc = false;
      }
    },
    async fetchcmm(){
      this.loadingCmm = true;

      const user = {
        pii: {
          name: this.name,
          id_number: this.idnum,
          id_card_number: (this.idcard || ''),
          email: this.email
        },
        bi: {
          last_login_ip: '127.0.0.1',
          passport_number: (this.passport || '')
        },
        cdid: 'cdid:user.placeholder',
        ecid: 'g'
      };

      try {
        const r = await fetch('/user/cmm_init', {
          method: 'POST',
          headers: {'content-type': 'application/json'},
          body: JSON.stringify({
            base_url: this.apBase,
            phc: this.phcObj,
            user,

            // 新增：告诉后端当前要哪种 PA
            agent_type: this.agentType
          })
        });

        const data = await r.json();

        this.cmmObj = data.cmm;
        this.cmcObj = (this.cmmObj || []).map(row => row[0]);
        this.cmmSk = String(data.sk || "");
        this.cmmPk = String(data.pk || "");

        // 新渲染方式：根据 agentType 过滤能力
        this.cmmHtml = this.renderCmmHtml(this.cmmObj, 'row');

        this.canSubmitCmc = !!(this.cmmSk && this.cmmPk);
        this.stage = 2;
        this.successCmm = true;
      } catch (e) {
        this.cmmHtml = '加载配置失败：' + (e && e.message ? e.message : 'unknown');
      } finally {
        this.loadingCmm = false;
      }
    },
    async submitcmc(){
      this.loadingSubmit = true;

      const hid = this.idnum ? this.idnum : '';

      let cmc = [];
      if (this.agentType === 'octopus') {
        cmc = (this.cmmObj || []).map((row, i) => {
          const nodes = Array.from(document.querySelectorAll(`input[name='row_${i}']:checked`));
          const idxs = nodes.map(n => Number(n.value));
          return row.filter((_, j) => idxs.includes(j));
        });
      } else if (this.agentType === 'openclaw') {
        const fullMatrix = this.cmmObj || [];
        // 确保有 8 行
        while (fullMatrix.length < 8) fullMatrix.push([]);

        // 第0行：features – 固定选择 openclaw
        const featuresRow = fullMatrix[0] || [];
        const openclawItem = featuresRow.find(item => item.label === 'openclaw');
        const selectedFeatures = openclawItem ? [openclawItem] : [];

        // 第1行：gateway – 暂不处理（空）
        // 第2行：personality – 暂不处理（空）

        // 第3行：hooks – 根据 openclawHooksSelected 筛选
        const hooksRow = fullMatrix[3] || [];
        const selectedHooks = hooksRow.filter(hook => {
          const hookType = hook.params && hook.params.hook_type;
          if (!hookType) return false;
          const mapping = {
            'session-memory': 'session_memory',
            'command-logger': 'command_logger',
            'bootstrap-extra-files': 'bootstrap_extra_files',
            'boot-md': 'boot_md'
          };
          const field = mapping[hookType];
          return field && this.openclawHooksSelected[field];
        });

        // 第4行：skills – 根据 skillsSelected 筛选
        const skillsRow = fullMatrix[4] || [];
        const selectedSkills = skillsRow.filter(skill => {
          const slug = skill.params && skill.params.skill_slug;
          return slug && this.skillsSelected.includes(slug);
        });

        // 第5行：knowledge - 添加 LLM 配置
        const llmConfigItem = {
          label: 'llm-model',
          params: {
            provider: this.llmConfig.provider,
            model: this.llmConfig.model,
            base_url: this.llmConfig.base_url,
            compatibility: 'openai-compatible'
          }
        };

        // 第5-7行：knowledge, channels, appearance
        cmc = [
          selectedFeatures,
          [],   // gateway
          [],   // personality
          selectedHooks,
          selectedSkills,
          [llmConfigItem],   // knowledge - 放入 LLM 配置
          [],   // channels
          []    // appearance
        ];
      }

      this.cmcObj = cmc;

      try {
        const r = await fetch('/user/cmm_submit', {
          method: 'POST',
          headers: {'content-type': 'application/json'},
          body: JSON.stringify({
            base_url: this.apBase,
            cmc: cmc || [],
            hid: hid,
            phc: this.phcObj,
            user_sk: this.cmmSk || "",
            user_pk: this.cmmPk || "",

            // 新增
            agent_type: this.agentType,
            hooks_config: this.agentType === 'openclaw' ? this.openclawHooksSelected : null,
            llm_config: this.agentType === 'openclaw' ? this.llmConfig : null
          })
        });

        const data = await r.json();

        this.paCmmText = JSON.stringify(data, null, 2);
        // 提取并打印 HASH_CHAIN entries
        if (data.PHC && data.PHC.ASO && data.PHC.ASO.HASH_CHAIN && data.PHC.ASO.HASH_CHAIN.entries) {
            const entries = data.PHC.ASO.HASH_CHAIN.entries;
            let entriesText = '\n\n========== HASH CHAIN ENTRIES ==========\n';
            entries.forEach(entry => {
                entriesText += `idx: ${entry.idx}, label: ${entry.label}, prev: ${entry.prev}, hash: ${entry.hash}\n`;
            });
            this.paCmmText += entriesText;
        }
        this.hashCH = '';
        this.hashCCH = '';
        this.hashStatus = '';

        this.phcObj = data.PHC;
        this.paObj = data.PA;
        this.canCreateAgent = !!(this.phcObj && this.paObj);
        this.stage = 3;
        this.successSubmit = true;
      } catch (e) {
        this.paCmmText = '提交配置失败：' + (e && e.message ? e.message : 'unknown');
      } finally {
        this.loadingSubmit = false;
      }
    },
    async createAgent(){
      this.loadingCreate = true;

      if (this.agentType === 'openclaw') {
        if (!this.dependencyStatus.checked) {
          await this.checkOpenClawDependencies();
        }

        if (!this.dependencyStatus.ready_for_openclaw) {
          this.agentOut = '已拦截创建：当前电脑缺少 OpenClaw 运行所需依赖，请先安装 Node.js 和 Git，再重新创建。';
          this.showAgent = true;
          this.loadingCreate = false;
          return;
        }
      }

      const payload2 = {
        phc: this.phcObj || {},
        pa: this.paObj || {},
        cmc: this.cmcObj || [],
        agent_type: this.agentType,
        hooks_config: this.agentType === 'openclaw' ? this.openclawHooksSelected : null,
        skills_config: this.agentType === 'openclaw' ? this.skillsSelected : null, 
        llm_config: this.agentType === 'openclaw' ? { provider: this.llmConfig.provider,model: this.llmConfig.model} : null
      };

      try {
        const r2 = await fetch('/user/create_agent', {
          method: 'POST',
          headers: {'content-type': 'application/json'},
          body: JSON.stringify(payload2)
        });

        const data2 = await r2.json();
        this.agentOut = JSON.stringify(data2, null, 2);
        if (data2 && data2.success) {
          const manifest = data2.manifest || {};
          const binding = manifest.binding || {};
          const modules = manifest.modules || {};
          const features = Object.values(modules).flat().filter(Boolean).join('、');
          this.createdAgentInfo = {
            agentType: data2.agent_type || this.agentType,
            agentId: manifest.id || this.currentPhcId,
            did: manifest.did || this.phcObj?.DID || ((this.phcObj?.ASO || {}).TPM || {}).CDID,
            phcId: binding.PHC_id || this.currentPhcId,
            apId: binding.APid || ((this.paObj?.APA || {}).APid),
            features,
            agentPath: data2.agent_path || data2.openclaw_package,
            launcher: data2.personal_launcher || data2.launcher
          };
        }
        // 在 agentOut 中附加哈希链信息（使用已存储的 phcObj）
        if (this.phcObj && this.phcObj.ASO && this.phcObj.ASO.HASH_CHAIN && this.phcObj.ASO.HASH_CHAIN.entries) {
            const entries = this.phcObj.ASO.HASH_CHAIN.entries;
            let entriesText = '\n\n========== HASH CHAIN ENTRIES ==========\n';
            entries.forEach(entry => {
                entriesText += `idx: ${entry.idx}, label: ${entry.label}, prev: ${entry.prev}, hash: ${entry.hash}\n`;
            });
            this.agentOut += entriesText;
        }
        if (data2 && data2.success === false && data2.error === 'missing_openclaw_dependencies') {
          this.dependencyStatus.checked = true;
          if (data2.dependencies) {
            this.dependencyStatus = {
              checked: true,
              ready_for_openclaw: !!data2.dependencies.ready_for_openclaw,
              winget: data2.dependencies.winget || { installed: false, path: '' },
              node: data2.dependencies.node || { installed: false, version: '', path: '', download_url: 'https://nodejs.org/en/download' },
              git: data2.dependencies.git || { installed: false, version: '', path: '', download_url: 'https://git-scm.com/download/win' }
            };
            this.dependencyMessage = JSON.stringify(data2.dependencies, null, 2);
          }
          this.showAgent = true;
          return;
        }
        if (this.agentType === 'openclaw' && data2.success) {
          this.skillsUserName = (data2.manifest && data2.manifest.id) || this.skillsUserName || 'phc';
          this.skillsOpenclawPath = data2.openclaw_package || '';
          const enabledHooks = Object.entries(this.openclawHooksSelected)
            .filter(([, v]) => v)
            .map(([k]) => {
              const map = {
                session_memory: '会话记忆备份',
                bootstrap_extra_files: '额外引导文件注入',
                command_logger: '命令审计日志',
                boot_md: '启动脚本执行'
              };
              return map[k] || k;
            });
          if (enabledHooks.length > 0) {
            this.$message && this.$message.success ? this.$message.success(`OpenClaw 创建成功，已选择基本功能: ${enabledHooks.join('、')}`) : null;
          }
          this.$message && this.$message.success ? this.$message.success(`OpenClaw 创建成功，当前 PHC ID：${this.currentPhcId || '未知'}，可继续安装当前实例的 Skill。`) : null;

          if (this.skillsSelected.length > 0 && this.skillsOpenclawPath) {
            this.skillsInstallLoading = true;
            this.skillsProgress = { percent: 30, message: '正在自动安装预选 skills...', status: null };
            this.installResult = null;
            this.skillsInstallDetail = '';
            try {
              const response = await fetch('/skills/install', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                  user_name: this.skillsUserName,
                  openclaw_path: this.skillsOpenclawPath,
                  selected_skills: this.skillsSelected
                })
              });
              const installData = await response.json();
              if (response.ok && installData.success) {
                this.skillsProgress = { percent: 80, message: '正在自动安装预选 skills...', status: null };
                this.pollInstallStatus(installData.session_id);
              } else {
                const detail = installData.detail || {};
                const message = detail.message || installData.message || '自动安装预选 skills 失败';
                this.skillsProgress = { percent: 100, message, status: 'exception' };
                this.skillsInstallDetail = JSON.stringify(installData, null, 2);
                this.skillsInstallLoading = false;
              }
            } catch (error) {
              this.skillsProgress = { percent: 100, message: '自动安装预选 skills 失败: ' + error.message, status: 'exception' };
              this.skillsInstallDetail = '自动安装预选 skills 失败: ' + error.message;
              this.skillsInstallLoading = false;
            }
          }
        }

        this.stage = 4;
        this.successCreate = true;
        this.saveLastAgent();
      } catch (e) {
        this.agentOut = '创建个人智能体失败：' + (e && e.message ? e.message : 'unknown');
      } finally {
         this.loadingCreate = false;
      }
    },
    buildRecoveryUser(picString = null) {
      return {
        pii: {
          name: (this.recoveryName || '').trim(),
          id_number: (this.recoveryIdnum || '').trim(),
          id_card_number: (this.recoveryIdcard || '').trim(),
          email: (this.recoveryEmail || '').trim()
        },
        bi: {
          last_login_ip: '127.0.0.1',
          passport_number: (this.recoveryPassport || '').trim(),
          ...(picString ? {pic_string: picString} : {})
        },
        cdid: 'cdid:user.placeholder',
        ecid: 'g'
      };
    },
    async prepareRecoveryUser() {
      const file = this.$refs.recoveryPicfile && this.$refs.recoveryPicfile.files && this.$refs.recoveryPicfile.files[0];
      if (!file) return this.buildRecoveryUser();
      const form = new FormData();
      form.append('file', file);
      const response = await fetch('/v1/pic/upload', {method:'POST', body:form});
      const data = await response.json();
      if (!response.ok || !data.string_part) throw new Error(data.error || '恢复照片上传失败');
      return this.buildRecoveryUser(data.string_part);
    },
    _applyRecoveredPa(data) {
      this.phcObj = data.phc || this.phcObj || null;
      const paObj = data.pa || {};
      this.paObj = paObj.PA || data.PA || null;
      this.cmcObj = paObj.CMC || data.cmc || data.CMC || null;
      this.agentType = paObj.agent_type || data.agent_type || this.agentType;
      this.updateAgentType = this.agentType;
      this.canCreateAgent = !!(this.phcObj && this.paObj && this.cmcObj);
    },
    saveLastAgent() {
      try {
        const payload = {
          phc: this.phcObj,
          pa: this.paObj,
          cmc: this.cmcObj,
          agent_type: this.agentType,
          identity: {
            name: this.name,
            id_number: this.idnum,
            id_card_number: this.idcard,
            email: this.email,
            passport: this.passport
          },
          skills: {
            user_name: this.skillsUserName,
            openclaw_path: this.skillsOpenclawPath
          }
        };
        fetch('/user/last_agent', {method:'POST', headers:{'content-type':'application/json'}, body: JSON.stringify(payload)}).catch(() => {});
      } catch (e) { /* 保存失败不影响主流程 */ }
    },
    async loadLastAgent() {
      try {
        const r = await fetch('/user/last_agent');
        const data = await r.json();
        if (!data.success || !data.agent) return;
        const a = data.agent;
        this.phcObj = a.phc || this.phcObj || null;
        this.paObj = a.pa || this.paObj || null;
        this.cmcObj = a.cmc || this.cmcObj || null;
        this.agentType = a.agent_type || this.agentType;
        this.updateAgentType = a.agent_type || this.updateAgentType;
        if (a.identity) {
          this.name = a.identity.name || this.name;
          this.idnum = a.identity.id_number || this.idnum;
          this.idcard = a.identity.id_card_number || this.idcard;
          this.email = a.identity.email || this.email;
          this.passport = a.identity.passport || this.passport;
        }
        if (a.skills) {
          this.skillsUserName = a.skills.user_name || this.skillsUserName;
          this.skillsOpenclawPath = a.skills.openclaw_path || this.skillsOpenclawPath;
        }
        this.canCreateAgent = !!(this.phcObj && this.paObj && this.cmcObj);
        this.canFetchCmm = !!(this.phcObj);
      } catch (e) { /* 无历史快照时静默忽略 */ }
    },
    async recoverpa(){
      this.loadingRecoverPa = true;
      try{
        if (!this.phcObj) throw new Error('请先持有 PHC（主流程申领或先执行「恢复 PHC & PA」）');
        const idnum = (this.idnum || '').trim();
        if (!idnum) throw new Error('请先填写主申请身份中的身份证号（用于派生 HID）');
        const user = {
          pii: {
            name: this.name,
            id_number: idnum,
            id_card_number: this.idcard || null,
            email: this.email || null
          },
          bi: {},
          cdid: 'cdid:user.placeholder',
          ecid: 'g'
        };
        const payload={base_url:this.apBase, phc: this.phcObj, user, agent_type: this.agentType};
        const r=await fetch('/user/recover_pa',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(payload)});
        const data=await r.json();
        this.paRecoverPaText=JSON.stringify(data,null,2);
        if (data && data.success !== false) {
          this._applyRecoveredPa(data);
          this.saveLastAgent();
          this.successRecoverPa = true;
        } else {
          this.successRecoverPa = false;
        }
      }catch(e){ this.paRecoverPaText='Recover PA failed: '+(e&&e.message?e.message:'unknown'); this.successRecoverPa = false; }
      finally { this.loadingRecoverPa = false; }
    },
    async recoverboth(){
      this.loadingRecoverBoth = true;
      try {
        const user = await this.prepareRecoveryUser();
        const r=await fetch('/user/recover_both',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({tp_base:this.tpBase, ap_base:this.apBase, user, agent_type: this.agentType, did: this.recoveryDid || null})});
        const data=await r.json();
        this.paRecoverBothText=JSON.stringify(data,null,2);
        if (data && data.success !== false) {
          this._applyRecoveredPa(data);
          this.saveLastAgent();
          this.successRecoverBoth = true;
        } else {
          this.successRecoverBoth = false;
        }
      }catch(e){ this.paRecoverBothText='Recover Both failed: '+(e&&e.message?e.message:'unknown'); this.successRecoverBoth = false; }
      finally { this.loadingRecoverBoth = false; }
    },
    async updatepa(){
      this.loadingUpdateInit = true;

      const updateId = (this.idnum || '').trim();
      if (!updateId) {
        this.updateText = '请先在申请身份中填写身份证号。';
        this.loadingUpdateInit = false;
        return;
      }

      const updateUser = {
        pii: {
          name: this.name,
          id_number: updateId,
          id_card_number: (this.idcard || ''),
          email: this.email
        },
        bi: {
          last_login_ip: '127.0.0.1',
          passport_number: (this.passport || '')
        },
        cdid: 'cdid:user.placeholder',
        ecid: 'g'
      };

      if (!this.phcObj) {
        try {
          const phcResponse = await fetch('/user/recover_phc', {
            method: 'POST',
            headers: {'content-type': 'application/json'},
            body: JSON.stringify({base_url:this.tpBase,user:updateUser})
          });
          const phcData = await phcResponse.json();
          if (!phcResponse.ok || phcData.success === false || !phcData.phc) {
            throw new Error(phcData.error || '自动恢复 PHC 失败');
          }
          this.phcObj = phcData.phc;
        } catch (e) {
          this.updateText = '无法自动恢复该 PA 的 PHC：' + (e && e.message ? e.message : 'unknown');
          this.loadingUpdateInit = false;
          return;
        }
      }

      if (this.updateAgentType === 'openclaw') {
        if (!this.skillsUserName) {
          this.updateText = '请先完成 OpenClaw 创建，或确认实例标识已自动带出。';
          this.loadingUpdateInit = false;
          return;
        }
        try {
          const encodedUser = encodeURIComponent(this.skillsUserName);
          const r = await fetch(`/skills/installed/${encodedUser}`);
          const data = await r.json();
          if (data.success) {
            this.installedSkillsList = this.normalizeInstalledSkillsPayload(data);
            if (!this.skillsOpenclawPath && data.instance_dir) {
              this.skillsOpenclawPath = data.instance_dir;
            }
            this.successUpdateInit = true;
            this.canSubmitUpdate = true;
            this.updateText = JSON.stringify(data, null, 2);
          } else {
            this.updateText = data.error || '获取已安装 skills 失败';
            this.canSubmitUpdate = false;
          }
        } catch (e) {
          this.updateText = '获取已安装 skills 失败：' + (e && e.message ? e.message : 'unknown');
          this.canSubmitUpdate = false;
        } finally {
          this.loadingUpdateInit = false;
        }
        return;
      }

      try {
        const r = await fetch('/user/update_init', {
          method: 'POST',
          headers: {'content-type': 'application/json'},
          body: JSON.stringify({
            base_url: this.apBase,
            phc: this.phcObj,
            user: updateUser,
            agent_type: this.updateAgentType
          })
        });

        const data = await r.json();
        const cmm = data.cmm;

        this.updSk = String(data.sk || "");
        this.updPk = String(data.pk || "");
        this.lastCMM = cmm;
        this.successUpdateInit = true;

        // 新渲染：临时切换到更新区选择的类型，渲染完立即还原，避免影响主流程
        const prevAgentType = this.agentType;
        this.agentType = this.updateAgentType;
        this.updCmmHtml = this.renderCmmHtml(cmm, 'upd_row');
        this.agentType = prevAgentType;

        this.canSubmitUpdate = !!((cmm && cmm.length > 0) && (this.updSk && this.updPk));
      } catch (e) {
        this.updateText = 'Update PA failed: ' + (e && e.message ? e.message : 'unknown');
      } finally {
        this.loadingUpdateInit = false;
      }
    },
    async submitUpdate(){
      this.loadingUpdateSubmit = true;

      if (this.updateAgentType === 'openclaw') {
        try {
          const r = await fetch('/skills/update-installed', {
            method: 'POST',
            headers: {'content-type': 'application/json'},
            body: JSON.stringify({
              user_name: this.skillsUserName,
              openclaw_path: this.skillsOpenclawPath
            })
          });
          const data = await r.json();
          this.updateText = JSON.stringify(data, null, 2);
          this.successUpdateSubmit = !!data.success;
          await this.refreshInstalledSkills();
        } catch (e) {
          this.updateText = '更新 skills 失败：' + (e && e.message ? e.message : 'unknown');
        } finally {
          this.loadingUpdateSubmit = false;
        }
        return;
      }

      const hid = this.idnum ? this.idnum : '';

      const cmc = (this.lastCMM || []).map((row, i) => {
        const nodes = Array.from(document.querySelectorAll(`input[name='upd_row_${i}']:checked`));
        const idxs = nodes.map(n => Number(n.value));
        return row.filter((_, j) => idxs.includes(j));
      });

      const payload = {
        base_url: this.apBase,
        cmc: cmc || [],
        hid: hid,
        phc: this.phcObj,
        user_sk: this.updSk || "",
        user_pk: this.updPk || "",
        agent_type: this.updateAgentType
      };

      try {
        const r = await fetch('/user/update_submit', {
          method: 'POST',
          headers: {'content-type': 'application/json'},
          body: JSON.stringify(payload)
        });

        const data = await r.json();
        this.updateText = JSON.stringify(data, null, 2);
        this.successUpdateSubmit = true;
      } catch (e) {
        this.updateText = '提交更新失败：' + (e && e.message ? e.message : 'unknown');
      } finally {
        this.loadingUpdateSubmit = false;
      }
    },

    async searchClawHubForUpdate() {
      if (!this.updateSearchKeyword.trim()) {
        this.$message && this.$message.warning ? this.$message.warning('请输入搜索关键词') : null;
        return;
      }
      this.updateSearchLoading = true;
      this.updateSearchResults = null;
      try {
        const response = await fetch(`/skills/search?keyword=${encodeURIComponent(this.updateSearchKeyword)}`);
        const data = await response.json();
        if (data.success) {
          this.updateSearchResults = data.output;
        } else {
          this.updateSearchResults = data.error || '搜索失败';
        }
      } catch (error) {
        this.updateSearchResults = '请求失败: ' + error.message;
      } finally {
        this.updateSearchLoading = false;
      }
    },

    async installNewSkillForUpdate() {
      if (!this.updateInstallSkillSlug.trim()) {
        return;
      }
      this.updateInstallLoading = true;
      try {
        const response = await fetch('/skills/install', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            user_name: this.skillsUserName,
            openclaw_path: this.skillsOpenclawPath,
            selected_skills: [this.updateInstallSkillSlug.trim()]
          })
        });
        const data = await response.json();
        this.updateText = JSON.stringify(data, null, 2);
        if (response.ok && data.success) {
          this.$message && this.$message.success ? this.$message.success('新 skill 安装任务已启动') : null;
          this.successUpdateSubmit = true;
          await this.refreshInstalledSkills();
          this.updateInstallSkillSlug = '';
        } else {
          this.$message && this.$message.error ? this.$message.error((data.detail && data.detail.message) || data.message || '安装失败') : null;
        }
      } catch (e) {
        this.updateText = '安装新 skill 失败：' + (e && e.message ? e.message : 'unknown');
      } finally {
        this.updateInstallLoading = false;
      }
    },

    async updateOneInstalledSkill(skillSlug) {
      this.singleSkillActionLoading = `update:${skillSlug}`;
      try {
        const response = await fetch('/skills/update-one', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            user_name: this.skillsUserName,
            openclaw_path: this.skillsOpenclawPath,
            skill_slug: skillSlug
          })
        });
        const data = await response.json();
        this.updateText = JSON.stringify(data, null, 2);
        if (data.success) {
          this.$message && this.$message.success ? this.$message.success(`已更新 ${skillSlug}`) : null;
          await this.refreshInstalledSkills();
        } else {
          const notFound = response.status === 404 || (data.detail && String(data.detail).includes('Not Found'));
          const message = notFound
            ? '更新单个 skill 接口不存在，请先重启 User 服务后再试。'
            : ((data.result && data.result.error) || data.detail || '更新失败');
          this.$message && this.$message.error ? this.$message.error(message) : null;
        }
      } catch (error) {
        this.$message && this.$message.error ? this.$message.error(`更新 ${skillSlug} 失败: ${error.message}`) : null;
      } finally {
        this.singleSkillActionLoading = '';
      }
    },

    async uninstallOneInstalledSkill(skillSlug) {
      this.singleSkillActionLoading = `remove:${skillSlug}`;
      try {
        const response = await fetch('/skills/uninstall-one', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            user_name: this.skillsUserName,
            openclaw_path: this.skillsOpenclawPath,
            skill_slug: skillSlug
          })
        });
        const data = await response.json();
        this.updateText = JSON.stringify(data, null, 2);
        if (data.success) {
          this.$message && this.$message.success ? this.$message.success(`已卸载 ${skillSlug}`) : null;
          await this.refreshInstalledSkills();
        } else {
          const notFound = response.status === 404 || (data.detail && String(data.detail).includes('Not Found'));
          const message = notFound
            ? '卸载单个 skill 接口不存在，请先重启 User 服务后再试。'
            : ((data.result && data.result.error) || data.detail || '卸载失败');
          this.$message && this.$message.error ? this.$message.error(message) : null;
        }
      } catch (error) {
        this.$message && this.$message.error ? this.$message.error(`卸载 ${skillSlug} 失败: ${error.message}`) : null;
      } finally {
        this.singleSkillActionLoading = '';
      }
    },
    statusType(idx){
      if (this.stage>idx) return 'success';
      if (this.stage===idx) return 'primary';
      return '';
    },
    statusColor(idx){
      if (this.stage>idx) return '#16a34a';
      if (this.stage===idx) return '#3867ff';
      return '#94a3b8';
    },
    toggleShow(which){
      if (which==='phc') this.showPhc = !this.showPhc;
      else if (which==='pa') this.showPa = !this.showPa;
      else if (which==='agent') this.showAgent = !this.showAgent;
      else if (which==='openclawDeps') {
        this.showOpenClawDeps = !this.showOpenClawDeps;
      }
      else if (which==='skillsInstallDetail') this.showSkillsInstallDetail = !this.showSkillsInstallDetail;
      else if (which==='update') this.showUpdate = !this.showUpdate;
      else if (which==='recoverBoth') this.showRecoverBoth = !this.showRecoverBoth;
      else if (which==='recoverPa') this.showRecoverPa = !this.showRecoverPa;
    },



        // ==================== 多智能体管理方法 ====================

    getStatusType(status) {
      const types = {
        created: 'info',
        deployed: 'warning',
        running: 'success',
        stopped: 'danger'
      };
      return types[status] || 'info';
    },

    viewGroupConfig(group) {
      this.showGroupConfig = this.showGroupConfig === group.group_id ? null : group.group_id;
    },

    async createSubAgent() {
  if (!this.newSubAgent.name) {
    if (this.$message) this.$message.warning('请输入子智能体名称');
    return;
  }

  // 安全获取父 Agent ID
  let parentPhcId = null;
  if (this.phcObj) {
    parentPhcId = this.phcObj.id || this.phcObj.phc_id || this.phcObj.PHC_id;
    // 如果 phcObj 内部还有 phc 字段
    if (!parentPhcId && this.phcObj.phc) parentPhcId = this.phcObj.phc.id;
    if (!parentPhcId && this.phcObj.PHC) parentPhcId = this.phcObj.PHC.id;
  }

  if (!parentPhcId) {
    if (this.$message) this.$message.warning('请先创建主 Agent（需要完成第4步）');
    console.error('phcObj:', this.phcObj);
    return;
  }

  this.creatingSubAgent = true;
  try {
    const response = await fetch('/agent/sub/create', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: this.newSubAgent.name,
        description: this.newSubAgent.description,
        capabilities: this.newSubAgent.capabilities,
        parent_phc_id: parentPhcId,  // 使用安全获取的 ID
        agent_type: 'openclaw',
        hooks_config: this.openclawHooksSelected,
        skills_config: this.skillsSelected,
        llm_config: {
          provider: this.llmConfig.provider,
          model: this.llmConfig.model
        }
      })
    });

        const data = await response.json();
        if (data.success) {
          if (this.$message) this.$message.success(`子智能体 "${this.newSubAgent.name}" 创建成功`);
          this.newSubAgent = { name: '', description: '', capabilities: [] };
          await this.loadAgentGroups();

          if (data.bridge_script) {
            this.downloadBridgeScriptContent(data.bridge_script, data.group_id);
          }
        } else {
          if (this.$message) this.$message.error(data.error || '创建失败');
        }
      } catch (error) {
    if (this.$message) this.$message.error('创建失败: ' + error.message);
  } finally {
    this.creatingSubAgent = false;
  }
},

    async loadAgentGroups() {
      if (!this.phcObj || !this.phcObj.id) return;

      try {
        const response = await fetch(`/agent/groups/${this.phcObj.id}`);
        const data = await response.json();
        if (data.success) {
          this.agentGroups = data.groups;
        }
      } catch (error) {
        console.error('加载 Agent 组失败:', error);
      }
    },

    async deploySubAgent(subAgentId) {
      try {
        const response = await fetch(`/agent/sub/${subAgentId}/deploy`, {
          method: 'POST'
        });
        const data = await response.json();
        if (data.success) {
          if (this.$message) this.$message.success(`部署命令: ${data.deploy_command}`);
          await this.loadAgentGroups();
        } else {
          if (this.$message) this.$message.error(data.error || '部署失败');
        }
      } catch (error) {
        if (this.$message) this.$message.error('部署失败: ' + error.message);
      }
    },

    async startSubAgent(subAgentId) {
      try {
        const response = await fetch(`/agent/sub/${subAgentId}/start`, {
          method: 'POST'
        });
        const data = await response.json();
        if (data.success) {
          if (this.$message) this.$message.success(`启动命令: ${data.launch_command}`);
          await this.loadAgentGroups();
        } else {
          if (this.$message) this.$message.error(data.error || '启动失败');
        }
      } catch (error) {
        if (this.$message) this.$message.error('启动失败: ' + error.message);
      }
    },

    async deleteSubAgent(subAgentId) {
      let confirmed = false;
      if (this.$confirm) {
        try {
          await this.$confirm('确定要删除这个子智能体吗？', '确认删除', { type: 'warning' });
          confirmed = true;
        } catch {
          confirmed = false;
        }
      } else {
        confirmed = confirm('确定要删除这个子智能体吗？');
      }

      if (!confirmed) return;

      try {
        const response = await fetch(`/agent/sub/${subAgentId}`, {
          method: 'DELETE'
        });
        const data = await response.json();
        if (data.success) {
          if (this.$message) this.$message.success('删除成功');
          await this.loadAgentGroups();
        } else {
          if (this.$message) this.$message.error(data.error || '删除失败');
        }
      } catch (error) {
        if (this.$message) this.$message.error('删除失败: ' + error.message);
      }
    },

    downloadBridgeScript(groupId) {
      const group = this.agentGroups.find(g => g.group_id === groupId);
      if (!group) return;

      const scriptContent = this.generateBridgeScriptContent(group);
      this.downloadBridgeScriptContent(scriptContent, groupId);
    },

    downloadBridgeScriptContent(content, groupId) {
      const blob = new Blob([content], { type: 'text/plain' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `agent_bridge_${groupId}.py`;
      a.click();
      URL.revokeObjectURL(url);
    },

        generateBridgeScriptContent(group) {
      const agentsList = (group.sub_agents || []).map(a => ({
        id: a.id,
        name: a.name,
        phc_id: a.phc_id,
        gateway_port: a.gateway_port,
        token: a.token
      }));

      // 使用转义来避免 JavaScript 模板字符串中的 $ 被解析
      const agentsJson = JSON.stringify(agentsList, null, 2);
      const groupId = group.group_id;
      const parentAgentId = group.parent_agent_id;

      return `#!/usr/bin/env python3
"""
Agent Communication Bridge for ${groupId}
Generated by User Service
"""

import asyncio
import json
import websockets
import sys
from datetime import datetime

AGENTS = ${agentsJson}
PARENT_AGENT_ID = "${parentAgentId}"

class AgentRouter:
    def __init__(self):
        self.agents = {}
        self.message_handlers = []

    async def connect_to_agent(self, agent_id, port, token):
        uri = f"ws://127.0.0.1:{port}/ws?token={token}"
        try:
            ws = await websockets.connect(uri)
            self.agents[agent_id] = ws
            print(f"[OK] Connected to {agent_id}")
            return ws
        except Exception as e:
            print(f"[ERROR] Failed to connect to {agent_id}: {e}")
            return None

    async def send_message(self, from_agent, to_agent, content):
        if to_agent not in self.agents:
            print(f"[ERROR] Agent {to_agent} not connected")
            return False
        message = {
            "type": "chat",
            "from": from_agent,
            "content": content,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
        try:
            await self.agents[to_agent].send(json.dumps(message))
            return True
        except Exception as e:
            print(f"[ERROR] Failed to send: {e}")
            return False

    async def run(self):
        print("=" * 50)
        print(f"Agent Communication Bridge for ${groupId}")
        print("=" * 50)
        for agent in AGENTS:
            await self.connect_to_agent(agent["id"], agent["gateway_port"], agent["token"])
        print("\\n[READY] Router is running")
        await asyncio.Future()

async def main():
    router = AgentRouter()
    await router.run()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\\n[STOP] Bridge stopped")
        sys.exit(0)
`;
    },
  },
}
</script>

<style>
/* ============================================================
   User 控制台 — 统一设计规范（科技蓝）
   与 TP / AP 三端视觉一致
   ============================================================ */
:root {
  /* 统一品牌色 */
  --primary-color: #3867ff;
  --primary-hover: #2d52cc;
  --primary-soft: #ebf0ff;
  --primary-ink: #1d4ed8;
  --primary-border: #c7d4ff;

  /* 中性色 */
  --text-strong: #0f172a;
  --text: #1f2937;
  --muted: #6b7280;
  --muted-2: #94a3b8;
  --border: #e5e7eb;
  --border-soft: #eef2f7;
  --bg: #f4f7fb;
  --card: #ffffff;

  /* 圆角 / 阴影 / 字体 */
  --radius-card: 14px;
  --radius-sm: 10px;
  --radius-pill: 999px;
  --shadow-card: 0 1px 2px rgba(15, 23, 42, 0.04), 0 10px 26px rgba(15, 23, 42, 0.05);
  --font-sans: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", "PingFang SC", sans-serif;
  --font-mono: Consolas, Monaco, "Courier New", monospace;

  --header-bg: #fff;
  --header-height: 68px;
  --content-width: 1280px;
}

/* Element Plus 主题变量覆盖
   用 :root:root 提高特异性，确保稳定压过 EP 默认样式表 */
:root:root {
  --el-color-primary: #3867ff;
  --el-color-primary-light-3: #7495ff;
  --el-color-primary-light-5: #9cb3ff;
  --el-color-primary-light-7: #c3d1ff;
  --el-color-primary-light-8: #d7e1ff;
  --el-color-primary-light-9: #ebf0ff;
  --el-color-primary-dark-2: #2d52cc;

  --el-border-radius-base: 8px;
  --el-border-radius-small: 6px;
  --el-border-radius-round: 999px;

  --el-font-size-extra-large: 21px;
  --el-font-size-large: 19px;
  --el-font-size-medium: 17px;
  --el-font-size-base: 15px;
  --el-font-size-small: 13.5px;
  --el-font-size-extra-small: 12.5px;

  --el-text-color-primary: #1f2937;
  --el-text-color-regular: #475467;
  --el-border-color: #e5e7eb;
  --el-border-color-light: #eef2f7;
  --el-bg-color: #ffffff;
  --el-fill-color-blank: #ffffff;
}

body {
  margin: 0;
  background: var(--bg);
  font-family: var(--font-sans);
  color: var(--text);
}

.app-wrapper {
  min-height: 100vh;
  background: var(--bg);
}

.llm-config-area {
  margin: 12px 0 16px;
  padding: 12px;
  background: #f8fafc;
  border-radius: 8px;
  border: 1px solid var(--border);
}
.llm-form {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
}
.llm-hint {
  margin-top: 6px;
  font-size: 12px;
  color: var(--muted-2);
}


/* Header Styles */
.app-header {
  height: var(--header-height);
  background: var(--header-bg);
  border-bottom: 1px solid var(--border);
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.03);
  position: sticky;
  top: 0;
  z-index: 100;
  display: flex;
  justify-content: center;
}

.header-inner {
  width: 100%;
  max-width: var(--content-width);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 14px;
}

.brand {
  display: flex;
  align-items: center;
  gap: 10px;
}

/* 平台 logo：蓝底方块 + 盾牌人形图标，与 TP / AP 三端同一枚 */
.logo-icon {
  width: 40px;
  height: 40px;
  flex: 0 0 40px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--primary-color);
  color: #fff;
}

.logo-icon svg {
  width: 23px;
  height: 23px;
}

.app-title {
  margin: 0;
  font-size: 17px;
  font-weight: 700;
  color: var(--text-strong);
}

.header-right {
  display: flex;
  align-items: center;
  gap: 14px;
}

/* 当前操作者：账号 + 角色 + 退出合成一个胶囊。
   原先「表单姓名 + 登录账号 + 退出按钮」三块并排，姓名与账号信息重复、
   视觉上也是散的；合成一体后与 TP / AP 两端的用户区形态一致。 */
.user-block {
  display: flex;
  align-items: center;
  gap: 10px;
  height: 42px;
  padding: 0 4px 0 5px;
  background: var(--primary-soft);
  border: 1px solid var(--primary-border);
  border-radius: 999px;
}

.user-avatar {
  width: 32px;
  height: 32px;
  flex: 0 0 32px;
  border-radius: 50%;
  background: linear-gradient(135deg, #3867ff 0%, #5f83ff 100%);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  font-weight: 700;
}

.user-meta {
  display: flex;
  flex-direction: column;
  line-height: 1.25;
  min-width: 0;
}

.user-name {
  font-size: 13.5px;
  font-weight: 600;
  color: var(--primary-ink);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.user-role {
  font-size: 11.5px;
  color: var(--muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* 退出是低频且带破坏性的操作：收成圆形图标按钮，hover 才露出危险色 */
.icon-logout {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  flex: 0 0 30px;
  padding: 0;
  color: var(--muted);
  background: transparent;
  border: none;
  border-radius: 50%;
  cursor: pointer;
  transition: color 0.15s ease, background 0.15s ease;
}

.icon-logout svg {
  width: 15px;
  height: 15px;
}

.icon-logout:hover {
  color: #dc2626;
  background: #fee2e2;
}

.icon-logout:focus-visible {
  outline: 2px solid var(--primary-color);
  outline-offset: 2px;
}

@media (max-width: 720px) {
  .user-meta {
    display: none;
  }

  .user-block {
    padding: 0 4px;
  }
}

/* Main Content Styles */
.app-content {
  max-width: var(--content-width);
  margin: 18px auto;
  padding: 0 14px;
}

/* 卡片外观与 AP 端 .panel 完全一致：1px 灰边 + 14px 圆角 + 同一阴影。
   Element Plus 默认卡片无边框、头部带分隔线，需要逐层覆盖。 */
.section-card {
  margin-bottom: 16px;
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius-card);
  box-shadow: var(--shadow-card);
  transition: box-shadow 0.25s ease;
  overflow: hidden;
}

.section-card:hover {
  box-shadow: var(--shadow-card) !important;
}

/* EP 卡片内边距/分隔线对齐 AP 的 panel：头部无下边框，标题与内容间距 16px */
.section-card .el-card__header {
  padding: 20px 20px 0;
  border-bottom: none;
}

.section-card .el-card__body {
  padding: 16px 20px 20px;
}

.card-header {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
}

/* 卡片标题 + 描述：与 AP 端 .panel-header 的 h2 / p 结构对齐 */
.header-title {
  font-size: 19px;
  font-weight: 700;
  line-height: 1.35;
  color: var(--text-strong);
}

.card-desc {
  margin: 0;
  font-size: 14px;
  line-height: 1.6;
  color: var(--muted);
}

/* Form Styles */
.file-upload-wrapper {
  border: 1px dashed #cfd8e3;
  padding: 10px;
  border-radius: var(--radius-sm);
  background: #f8fafc;
}

.custom-file-input {
  width: 100%;
}

/* Timeline Styles */
.custom-timeline {
  padding-left: 10px;
}

.timeline-content {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 0;
}

.step-title {
  margin: 0;
  font-size: 15px;
  font-weight: 500;
  color: var(--text-strong);
}

.action-area {
  display: flex;
  align-items: center;
  gap: 12px;
}

.created-agent-info {
  margin-top: 16px;
  padding: 18px;
  border: 1px solid #b9dec4;
  border-radius: 8px;
  background: #f5fbf6;
}

.created-agent-info-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.created-agent-eyebrow {
  color: #287044;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 1px;
}

.created-agent-info h4 {
  margin: 4px 0 0;
  color: var(--text-strong);
  font-size: 18px;
}

.created-agent-summary {
  margin: 8px 0 16px;
  color: var(--muted-2);
  font-size: 12px;
}

.created-agent-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.created-agent-grid > div {
  min-width: 0;
  padding: 11px 12px;
  border: 1px solid #d8eadc;
  border-radius: 6px;
  background: #fff;
}

.created-agent-grid span,
.created-agent-grid strong {
  display: block;
}

.created-agent-grid span {
  margin-bottom: 5px;
  color: var(--muted-2);
  font-size: 11px;
}

.created-agent-grid strong {
  color: var(--text-strong);
  font-size: 13px;
  overflow-wrap: anywhere;
}

.created-agent-paths {
  display: grid;
  gap: 8px;
  margin-top: 12px;
}

.created-agent-paths > div {
  display: grid;
  grid-template-columns: 80px minmax(0, 1fr);
  align-items: start;
  gap: 10px;
}

.created-agent-paths span {
  color: var(--muted-2);
  font-size: 11px;
  line-height: 1.7;
}

.created-agent-paths code {
  padding: 5px 7px;
  border-radius: 4px;
  background: #eaf5ec;
  color: #245c36;
  font-size: 11px;
  overflow-wrap: anywhere;
}

.status-tag {
  min-width: 50px;
  text-align: center;
}

.phc-actions {
  justify-content: flex-end;
  gap: 10px;
  flex-wrap: wrap;
}

.phc-actions .el-button {
  margin-left: 0;
}

.phc-status-tag {
  height: 32px;
  padding: 0 14px;
  border-radius: 16px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-weight: 600;
}

@media (max-width: 720px) {
  .timeline-content {
    align-items: flex-start;
    flex-direction: column;
    gap: 10px;
  }

  .phc-actions {
    justify-content: flex-start;
    width: 100%;
  }

  .phc-actions .el-button,
  .phc-status-tag {
    flex: 1 1 auto;
  }

  .created-agent-grid {
    grid-template-columns: 1fr;
  }
}

/* Dynamic Content Areas */
.detail-box {
  margin-top: 12px;
  background: #f8fafc;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 12px;
}

pre {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-all;
  font-family: Consolas, Monaco, monospace;
  font-size: 12px;
  color: #475467;
}

.dynamic-form-area {
  margin-top: 16px;
  padding: 16px;
  background: #fdfdfd;
  border: 1px solid var(--border-soft);
  border-radius: 6px;
}

/* Config Options Styles */
.config-category {
    margin-bottom: 20px;
    background: var(--primary-soft);
    padding: 15px;
    border-radius: var(--radius-sm);
    border: 1px solid var(--primary-border);
}
.config-group-title {
    font-weight: 700;
    color: var(--primary-color);
    margin-bottom: 12px;
    font-size: 14px;
    display: flex;
    align-items: center;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}
.config-group-title::before {
    content: '';
    display: inline-block;
    width: 6px;
    height: 6px;
    background: var(--primary-color);
    margin-right: 8px;
    border-radius: 50%;
}
.config-options {
    display: flex;
    flex-wrap: wrap;
    gap: 12px;
}
.option-chip {
    position: relative;
    cursor: pointer;
    user-select: none;
}
.option-chip input {
    position: absolute;
    opacity: 0;
    width: 0;
    height: 0;
}
.chip-content {
    display: inline-block;
    padding: 8px 18px;
    background: #fff;
    color: #475467;
    border-radius: var(--radius-pill);
    font-size: 13px;
    border: 1px solid var(--border);
    transition: all 0.25s ease;
    font-weight: 500;
}
.option-chip:hover .chip-content {
    border-color: var(--primary-border);
    color: var(--primary-color);
}
.option-chip input:checked + .chip-content {
    background: var(--primary-color);
    color: #fff;
    border-color: var(--primary-color);
    box-shadow: 0 2px 8px rgba(56, 103, 255, 0.28);
}

/* Update Section Styles */
.update-actions {
  display: flex;
  align-items: center;
  gap: 16px;
  background: #f8fafc;
  padding: 16px;
  border-radius: 6px;
}

.action-group {
  display: flex;
  align-items: center;
  gap: 8px;
}

.arrow-divider {
  color: var(--muted-2);
  font-weight: bold;
}

.result-section {
  margin-top: 24px;
}

.result-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.result-label {
  font-size: 14px;
  color: var(--muted-2);
}

/* Recovery Section Styles */
.warning-card {
  /* Removed border */
}

.warning-header {
  /* Removed color */
}

.recovery-item {
  padding: 8px 0;
}

.recovery-info h4 {
  margin: 0 0 4px 0;
  font-size: 15px;
  color: var(--text-strong);
}

.sub-text {
  margin: 0 0 12px 0;
  font-size: 12px;
  color: var(--muted-2);
}

.recovery-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.recovery-form {
  max-width: 920px;
  padding: 18px;
  border: 1px solid var(--primary-border);
  border-radius: 8px;
  background: #fbfcfe;
}

.recovery-form-section {
  padding: 0 0 18px;
  margin-bottom: 18px;
  border-bottom: 1px solid #e6eaf0;
}

.recovery-form-section:last-of-type {
  margin-bottom: 0;
  border-bottom: 0;
}

.recovery-section-heading {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
}

.recovery-section-heading strong,
.recovery-section-heading small {
  display: block;
}

.recovery-section-heading strong {
  color: var(--text-strong);
  font-size: 14px;
}

.recovery-section-heading small {
  margin-top: 3px;
  color: var(--muted-2);
  font-size: 12px;
}

.recovery-section-index {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 38px;
  height: 28px;
  border-radius: 6px;
  color: #185abd;
  background: #e8f0fe;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: .5px;
}

.recovery-section-index.bi-index {
  color: #9a5b00;
  background: #fff1d6;
}

.recovery-section-index.did-index {
  color: #287044;
  background: #e5f5eb;
}

.recovery-form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px 18px;
}

.recovery-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
  color: var(--text-strong);
  font-size: 13px;
  font-weight: 600;
}

.recovery-field em {
  margin-left: 5px;
  color: #c2410c;
  font-size: 11px;
  font-style: normal;
  font-weight: 500;
}

.recovery-field small {
  color: var(--muted-2);
  font-size: 11px;
  font-weight: 400;
}

.recovery-upload-field {
  justify-content: flex-start;
}

.recovery-file-input {
  box-sizing: border-box;
  width: 100%;
  padding: 7px;
  border: 1px dashed #b9c4d3;
  border-radius: 6px;
  background: #fff;
  color: var(--muted-2);
  font-size: 12px;
}

.recovery-did-field {
  max-width: 620px;
}

.recovery-query-row,
.recovery-target-row {
  display: flex;
  align-items: end;
  gap: 12px;
  margin-top: 16px;
}

.recovery-query-hint {
  padding-bottom: 9px;
  color: var(--muted-2);
  font-size: 12px;
  font-weight: 400;
}

.recovery-target-row {
  max-width: 920px;
  display: block;
  padding-top: 14px;
  border-top: 1px solid #e6eaf0;
}

.recovery-pa-select {
  width: 100%;
}

.recovery-pa-popper {
  min-width: 620px;
  max-width: min(920px, calc(100vw - 48px));
}

.recovery-pa-option strong,
.recovery-pa-option small {
  display: block;
  line-height: 1.45;
}

.recovery-pa-option strong {
  color: var(--text-strong);
  font-size: 13px;
}

.recovery-pa-option small {
  color: var(--muted-2);
  font-size: 11px;
}

.recovery-pa-summary {
  margin-top: 12px;
  padding: 13px 14px;
  border-left: 3px solid #3867ff;
  border-radius: 6px;
  background: #f4f7ff;
}

.recovery-pa-summary-title {
  margin-bottom: 9px;
  color: var(--text-strong);
  font-size: 13px;
  font-weight: 700;
}

.recovery-pa-summary-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px 16px;
}

.recovery-pa-summary-grid span {
  min-width: 0;
  color: #344054;
  font-size: 12px;
  overflow-wrap: anywhere;
}

.recovery-pa-summary-grid b {
  display: block;
  margin-bottom: 3px;
  color: var(--muted-2);
  font-size: 11px;
  font-weight: 500;
}

.recovery-pa-features {
  margin-top: 9px;
  color: #344054;
  font-size: 12px;
  overflow-wrap: anywhere;
}

.recovery-server-result {
  margin-top: 16px;
}

@media (max-width: 720px) {
  .recovery-form-grid {
    grid-template-columns: 1fr;
  }

  .recovery-query-row {
    align-items: flex-start;
    flex-direction: column;
  }

  .recovery-query-hint {
    padding-bottom: 0;
  }

  .recovery-pa-summary-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .recovery-pa-popper {
    min-width: min(420px, calc(100vw - 32px));
  }
}
.agent-type-box {
  margin: 12px 0 16px 0;
  padding: 16px;
  background: var(--primary-soft);
  border: 1px solid var(--primary-border);
  border-radius: 8px;
}

.agent-type-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-strong);
  margin-bottom: 10px;
}

.agent-type-desc {
  margin-top: 10px;
  font-size: 12px;
  color: #475467;
  line-height: 1.6;
}

.dependency-toggle-row {
  margin-top: 12px;
  display: flex;
  justify-content: flex-start;
}

.dependency-panel {
  margin-top: 18px;
  padding: 16px;
  border: 1px solid var(--primary-border);
  border-radius: var(--radius-sm);
  background: #fff;
}

.dependency-panel-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 14px;
}

.dependency-title {
  font-size: 15px;
  font-weight: 600;
  color: #1f2d3d;
  margin-bottom: 4px;
}

.dependency-subtitle {
  font-size: 13px;
  color: #607085;
  line-height: 1.6;
}

.dependency-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.dependency-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px;
}

.dependency-item {
  padding: 14px;
  border-radius: 8px;
  background: #fff;
  border: 1px solid var(--border);
}

.dependency-item-single {
  max-width: 420px;
}

.hooks-selection-area {
  margin-top: 16px;
}

.inline-config-hint {
  margin-top: 16px;
}

.hooks-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 14px;
}

.hook-item {
  background: #fff;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 14px;
  cursor: pointer;
  transition: border-color 0.18s ease, box-shadow 0.18s ease;
}

.hook-item:hover {
  border-color: var(--primary-border);
  box-shadow: 0 2px 10px rgba(56, 103, 255, 0.10);
}

.hook-selected {
  border-color: var(--primary-color);
  background: var(--primary-soft);
}

.hook-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.hook-emoji {
  font-size: 18px;
}

.hook-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-strong);
}

.hook-desc {
  font-size: 12px;
  color: #475467;
  line-height: 1.7;
}

.skills-container {
  margin-top: 18px;
  padding-top: 18px;
  border-top: 1px solid var(--border);
}

.skills-user-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 14px;
  flex-wrap: wrap;
}

.skills-hint {
  margin-bottom: 14px;
  font-size: 12px;
  color: var(--muted-2);
}

.skills-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 14px;
}

.skill-card-item {
  background: #fff;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 16px;
  cursor: pointer;
  transition: border-color 0.18s ease, box-shadow 0.18s ease;
}

.skill-card-item:hover {
  border-color: var(--primary-border);
  box-shadow: 0 2px 10px rgba(56, 103, 255, 0.10);
}

.skill-selected {
  border-color: var(--primary-color);
  background: var(--primary-soft);
}

.skill-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.skill-emoji {
  font-size: 18px;
}

.skill-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-strong);
}

.skill-desc {
  font-size: 12px;
  color: #475467;
  line-height: 1.7;
}

.skills-actions {
  margin-top: 16px;
  display: flex;
  justify-content: flex-start;
}

.skills-search-section {
  margin-top: 18px;
  background: var(--primary-soft);
  border: 1px solid var(--primary-border);
  border-radius: var(--radius-sm);
  padding: 16px;
}

.search-input-group {
  display: flex;
  gap: 10px;
}

.search-results {
  margin-top: 12px;
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px;
}

.skills-progress {
  margin-top: 18px;
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 14px;
}

.progress-message {
  margin: 10px 0 0 0;
  font-size: 13px;
  color: #475467;
}

.skills-install-result {
  margin-top: 18px;
  border-radius: 10px;
  padding: 14px;
  border: 1px solid var(--border);
  background: #fff;
}

.result-success {
  border-color: #b7eb8f;
  background: #f6ffed;
}

.result-error {
  border-color: #ffccc7;
  background: #fff2f0;
}

.result-detail {
  margin-top: 8px;
  font-size: 13px;
  color: #475467;
}

.skill-pill {
  display: inline-block;
  padding: 6px 12px;
  border-radius: var(--radius-pill);
  background: var(--primary-soft);
  border: 1px solid var(--primary-border);
  color: var(--primary-ink);
  font-size: 13px;
  font-weight: 500;
}

.installed-skills-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.installed-skill-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: #fff;
}

.installed-skill-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.dependency-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-strong);
  margin-bottom: 8px;
}

.dependency-meta {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.dependency-version {
  font-size: 12px;
  color: #475467;
  word-break: break-all;
}

.dependency-install-actions {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  margin-top: 14px;
}

.dependency-tip {
  margin-top: 12px;
  font-size: 12px;
  color: #6b7280;
  line-height: 1.7;
}

.dependency-tip a {
  color: var(--primary-color);
  text-decoration: none;
}

.dependency-tip a:hover {
  text-decoration: underline;
}

.dependency-result {
  margin-top: 12px;
  background: #f8fafc;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px;
}

.empty-config-tip {
  color: var(--muted-2);
  font-size: 13px;
  padding: 12px;
}

/* Multi-Agent Styles */
.sub-agent-create {
  margin-bottom: 20px;
  padding: 16px;
  background: #f8fafc;
  border-radius: 8px;
}

.agent-group-panel {
  margin-top: 20px;
  padding: 16px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: #fff;
}

.group-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--border-soft);
}

.sub-agents-list {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 16px;
  margin-bottom: 20px;
}

.sub-agent-card {
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 14px;
  background: #fafbfc;
}

.agent-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.agent-name {
  font-size: 16px;
  font-weight: 600;
  color: var(--primary-color);
}

.agent-info {
  font-size: 12px;
  color: #475467;
  margin-bottom: 12px;
}

.agent-info div {
  margin-bottom: 4px;
}

.agent-actions {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
}

.group-actions {
  display: flex;
  gap: 12px;
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid var(--border-soft);
}


</style>