from __future__ import annotations

from typing import Any, Dict, List, Optional
import os
import json
import shutil
import subprocess
import secrets
from pathlib import Path
from datetime import datetime

from crypto_lib import canonical_json, sha256_hex

LLM_PROVIDERS: Dict[str, Dict[str, Any]] = {
    "deepseek": {
        "name": "DeepSeek",
        "default_base_url": "https://api.deepseek.com/v1",
        "models": ["deepseek-v4-pro", "deepseek-v4-flash"],
        "default_model": "deepseek-v4-pro",
        "model_prefix": "openai",
        "api_key": os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY", "")
    },
    "qwen": {
        "name": "通义千问 (Qwen)",
        "default_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "models": ["qwen3-max", "qwen-plus", "qwen-turbo", "qwen-long"],
        "default_model": "qwen-plus",
        "model_prefix": "openai",
        "api_key": os.getenv("QWEN_API_KEY", "")
    },
    "doubao": {
        "name": "豆包 (Doubao)",
        "default_base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "models": ["doubao-pro-256k", "doubao-lite-128k", "doubao-1-5-pro-256k"],
        "default_model": "doubao-pro-256k",
        "model_prefix": "openai",
        "api_key": os.getenv("DOUBAO_API_KEY", "")
    },
    "spark": {
        "name": "讯飞星火 (Spark)",
        "default_base_url": "https://spark-api-open.xf-yun.com/v1",
        "models": ["spark-v4-pro", "spark-v3-5", "spark-lite"],
        "default_model": "spark-v4-pro",
        "model_prefix": "openai",
        "api_key": os.getenv("SPARK_API_KEY", "")
    },
    "openai": {
        "name": "OpenAI",
        "default_base_url": "",
        "models": ["gpt-4o", "gpt-4-turbo", "gpt-4", "gpt-3.5-turbo"],
        "default_model": "gpt-4o",
        "model_prefix": "openai",
        "api_key": os.getenv("OPENAI_API_KEY", "")
    },
}


def get_provider_config(provider_key: str) -> Dict[str, Any]:
    provider_key = provider_key.lower()
    cfg = LLM_PROVIDERS.get(provider_key, LLM_PROVIDERS["deepseek"])
    # 从本机环境变量获取凭据。
    return cfg
class HooksConfig:
    def __init__(self, session_memory: bool = False, bootstrap_extra_files: bool = False,
                 command_logger: bool = False, boot_md: bool = False):
        self.session_memory = session_memory
        self.bootstrap_extra_files = bootstrap_extra_files
        self.command_logger = command_logger
        self.boot_md = boot_md


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _template_dir() -> str:
    return os.path.join(os.getcwd(), "agent_provider", "openclaw", "templates")


def _state_dir(package_dir: str) -> str:
    return os.path.join(package_dir, "state")


def _copy_openclaw_templates(state_dir: str) -> None:
    tpl_dir = _template_dir()
    _ensure_dir(state_dir)

    files = [
        "AGENTS.md",
        "BOOTSTRAP.md",
        "HEARTBEAT.md",
        "IDENTITY.md",
        "MEMORY.md",
        "SOUL.md",
        "TOOLS.md",
        "USER.md",
    ]

    for name in files:
        src = os.path.join(tpl_dir, name)
        dst = os.path.join(state_dir, name)

        if os.path.exists(src):
            shutil.copyfile(src, dst)
        else:
            # 兜底，避免模板缺文件时报错
            with open(dst, "w", encoding="utf-8") as f:
                if name == "MEMORY.md":
                    f.write("# MEMORY.md - Long-Term Memory\n\n_No long-term memory has been recorded yet._\n")
                else:
                    f.write("")


def _write_workspace_state(state_dir: str) -> str:
    path = os.path.join(state_dir, "workspace-state.json")
    obj = {
        "version": 1,
        "bootstrapSeededAt": datetime.utcnow().isoformat() + "Z",
        "createdBy": "personal-agent",
        "agentType": "openclaw",
        "identityBound": True,
    }

    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)

    return path


def _debug_build_openclaw_state_only(root: str) -> Dict[str, Any]:
    package_dir = os.path.join(root, "openclaw_package")
    state_dir = _state_dir(package_dir)

    _ensure_dir(package_dir)
    _ensure_dir(state_dir)
    _ensure_openclaw_state_subdirs(state_dir)
    _copy_openclaw_templates(state_dir)
    workspace_state_path = _write_workspace_state(state_dir)

    return {
        "package_dir": package_dir,
        "state_dir": state_dir,
        "workspace_state_path": workspace_state_path,
    }


def _ensure_openclaw_state_subdirs(state_dir: str) -> None:
    for sub in ["memory", "credentials", "sessions", "workspace"]:
        _ensure_dir(os.path.join(state_dir, sub))


def _cmc_labels(cmc: List[List[Dict[str, Any]]]) -> List[str]:
    labels: List[str] = []

    for row in cmc or []:
        for item in row or []:
            if isinstance(item, dict):
                label = str(item.get("label") or "").strip()
            else:
                label = str(item or "").strip()

            if label:
                labels.append(label)

    return labels


def detect_agent_type(cmc: List[List[Dict[str, Any]]]) -> str:
    """
    只要 CMC 里出现 openclaw，就走 OpenClaw 分支。
    否则默认 Octopus。
    """
    labels = set(_cmc_labels(cmc))

    if "openclaw" in labels or "agent-openclaw" in labels:
        return "openclaw"

    return "octopus"


def _labels_by_row(cmc: List[List[Dict[str, Any]]], idx: int) -> List[str]:
    if len(cmc or []) <= idx:
        return []

    out: List[str] = []

    for item in cmc[idx] or []:
        if isinstance(item, dict):
            label = str(item.get("label") or "").strip()
        else:
            label = str(item or "").strip()

        if label:
            out.append(label)

    return out


def _enabled(labels: List[str], *names: str) -> bool:
    label_set = set(labels)
    return any(name in label_set for name in names)


def build_openclaw_policy(cmc: List[List[Dict[str, Any]]]) -> Dict[str, Any]:
    """
    将 CMC 转成 OpenClaw PA 的能力策略。
    这个 policy 会写入 state/openclaw.json，并追加到 TOOLS.md。
    """
    runtime = _labels_by_row(cmc, 0)
    gateway = _labels_by_row(cmc, 1)
    personality = _labels_by_row(cmc, 2)
    tools = _labels_by_row(cmc, 3)
    channels = _labels_by_row(cmc, 4)
    appearance = _labels_by_row(cmc, 5)

    return {
        "runtime": {
            "openclaw": _enabled(runtime, "openclaw", "agent-openclaw"),
        },
        "gateway": {
            "localhost": _enabled(gateway, "localhost-gateway"),
            "tailscale": _enabled(gateway, "tailscale-gateway"),
            "shared_secret": _enabled(gateway, "shared-secret"),
        },
        "personality": {
            "default_soul": _enabled(personality, "default-soul"),
            "strict_privacy": _enabled(personality, "strict-privacy"),
        },
        "tools": {
            "local_memory": _enabled(tools, "local-memory"),
            "long_term_memory": _enabled(tools, "long-term-memory"),
            "browser_control": _enabled(tools, "browser-control"),
            "file_access": _enabled(tools, "file-access"),
            "shell_run": _enabled(tools, "shell-run"),
            "camera": _enabled(tools, "camera"),
            "canvas": _enabled(tools, "canvas"),
        },
        "channels": {
            "text": _enabled(channels, "text"),
            "webchat": _enabled(channels, "webchat"),
            "telegram": _enabled(channels, "telegram"),
            "discord": _enabled(channels, "discord"),
            "slack": _enabled(channels, "slack"),
        },
        "appearance": {
            "theme": appearance[0] if appearance else "appearance-purple",
        },
    }


def build_openclaw_binding(
        phc: Dict[str, Any],
        pa: Dict[str, Any] | None,
        cmc: List[List[Dict[str, Any]]],
        hid: str,
        package_cmi: str | None = None,
) -> Dict[str, Any]:
    """
    生成 OpenClaw 的身份绑定文件 openclaw_binding.json。

    注意：
    OpenClaw 绑定层统一使用 SCID.AF。
    不再优先使用 ASO.TPM.AF，避免 AP 阶段错误覆盖 TPM.AF 后导致 af 与 scid.AF 不一致。
    """
    pa = pa or {}

    did = (
            phc.get("DID")
            or ((phc.get("ASO") or {}).get("TPM") or {}).get("CDID")
    )

    scid = phc.get("SCID") or {}
    if isinstance(scid, str):
        try:
            import json
            scid = json.loads(scid)
        except:
            scid = {}
    scid_af = scid.get("AF")

    af = str(scid_af) if scid_af is not None else str(
        ((phc.get("ASO") or {}).get("TPM") or {}).get("AF") or ""
    )

    apm = pa.get("APM") or {}
    apa = pa.get("APA") or {}
    proof = phc.get("PROOF") or {}

    phc_hash = sha256_hex(canonical_json(phc))
    pa_hash = sha256_hex(canonical_json(pa)) if pa else None
    llm_public_config = extract_llm_public_config(cmc)
    llm_binding_hash = sha256_hex(canonical_json(llm_public_config))

    binding = {
        "agent_type": "openclaw",
        "created_at": datetime.utcnow().isoformat() + "Z",
        "phc_id": phc.get("id"),
        "did": did,
        "hid": hid,
        "af": af,
        "scid": scid,
        "cmi": apm.get("CMI"),
        "package_cmi": str(package_cmi) if package_cmi is not None else None,
        "phc_hash": phc_hash,
        "pa_hash": pa_hash,
        "llm_binding": {
            "provider": llm_public_config.get("provider"),
            "model": llm_public_config.get("model"),
            "base_url": llm_public_config.get("base_url"),
            "compatibility": llm_public_config.get("compatibility"),
            "hash": llm_binding_hash,
        },
        "modules": {
            "runtime": _labels_by_row(cmc, 0),
            "gateway": _labels_by_row(cmc, 1),
            "personality": _labels_by_row(cmc, 2),
            "hooks": _labels_by_row(cmc, 3),
            "skills": _labels_by_row(cmc, 4),
            "llm": _labels_by_row(cmc, 5),
            "knowledge": _labels_by_row(cmc, 6),
            "channels": _labels_by_row(cmc, 7),
            "appearance": _labels_by_row(cmc, 8),
        },
        "binding": {
            "PHC_id": phc.get("id"),
            "SCID": scid,
            "APid": apa.get("APid"),
            "TPid": (phc.get("TPA") or {}).get("TPid"),
        },
        "proof": {
            "APA": apa.get("APproof"),
            "APCH": proof.get("APCH"),
            "APCH_r": proof.get("APCH_r"),
            "TPCH": proof.get("TPCH"),
            "CHproof": proof.get("CHproof"),
        },
        "note": "This OpenClaw instance is bound to PHC/PA without exposing PII or BI.",
    }

    return binding


def build_openclaw_package(
        root: str,
        phc: Dict[str, Any],
        cmc: List[List[Dict[str, Any]]],
        hid: str,
        pa: Dict[str, Any] | None = None,
        package_cmi: str | None = None,
        hooks_config: Optional[Dict[str, bool]] = None,
        skills_config: Optional[List[str]] = None,
        llm_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    在 local_store/agents/<phc_id>/openclaw_package 下生成 OpenClaw 个人配置包。

    新结构：
      openclaw_package/
        manifest.json
        openclaw_binding.json
        runtime_info.json
        state/
          openclaw.json
          workspace-state.json
          AGENTS.md
          BOOTSTRAP.md
          HEARTBEAT.md
          IDENTITY.md
          MEMORY.md
          SOUL.md
          TOOLS.md
          USER.md
          memory/
          credentials/
          sessions/
          workspace/
    """
    
    pa = pa or {}

    package_dir = os.path.join(root, "openclaw_package")
    state_dir = _state_dir(package_dir)

    # 重新生成 package，避免旧文件残留
    if os.path.exists(package_dir):
        shutil.rmtree(package_dir, ignore_errors=True)

    _ensure_dir(package_dir)
    _ensure_dir(state_dir)

    _remove_legacy_codex_wrappers(package_dir)

        # 0. 从 CMC 中提取模型公开配置
    # 注意：这里不包含 API Key，只包含 provider/model/base_url/compatibility
    llm_public_config = extract_llm_public_config(cmc)

    # 0.1 合并模型配置
    # 原则：
    # - provider/model/base_url 以 CMC 为准，用于身份绑定
    # - api_key 仍然来自前端 llm_config，用于写入 .env
    merged_llm_config = dict(llm_config or {})

    merged_llm_config["provider"] = llm_public_config.get("provider")
    merged_llm_config["model"] = llm_public_config.get("model")
    merged_llm_config["base_url"] = llm_public_config.get("base_url")
    merged_llm_config["compatibility"] = llm_public_config.get("compatibility")

    # 0.2 生成每个 PA 独立的 .env
    env_path = _write_openclaw_env_template(
        package_dir,
        llm_config=merged_llm_config,
    )
    # 1. 创建 state 子目录
    _ensure_openclaw_state_subdirs(state_dir)

    # 2. 复制模板 md 文件到 state/
    _copy_openclaw_templates(state_dir)

    # 3. 生成 workspace-state.json
    workspace_state_path = _write_workspace_state(state_dir)

    # 4. 生成 policy
    policy = build_openclaw_policy(cmc)

    # 5. 生成 binding
    binding = build_openclaw_binding(
        phc=phc,
        pa=pa,
        cmc=cmc,
        hid=hid,
        package_cmi=package_cmi,
    )

    binding_path = os.path.join(package_dir, "openclaw_binding.json")
    _write_json_file(binding_path, binding)
    llm_public_config = extract_llm_public_config(cmc)
    llm_config_hash = sha256_hex(canonical_json(llm_public_config))

    # 6. 生成 runtime_info.json
    runtime_info_path = _write_runtime_info(package_dir)

    # 7. 生成 state/openclaw.json
    config_path = _write_openclaw_config(
        state_dir=state_dir,
        phc=phc,
        pa=pa,
        policy=policy,
        env_path=env_path,
        cmc=cmc,
        hid=hid,
    )

    # 8. 将身份上下文追加到模板 md
    _append_identity_context_to_templates(
        state_dir=state_dir,
        phc=phc,
        pa=pa,
        cmc=cmc,
        policy=policy,
    )

    # 9. 生成 package manifest
    did = (
            phc.get("DID")
            or ((phc.get("ASO") or {}).get("TPM") or {}).get("CDID")
    )

    manifest = {
        "agent_type": "openclaw",
        "created_at": datetime.utcnow().isoformat() + "Z",
        "phc_id": phc.get("id"),
        "did": did,
        "hid": hid,
        "package_cmi": str(package_cmi) if package_cmi is not None else None,
        "package_dir": package_dir,
        "state_dir": state_dir,
        "binding_path": binding_path,
        "config_path": config_path,
        "runtime_info_path": runtime_info_path,
        "workspace_state_path": workspace_state_path,
        "policy": policy,
        "llm_runtime": {
            "provider": llm_public_config.get("provider"),
            "model": llm_public_config.get("model"),
            "base_url": llm_public_config.get("base_url"),
            "compatibility": llm_public_config.get("compatibility"),
            "llm_config_hash": llm_config_hash,
            "api_key_configured": bool((llm_config or {}).get("api_key")),
        },
        "files": {
            "binding": "openclaw_binding.json",
            "runtime": "runtime_info.json",
            "config": "state/openclaw.json",
            "env": ".env",
            "workspace_state": "state/workspace-state.json",
            "templates": [
                "state/AGENTS.md",
                "state/BOOTSTRAP.md",
                "state/HEARTBEAT.md",
                "state/IDENTITY.md",
                "state/MEMORY.md",
                "state/SOUL.md",
                "state/TOOLS.md",
                "state/USER.md",
            ],
        },
    }

    manifest_path = os.path.join(package_dir, "manifest.json")
    _write_json_file(manifest_path, manifest)
    # 10. 配置 Hooks（如果提供了配置）
    if hooks_config:
       _configure_hooks_in_package(package_dir, hooks_config)

    # 11. 安装 Skills（如果提供了配置）
    if skills_config:
       _install_skills_in_package(package_dir, skills_config)

    return {
        "package_dir": package_dir,
        "state_dir": state_dir,
        "config_path": config_path,
        "binding_path": binding_path,
        "runtime_info_path": runtime_info_path,
        "manifest_path": manifest_path,
        "workspace_state_path": workspace_state_path,
        "deploy_script": None,
        "launcher": None,
        "binding": binding,
        "policy": policy,
    }


def _write_deploy_script(root: str) -> str:
    path = os.path.join(root, "deploy_openclaw_personal.bat")

    content = r"""@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul

set "SCRIPT_DIR=%~dp0"
set "PACKAGE_DIR=%SCRIPT_DIR%openclaw_package"
set "OPENCLAW_STATE_DIR=%PACKAGE_DIR%\state"
set "OPENCLAW_CONFIG_PATH=%OPENCLAW_STATE_DIR%\openclaw.json"
set "OPENCLAW_BINDING_PATH=%PACKAGE_DIR%\openclaw_binding.json"
set "NPM_PREFIX=%OPENCLAW_STATE_DIR%\npm"

echo ==========================================
echo Deploying Personal OpenClaw PA
echo ==========================================
echo.

where node >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Node.js not found. Please install Node.js first.
  pause
  exit /b 1
)

where npm >nul 2>nul
if errorlevel 1 (
  echo [ERROR] npm not found. Please install npm first.
  pause
  exit /b 1
)

if not exist "%OPENCLAW_STATE_DIR%" mkdir "%OPENCLAW_STATE_DIR%"
if not exist "%OPENCLAW_STATE_DIR%\memory" mkdir "%OPENCLAW_STATE_DIR%\memory"
if not exist "%OPENCLAW_STATE_DIR%\credentials" mkdir "%OPENCLAW_STATE_DIR%\credentials"
if not exist "%OPENCLAW_STATE_DIR%\sessions" mkdir "%OPENCLAW_STATE_DIR%\sessions"
if not exist "%OPENCLAW_STATE_DIR%\workspace" mkdir "%OPENCLAW_STATE_DIR%\workspace"
if not exist "%NPM_PREFIX%" mkdir "%NPM_PREFIX%"

echo.
echo Installing package-bound OpenClaw and Codex...
echo NPM_PREFIX=%NPM_PREFIX%
echo.

call npm install --prefix "%NPM_PREFIX%" openclaw @openai/codex

if errorlevel 1 (
  echo [ERROR] Failed to install package-bound OpenClaw/Codex.
  pause
  exit /b 1
)

echo.
echo Checking package-bound OpenClaw:
if exist "%NPM_PREFIX%\node_modules\.bin\openclaw.cmd" (
  call "%NPM_PREFIX%\node_modules\.bin\openclaw.cmd" --version
) else (
  echo [ERROR] package-bound openclaw.cmd missing.
  pause
  exit /b 1
)

echo.
echo Checking package-bound Codex:
if exist "%NPM_PREFIX%\node_modules\@openai\codex\bin\codex.js" (
  echo codex.js exists
) else (
  echo [ERROR] package-bound codex.js missing.
  pause
  exit /b 1
)

echo.
echo Cleaning stale plugin-skills...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Remove-Item '%OPENCLAW_STATE_DIR%\plugin-skills' -Force -Recurse -ErrorAction SilentlyContinue; New-Item -ItemType Directory -Path '%OPENCLAW_STATE_DIR%\plugin-skills' -Force | Out-Null"

echo.
echo [OK] OpenClaw deployment ready.
echo.
echo OPENCLAW_STATE_DIR=%OPENCLAW_STATE_DIR%
echo OPENCLAW_CONFIG_PATH=%OPENCLAW_CONFIG_PATH%
echo OPENCLAW_BINDING_PATH=%OPENCLAW_BINDING_PATH%
echo NPM_PREFIX=%NPM_PREFIX%
echo.

pause
"""
    return _write_text_file(path, content)


def _write_gateway_run_script(root: str) -> str:
    """
    生成 run_openclaw_gateway_personal.bat。
    该脚本只使用当前 PA 包里的 package-bound OpenClaw/Codex。
    """
    path = os.path.join(root, "run_openclaw_gateway_personal.bat")

    content = r"""@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul

set "SCRIPT_DIR=%~dp0"
set "PACKAGE_DIR=%SCRIPT_DIR%openclaw_package"
set "OPENCLAW_STATE_DIR=%PACKAGE_DIR%\state"
set "OPENCLAW_CONFIG_PATH=%OPENCLAW_STATE_DIR%\openclaw.json"
set "OPENCLAW_BINDING_PATH=%PACKAGE_DIR%\openclaw_binding.json"
set "PERSONAL_AGENT_MANIFEST=%SCRIPT_DIR%agent_manifest.json"
set "OPENCLAW_ENV_PATH=%PACKAGE_DIR%\.env"
set "NPM_PREFIX=%OPENCLAW_STATE_DIR%\npm"

if exist "%OPENCLAW_ENV_PATH%" (
  echo Loading env file:
  echo %OPENCLAW_ENV_PATH%
  for /f "usebackq eol=# tokens=1,* delims==" %%A in ("%OPENCLAW_ENV_PATH%") do (
    if not "%%A"=="" (
      set "%%A=%%B"
    )
  )
) else (
  echo [WARN] .env not found:
  echo %OPENCLAW_ENV_PATH%
)

echo.
echo Model env:
echo OPENCLAW_MODEL=%OPENCLAW_MODEL%
echo OPENAI_API_KEY loaded: %OPENAI_API_KEY:~0,7%****
echo.

if not defined OPENAI_API_KEY (
  echo [ERROR] OPENAI_API_KEY is missing.
  echo Please edit:
  echo %OPENCLAW_ENV_PATH%
  echo.
  pause
  exit /b 1
)

set "KEY_PREFIX=%OPENAI_API_KEY:~0,3%"
set "IS_DEEPSEEK=false"

if not defined OPENAI_BASE_URL (
  echo %OPENAI_API_KEY% | findstr /b /c:"sk-" >nul
  if errorlevel 1 (
    echo [ERROR] OPENAI_API_KEY does not look like an OpenAI Platform key.
    echo It should start with sk- or sk-proj-
    echo Or set OPENAI_BASE_URL for other providers like DeepSeek.
    echo Current prefix:
    echo %OPENAI_API_KEY:~0,10%
    echo.
    pause
    exit /b 1
  )
) else (
  echo Using custom API base URL: %OPENAI_BASE_URL%
  echo OPENCLAW_MODEL=%OPENCLAW_MODEL%
)

if not exist "%OPENCLAW_STATE_DIR%" mkdir "%OPENCLAW_STATE_DIR%"
if not exist "%OPENCLAW_STATE_DIR%\memory" mkdir "%OPENCLAW_STATE_DIR%\memory"
if not exist "%OPENCLAW_STATE_DIR%\credentials" mkdir "%OPENCLAW_STATE_DIR%\credentials"
if not exist "%OPENCLAW_STATE_DIR%\sessions" mkdir "%OPENCLAW_STATE_DIR%\sessions"
if not exist "%OPENCLAW_STATE_DIR%\workspace" mkdir "%OPENCLAW_STATE_DIR%\workspace"

cd /d "%PACKAGE_DIR%"

set "PATH=%NPM_PREFIX%\node_modules\.bin;%PATH%"
set "NODE_PATH=%NPM_PREFIX%\node_modules"

REM Important:
REM Point OpenClaw to the real Codex Node entrypoint.
REM Do NOT point this to a .cmd wrapper.
REM Do NOT use a wrapper that adds "app-server" manually.
set "OPENCLAW_CODEX_APP_SERVER_BIN=%NPM_PREFIX%\node_modules\@openai\codex\bin\codex.js"

echo ==========================================
echo OpenClaw Personal Gateway Runner
echo ==========================================
echo.
echo Package:
echo %PACKAGE_DIR%
echo.
echo State Dir:
echo %OPENCLAW_STATE_DIR%
echo.
echo Config:
echo %OPENCLAW_CONFIG_PATH%
echo.
echo Binding:
echo %OPENCLAW_BINDING_PATH%
echo.
echo Package-bound OpenClaw:
echo %NPM_PREFIX%\node_modules\.bin\openclaw.cmd
echo.
echo Codex app-server Node entry:
echo %OPENCLAW_CODEX_APP_SERVER_BIN%
echo.

if exist "%NPM_PREFIX%\node_modules\.bin\openclaw.cmd" (
  echo package openclaw exists
) else (
  echo [ERROR] package openclaw missing.
  echo Please run deploy_openclaw_personal.bat first.
  pause
  exit /b 1
)

if exist "%OPENCLAW_CODEX_APP_SERVER_BIN%" (
  echo codex app-server node entry exists
) else (
  echo [ERROR] codex app-server node entry missing.
  echo Please run deploy_openclaw_personal.bat first.
  pause
  exit /b 1
)

echo.
echo Cleaning stale plugin-skills symlinks...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Remove-Item '%OPENCLAW_STATE_DIR%\plugin-skills' -Force -Recurse -ErrorAction SilentlyContinue; New-Item -ItemType Directory -Path '%OPENCLAW_STATE_DIR%\plugin-skills' -Force | Out-Null"
echo Done.
echo.

echo Starting package-bound OpenClaw Gateway...
echo.

call "%NPM_PREFIX%\node_modules\.bin\openclaw.cmd" gateway run

echo.
echo [ERROR] OpenClaw Gateway process exited.
pause
"""
    return _write_text_file(path, content)


def _write_dashboard_ps1_script(root: str) -> str:
    """
    生成 open_dashboard_personal.ps1。
    使用 package-bound openclaw.cmd 打开 dashboard。
    """
    path = os.path.join(root, "open_dashboard_personal.ps1")

    content = r'''param(
  [string]$PackageDir,
  [string]$StateDir,
  [string]$ConfigPath,
  [string]$BindingPath
)

$ErrorActionPreference = "Stop"

$env:OPENCLAW_STATE_DIR = $StateDir
$env:OPENCLAW_CONFIG_PATH = $ConfigPath
$env:OPENCLAW_BINDING_PATH = $BindingPath

$npmPrefix = Join-Path $StateDir "npm"
$binDir = Join-Path $npmPrefix "node_modules\.bin"
$nodeModules = Join-Path $npmPrefix "node_modules"
$openclawCmd = Join-Path $binDir "openclaw.cmd"

$env:PATH = "$binDir;$env:PATH"
$env:NODE_PATH = $nodeModules
$env:OPENCLAW_CODEX_APP_SERVER_BIN = Join-Path $nodeModules "@openai\codex\bin\codex.js"

$envPath = Join-Path $PackageDir ".env"
if (Test-Path $envPath) {
    Get-Content $envPath | ForEach-Object {
        $line = $_.Trim()
        if (-not $line) { return }
        if ($line.StartsWith("#")) { return }

        $idx = $line.IndexOf("=")
        if ($idx -le 0) { return }

        $key = $line.Substring(0, $idx).Trim()
        $val = $line.Substring($idx + 1).Trim().Trim('"')

        if ($key) {
            [Environment]::SetEnvironmentVariable($key, $val, "Process")
        }
    }
}

if (-not (Test-Path $openclawCmd)) {
    Write-Host "package-bound openclaw.cmd not found:"
    Write-Host $openclawCmd
    exit 1
}

Set-Location $PackageDir

$out = & $openclawCmd dashboard --no-open 2>&1 | Out-String

Start-Sleep -Milliseconds 300

$clip = ""
try {
    $clip = Get-Clipboard
} catch {
    $clip = ""
}

if ($clip -match 'https?://[^\s"]+') {
    $url = $Matches[0]

    if ($url -match 'token=') {
        Write-Output $url
        exit 0
    }
}

$clean = $out -replace "`e\[[0-9;]*m", ""
$m = [regex]::Match($clean, 'https?://[^\s"]+')

if ($m.Success) {
    Write-Output $m.Value
    exit 0
}

Write-Host "Failed to get dashboard URL."
Write-Host "OpenClaw output:"
Write-Host $out
Write-Host "Clipboard:"
Write-Host $clip
exit 1
'''

    return _write_text_file(path, content)

def _normalize_openclaw_model(model: str, provider_prefix: str = "openai", default_model: str = "gpt-4o") -> str:
    model = str(model or "").strip()
    if not model:
        model = default_model

    if "/" in model:
        return model

    return f"{provider_prefix}/{model}"
def extract_llm_public_config(cmc: List[List[Dict[str, Any]]]) -> Dict[str, Any]:
    """
    从 CMC 中提取可以参与身份绑定的模型公开配置。
    注意：这里绝对不包含 API Key。
    """
    for row in cmc or []:
        for item in row or []:
            if not isinstance(item, dict):
                continue

            label = str(item.get("label") or "").strip()
            params = item.get("params") or {}

            if label == "llm-model":
                provider = str(params.get("provider") or "openai").strip()
                model = str(params.get("model") or "gpt-4o").strip()
                base_url = str(params.get("base_url") or "").strip()
                compatibility = str(params.get("compatibility") or "openai-compatible").strip()
                
                provider_cfg = get_provider_config(provider)
                prefix = str(provider_cfg.get("model_prefix") or "openai").strip()

                return {
                    "provider": provider,
                    "model": _normalize_openclaw_model(model, provider_prefix=prefix),
                    "base_url": base_url,
                    "compatibility": compatibility,
                }

    return {
        "provider": "openai",
        "model": "openai/gpt-4o",
        "base_url": "",
        "compatibility": "openai-native",
    }
def _write_openclaw_env_template(package_dir: str, llm_config: Dict[str, Any] | None = None) -> str:
    """
    为每个个人 OpenClaw PA 生成独立 .env。

    llm_config 格式:
    {
        "provider": "deepseek" | "qwen" | "doubao" | "spark" | "openai",
        "api_key": "sk-xxx",
        "base_url": "https://...",
        "model": "deepseek-v4-pro"
    }
    """
    path = os.path.join(package_dir, ".env")

    if os.path.exists(path):
        return path

    if llm_config:
        provider_key = str(llm_config.get("provider") or "deepseek").lower().strip()
        provider_cfg = get_provider_config(provider_key)

        api_key = str(
            llm_config.get("api_key")
            or provider_cfg.get("api_key")
            or ""
        ).strip()

        base_url = str(
            llm_config.get("base_url")
            or provider_cfg.get("default_base_url")
            or ""
        ).strip()

        raw_model = str(
            llm_config.get("model")
            or provider_cfg.get("default_model")
            or "gpt-4o"
        ).strip()

        prefix = str(provider_cfg.get("model_prefix") or "openai").strip()

        full_model = _normalize_openclaw_model(
            raw_model,
            provider_prefix=prefix,
        )

        if not api_key:
            raise ValueError(f"missing api_key for llm provider: {provider_key}")

        content = f"""# Personal OpenClaw PA environment
# Provider: {provider_cfg.get('name', provider_key)}
# Generated automatically, do NOT edit unless needed.
OPENAI_API_KEY={api_key}
OPENCLAW_MODEL={full_model}
OPENAI_BASE_URL={base_url}
LLM_PROVIDER={provider_key}
"""
        return _write_text_file(path, content)

    template_env = os.path.join(
        os.getcwd(),
        "agent_provider",
        "openclaw",
        ".env",
    )

    if os.path.exists(template_env):
        shutil.copyfile(template_env, path)
        return path

    content = """# Personal OpenClaw PA environment
# This file belongs only to this generated personal agent.
# Do NOT commit this file to git if it contains real API keys.
#
OPENAI_API_KEY=
OPENCLAW_MODEL=openai/gpt-4o
OPENAI_BASE_URL=
LLM_PROVIDER=openai
"""

    return _write_text_file(path, content)


def _remove_legacy_codex_wrappers(package_dir: str) -> None:
    """
    删除旧的 codex wrapper。
    旧 wrapper 如果手动加 app-server，会导致：
      codex app-server app-server
    然后报 unrecognized subcommand 'app-server'
    """
    for name in ("codex-app-server.cmd", "codex-app-server.js"):
        path = os.path.join(package_dir, name)
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass


def _write_launch_script(root: str) -> str:
    """
    生成 launch_openclaw_personal.bat。

    目标效果：
    用户双击该脚本后：
      1. 设置当前个人 OpenClaw PA 的 state/config/binding
      2. 生成或确认 Gateway token
      3. 启动当前 PA 专属 Gateway runner
      4. 打开 OpenClaw Dashboard 对话平台
    """
    # 先生成独立 Gateway runner，避免 start/cmd 转义复杂导致 gateway 没启动
    _write_gateway_run_script(root)
    _write_dashboard_ps1_script(root)

    path = os.path.join(root, "launch_openclaw_personal.bat")

    content = r"""@echo off
setlocal enabledelayedexpansion

chcp 65001 >nul

set "SCRIPT_DIR=%~dp0"
set "PACKAGE_DIR=%SCRIPT_DIR%openclaw_package"
set "OPENCLAW_STATE_DIR=%PACKAGE_DIR%\state"
set "OPENCLAW_CONFIG_PATH=%OPENCLAW_STATE_DIR%\openclaw.json"
set "OPENCLAW_BINDING_PATH=%PACKAGE_DIR%\openclaw_binding.json"
set "PERSONAL_AGENT_MANIFEST=%SCRIPT_DIR%agent_manifest.json"
set "GATEWAY_RUNNER=%SCRIPT_DIR%run_openclaw_gateway_personal.bat"
set "OPEN_DASHBOARD_PS1=%SCRIPT_DIR%open_dashboard_personal.ps1"
set "OPENCLAW_ENV_PATH=%PACKAGE_DIR%\.env"

if exist "%OPENCLAW_ENV_PATH%" (
  echo Loading env file:
  echo %OPENCLAW_ENV_PATH%
  for /f "usebackq eol=# tokens=1,* delims==" %%A in ("%OPENCLAW_ENV_PATH%") do (
    if not "%%A"=="" (
      set "%%A=%%B"
    )
  )
) else (
  echo [WARN] .env not found:
  echo %OPENCLAW_ENV_PATH%
)

echo.
echo Model env:
echo OPENCLAW_MODEL=%OPENCLAW_MODEL%
echo OPENAI_API_KEY loaded: %OPENAI_API_KEY:~0,7%****
echo.

echo ==========================================
echo Launching Personal OpenClaw Dashboard
echo ==========================================
echo.

echo Agent Dir:
echo %SCRIPT_DIR%
echo.
echo Package:
echo %PACKAGE_DIR%
echo.
echo State Dir:
echo %OPENCLAW_STATE_DIR%
echo.
echo Config:
echo %OPENCLAW_CONFIG_PATH%
echo.
echo Binding:
echo %OPENCLAW_BINDING_PATH%
echo.
echo Manifest:
echo %PERSONAL_AGENT_MANIFEST%
echo.
echo Gateway Runner:
echo %GATEWAY_RUNNER%
echo.
echo Dashboard PS1:
echo %OPEN_DASHBOARD_PS1%
echo.

set "NPM_PREFIX=%OPENCLAW_STATE_DIR%\npm"
set "PACKAGE_OPENCLAW=%NPM_PREFIX%\node_modules\.bin\openclaw.cmd"

if not exist "%PACKAGE_OPENCLAW%" (
  echo [ERROR] Package-bound OpenClaw CLI not found.
  echo Please run deploy_openclaw_personal.bat first.
  echo Missing:
  echo %PACKAGE_OPENCLAW%
  echo.
  pause
  exit /b 1
)

if not exist "%PACKAGE_DIR%" (
  echo [ERROR] openclaw_package not found:
  echo %PACKAGE_DIR%
  echo.
  pause
  exit /b 1
)

if not exist "%GATEWAY_RUNNER%" (
  echo [ERROR] Gateway runner not found:
  echo %GATEWAY_RUNNER%
  echo.
  pause
  exit /b 1
)

if not exist "%OPEN_DASHBOARD_PS1%" (
  echo [ERROR] open_dashboard_personal.ps1 not found:
  echo %OPEN_DASHBOARD_PS1%
  echo.
  pause
  exit /b 1
)

if not exist "%OPENCLAW_STATE_DIR%" mkdir "%OPENCLAW_STATE_DIR%"
if not exist "%OPENCLAW_STATE_DIR%\memory" mkdir "%OPENCLAW_STATE_DIR%\memory"
if not exist "%OPENCLAW_STATE_DIR%\credentials" mkdir "%OPENCLAW_STATE_DIR%\credentials"
if not exist "%OPENCLAW_STATE_DIR%\sessions" mkdir "%OPENCLAW_STATE_DIR%\sessions"
if not exist "%OPENCLAW_STATE_DIR%\workspace" mkdir "%OPENCLAW_STATE_DIR%\workspace"

echo [1/4] Checking package-bound OpenClaw version...
call "%PACKAGE_OPENCLAW%" --version
echo.

echo [2/4] Stopping global scheduled Gateway if it is running...
schtasks /End /TN "OpenClaw Gateway" >nul 2>nul
schtasks /Change /TN "OpenClaw Gateway" /DISABLE >nul 2>nul
echo Done.
echo.

echo [3/4] Starting package-bound Gateway runner...
echo.
echo A new window named "OpenClaw Personal Gateway" should open.
echo Keep that window open.
echo.

if not defined OPENAI_API_KEY (
  echo [ERROR] OPENAI_API_KEY is missing.
  echo Please edit this file:
  echo %OPENCLAW_ENV_PATH%
  echo.
  echo Required:
  echo OPENAI_API_KEY=your_key_here
  echo.
  pause
  exit /b 1
)

start "OpenClaw Personal Gateway" cmd /k call "%GATEWAY_RUNNER%"

echo Waiting for Gateway to initialize...
timeout /t 25 /nobreak >nul
echo.

echo [4/4] Opening authenticated OpenClaw Dashboard...
echo.

set "DASHBOARD_URL="

for /f "usebackq delims=" %%U in (`powershell -NoProfile -ExecutionPolicy Bypass -File "%OPEN_DASHBOARD_PS1%" -PackageDir "%PACKAGE_DIR%" -StateDir "%OPENCLAW_STATE_DIR%" -ConfigPath "%OPENCLAW_CONFIG_PATH%" -BindingPath "%OPENCLAW_BINDING_PATH%"`) do (
  echo %%U | findstr /r /c:"^http://.*token=" /c:"^https://.*token=" >nul
  if not errorlevel 1 (
    set "DASHBOARD_URL=%%U"
  )
)

if not defined DASHBOARD_URL (
  echo [ERROR] Failed to get authenticated dashboard URL.
  echo Please check whether OpenClaw Gateway is running.
  echo.
  pause
  exit /b 1
)

echo Authenticated Dashboard URL:
echo %DASHBOARD_URL%
echo.

start "" "%DASHBOARD_URL%"

echo.
echo ==========================================
echo OpenClaw Dashboard opened with authenticated URL.
echo.
echo If the browser still shows the connection page:
echo   1. Check browser address bar.
echo   2. It should contain token=...
echo   3. If not, run this in PowerShell:
echo      Get-Clipboard
echo.
echo IMPORTANT:
echo Do NOT run "openclaw dashboard" or "openclaw doctor" without personal env vars.
echo ==========================================
echo.

pause
"""
    return _write_text_file(path, content)


def _write_json_file(path: str, obj: Dict[str, Any]) -> str:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)

    return path


def _write_text_file(path: str, content: str) -> str:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

    return path


def _safe_cmd_version(cmd: List[str]) -> str | None:
    try:
        p = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=8,
            shell=False,
        )
        if p.returncode == 0:
            return (p.stdout or p.stderr or "").strip()
    except Exception:
        return None

    return None


def _write_runtime_info(package_dir: str) -> str:
    path = os.path.join(package_dir, "runtime_info.json")

    obj = {
        "install_mode": "package-bound-npm-prefix",
        "command": "state/npm/node_modules/.bin/openclaw.cmd",
        "node_version": _safe_cmd_version(["node", "--version"]),
        "npm_version": _safe_cmd_version(["npm", "--version"]),
        "openclaw_version": _safe_cmd_version(["openclaw", "--version"]),
        "created_at": datetime.utcnow().isoformat() + "Z",
    }

    return _write_json_file(path, obj)


def _configure_hooks_from_cmc(cmc: List[List[Dict[str, Any]]], config: dict) -> None:
    """从 CMC 中提取 Hook 配置并更新 openclaw.json"""
    selected_hooks = []

    for row in cmc:
        for item in row:
            if not isinstance(item, dict):
                continue
            label = item.get("label", "")
            params = item.get("params", {})
            if label.startswith("hook-") and not params.get("modifiable", True):
                hook_type = label.replace("hook-", "")
                selected_hooks.append(hook_type)

    if not selected_hooks:
        return

    config.setdefault("hooks", {})
    config["hooks"].setdefault("internal", {})
    config["hooks"]["internal"].setdefault("entries", {})

    hook_mapping = {
        "session-memory": "session-memory",
        "command-logger": "command-logger",
        "bootstrap-files": "bootstrap-extra-files",
        "boot-md": "boot-md"
    }

    for hook_label in selected_hooks:
        hook_name = hook_mapping.get(hook_label, hook_label)
        config["hooks"]["internal"]["entries"][hook_name] = {"enabled": True}


def _configure_initial_skills_from_cmc(cmc: List[List[Dict[str, Any]]]) -> List[str]:
    """从 CMC 中提取初始 Skill 配置，返回技能 slug 列表"""
    selected_skills = []

    for row in cmc:
        for item in row:
            if not isinstance(item, dict):
                continue
            label = item.get("label", "")
            params = item.get("params", {})
            if label.startswith("skill-") and params.get("modifiable", True):
                skill_slug = params.get("skill_slug")
                if skill_slug:
                    selected_skills.append(skill_slug)

    return selected_skills


def _write_openclaw_config(
        state_dir: str,
        phc: Dict[str, Any],
        pa: Dict[str, Any],
        policy: Dict[str, Any],
        env_path: str | None = None,
        cmc: List[List[Dict[str, Any]]] | None = None,
        hid: str | None = None,
) -> str:
    """
    写 OpenClaw 官方配置文件。
    注意：会自动添加 HTTP API 端点配置，以便两个 Agent 互相通信。
    """

    token = secrets.token_urlsafe(32)

    config = {
        "gateway": {
            "mode": "local",
            "auth": {
                "mode": "token",
                "token": token,
            },
            # ========== 关键修改：添加 HTTP API 端点配置 ==========
            "http": {
                "endpoints": {
                    "chatCompletions": {
                        "enabled": True
                    }
                }
            }
            # ====================================================
        },
        "plugins": {
            "allow": [
                "browser",
                "canvas",
                "device-pair",
                "file-transfer",
                "memory-core",
                "phone-control",
                "talk-voice",
            ]
        },
    }

    if cmc:
        _configure_hooks_from_cmc(cmc, config)

    if env_path and os.path.exists(env_path):
        env_vars = {}
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    env_vars[key.strip()] = value.strip()

        llm_public_config = extract_llm_public_config(cmc or [])

        openai_base_url = str(
            llm_public_config.get("base_url")
            or env_vars.get("OPENAI_BASE_URL", "")
        ).strip()

        openclaw_model = str(
            llm_public_config.get("model")
            or env_vars.get("OPENCLAW_MODEL", "")
        ).strip()

        if openclaw_model:
            config.setdefault("agents", {})
            config["agents"].setdefault("defaults", {})
            config["agents"]["defaults"]["model"] = _normalize_openclaw_model(openclaw_model)

        if openai_base_url:
            config["models"] = {
                "mode": "merge",
                "providers": {
                    "openai": {
                        "baseUrl": openai_base_url
                    }
                }
            }

    path = os.path.join(state_dir, "openclaw.json")
    return _write_json_file(path, config)


def _append_text(path: str, content: str) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(content)


def _append_identity_context_to_templates(
        state_dir: str,
        phc: Dict[str, Any],
        pa: Dict[str, Any],
        cmc: List[List[Dict[str, Any]]],
        policy: Dict[str, Any],
) -> None:
    did = (
            phc.get("DID")
            or ((phc.get("ASO") or {}).get("TPM") or {}).get("CDID")
    )
    phc_id = phc.get("id")
    pa_cmi = ((pa.get("APM") or {}).get("CMI"))
    ap_id = ((pa.get("APA") or {}).get("APid"))

    common = f"""

---

## PHC/PA Identity Binding

This OpenClaw workspace is bound to a verified Personal Agent identity.

- Agent Type: OpenClaw PA
- Binding Mode: PHC-PA-OpenClaw
- PHC ID: {phc_id}
- DID: {did}
- AP ID: {ap_id}
- PA CMI: {pa_cmi}
- Binding File: `../openclaw_binding.json`
- Config File: `openclaw.json`

This agent is not a generic assistant. It is a personal OpenClaw instance generated through the PHC/PA identity construction process.

Privacy rules:

1. Do not reveal PII or BI.
2. Do not reveal RF, CRF, CID_enc, r_bind, r_bind2, or private proof internals.
3. Do not expose private memory in public or group channels.
4. Ask before external actions.
5. Ask before destructive file operations.
"""

    agents_path = os.path.join(state_dir, "AGENTS.md")
    if os.path.exists(agents_path):
        _append_text(agents_path, common)

    soul_path = os.path.join(state_dir, "SOUL.md")
    if os.path.exists(soul_path):
        _append_text(soul_path, f"""

    ---

    ## Identity-Aware Soul Extension

    You are a personal OpenClaw agent bound to one human through a PHC/PA credential chain.

    Your continuity comes from local memory files and OpenClaw state.
    Your authority comes from:

    - `../openclaw_binding.json`
    - `openclaw.json`
    - the PA CMI and CMC capability configuration

    Do not claim to represent the human beyond the configured PA permissions.
    """)

    user_path = os.path.join(state_dir, "USER.md")
    if os.path.exists(user_path):
        _append_text(user_path, f"""

    ---

    ## Bound User Identity Context

    - PHC ID: {phc_id}
    - DID: {did}
    - Agent Type: OpenClaw PA

    Sensitive PII/BI is not stored here.
    The identity proof is kept in `../openclaw_binding.json`.
    """)

    tools_path = os.path.join(state_dir, "TOOLS.md")
    if os.path.exists(tools_path):
        _append_text(tools_path, f"""

---

## Capability Policy Generated from PA CMC

```json
{json.dumps(policy, ensure_ascii=False, indent=2)}
Operational rules:

Use only enabled capabilities.
Ask before sending messages externally.
Ask before public posting.
Ask before shell execution if enabled.
Never leak identity proof details in public channels.
""")
    identity_path = os.path.join(state_dir, "IDENTITY.md")
    if os.path.exists(identity_path):
        _append_text(identity_path, f"""
---
PHC/PA Identity Overlay
PHC ID: {phc_id}
DID: {did}
PA CMI: {pa_cmi}
AP ID: {ap_id}
This file describes identity context for behavior alignment only.
The cryptographic binding record is stored in ../openclaw_binding.json.
""")


def build_openclaw_agent_files(
        root: str,
        phc: Dict[str, Any],
        pa: Dict[str, Any],
        cmc: List[List[Dict[str, Any]]],
        hid: str,
        package_cmi: str | None = None,
        hooks_config: Optional[Dict[str, bool]] = None,
        skills_config: Optional[List[str]] = None,
        llm_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    create_agent 阶段调用：
    1. 生成 openclaw_package
    2. 生成 openclaw_binding.json
    3. 生成 state/openclaw.json
    4. 复制 OpenClaw persona 模板到 state/
    5. 生成 deploy_openclaw_personal.bat
    6. 生成 launch_openclaw_personal.bat
    """
    # 注意：build_openclaw_package 现在返回的是字典，不是字符串
    package_info = build_openclaw_package(
        root=root,
        phc=phc,
        cmc=cmc,
        hid=hid,
        pa=pa,
        package_cmi=package_cmi,
        hooks_config=hooks_config,
        skills_config=skills_config,
        llm_config=llm_config,          # 关键：传递模型配置
    )

    # 生成部署和启动脚本
    deploy_script = _write_deploy_script(root)
    launcher = _write_launch_script(root)

    # 将脚本路径添加到返回字典中
    package_info["deploy_script"] = deploy_script
    package_info["launcher"] = launcher

    # 注意：package_info 中已经包含了 package_dir, state_dir, config_path 等所有字段
    # 因此直接返回即可
    return package_info
def _configure_hooks_in_package(package_dir: str, hooks_config: Dict[str, bool]) -> None:
    """
    在生成的包中配置 Hooks
    """
    config_path = os.path.join(package_dir, "state", "openclaw.json")

    if not os.path.exists(config_path):
        print(f"[WARN] Config file not found: {config_path}")
        return

    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)

        # 确保 hooks 结构存在
        if "hooks" not in config:
            config["hooks"] = {}
        if "internal" not in config["hooks"]:
            config["hooks"]["internal"] = {}
        if "entries" not in config["hooks"]["internal"]:
            config["hooks"]["internal"]["entries"] = {}

        # Hook 名称映射
        hook_mapping = {
            "session_memory": "session-memory",
            "bootstrap_extra_files": "bootstrap-extra-files",
            "command_logger": "command-logger",
            "boot_md": "boot-md"
        }

        for config_key, hook_name in hook_mapping.items():
            if config_key in hooks_config:
                if hook_name not in config["hooks"]["internal"]["entries"]:
                    config["hooks"]["internal"]["entries"][hook_name] = {}
                config["hooks"]["internal"]["entries"][hook_name]["enabled"] = hooks_config[config_key]

        # 写回配置文件
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)

        # 更新 manifest
        manifest_path = os.path.join(package_dir, "manifest.json")
        if os.path.exists(manifest_path):
            with open(manifest_path, 'r', encoding='utf-8') as f:
                manifest = json.load(f)
            manifest["hooks_configured"] = hooks_config
            with open(manifest_path, 'w', encoding='utf-8') as f:
                json.dump(manifest, f, indent=2, ensure_ascii=False)

        print(f"[OK] Hooks configured: {hooks_config}")

    except Exception as e:
        print(f"[ERROR] Failed to configure hooks: {e}")
def _resolve_clawhub_command() -> Optional[List[str]]:
    """查找 clawhub 命令"""
    import shutil

    candidates = [
        shutil.which("clawhub.cmd"),
        shutil.which("clawhub"),
        os.path.expanduser("~/AppData/Roaming/npm/clawhub.cmd"),
        os.path.expanduser("~/AppData/Roaming/npm/clawhub"),
        r"C:\npm-global\clawhub.cmd",
    ]

    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            return [candidate]

    return None
def _install_single_skill(instance_dir: Path, skill_slug: str, clawhub_cmd: List[str]) -> Dict[str, Any]:
    """安装单个 skill"""
    import subprocess

    env = os.environ.copy()
    env["CLAWHUB_WORKDIR"] = str(instance_dir)

    run_cmd = clawhub_cmd + ["install", skill_slug, "--force", "--workdir", str(instance_dir)]
    # Windows 下 .cmd/.bat 需经 cmd.exe 解释执行，否则 shell=False 会抛 WinError 193
    if os.name == "nt" and run_cmd and str(run_cmd[0] or "").lower().endswith((".cmd", ".bat")):
        run_cmd = ["cmd.exe", "/c"] + run_cmd

    try:
        proc = subprocess.run(
            run_cmd,
            capture_output=True,
            text=True,
            timeout=180,
            cwd=str(instance_dir),
            env=env
        )

        if proc.returncode == 0:
            return {"success": True, "skill": skill_slug, "output": proc.stdout}
        else:
            return {"success": False, "skill": skill_slug, "error": proc.stderr}

    except Exception as e:
        return {"success": False, "skill": skill_slug, "error": str(e)}
def _install_skills_in_package(package_dir: str, skills_config: List[str]) -> None:
    """
    在生成的包中安装 Skills（使用 ClawHub）
    """
    if not skills_config:
        return

    clawhub_cmd = _resolve_clawhub_command()
    if not clawhub_cmd:
        print("[WARN] ClawHub not found, skills installation skipped")
        return

    instance_dir = Path(package_dir)
    skills_dir = instance_dir / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)

    installed = []
    failed = []

    for skill_slug in skills_config:
        print(f"[INFO] Installing skill: {skill_slug}")
        result = _install_single_skill(instance_dir, skill_slug, clawhub_cmd)
        if result.get("success"):
            installed.append(skill_slug)
        else:
            failed.append({"slug": skill_slug, "error": result.get("error", "unknown")})

    # 更新 manifest
    manifest_path = os.path.join(package_dir, "manifest.json")
    if os.path.exists(manifest_path):
        with open(manifest_path, 'r', encoding='utf-8') as f:
            manifest = json.load(f)
        manifest["skills_installed"] = {
            "success": installed,
            "failed": failed
        }
        with open(manifest_path, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)

    print(f"[OK] Skills installed: {len(installed)}/{len(skills_config)}")
def extract_llm_public_config(cmc: List[List[Dict[str, Any]]]) -> Dict[str, Any]:
    """
    从 CMC 中提取可绑定的模型公开配置。
    不包含 API Key。
    """
    for row in cmc or []:
        for item in row or []:
            if not isinstance(item, dict):
                continue

            label = str(item.get("label") or "").strip()
            params = item.get("params") or {}

            if label == "llm-model":
                provider = str(params.get("provider") or "openai").strip()
                model = str(params.get("model") or "openai/gpt-4o").strip()
                base_url = str(params.get("base_url") or "").strip()
                compatibility = str(params.get("compatibility") or "openai-compatible").strip()
                
                provider_cfg = get_provider_config(provider)
                prefix = str(provider_cfg.get("model_prefix") or "openai").strip()

                return {
                    "provider": provider,
                    "model": _normalize_openclaw_model(model, provider_prefix=prefix),
                    "base_url": base_url,
                    "compatibility": compatibility,
                }

    return {
        "provider": "openai",
        "model": "openai/gpt-4o",
        "base_url": "",
        "compatibility": "openai-native",
    }
def compute_openclaw_bound_cmi(
    hid: str,
    code_cmi: int | str | None,
    cmc: List[List[Dict[str, Any]]],
    llm_public_config: Dict[str, Any],
) -> int:
    from crypto_lib import hash_to_int, DL_Q

    payload = canonical_json({
        "kind": "openclaw-pa-cmi-v1",
        "hid": str(hid),
        "code_cmi": str(code_cmi or ""),
        "cmc": cmc,
        "llm_public_config": llm_public_config,
    }).encode()

    return hash_to_int(payload) % DL_Q