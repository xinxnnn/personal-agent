from __future__ import annotations

from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Dict, List, Optional
import subprocess
import json
import uuid
import shutil
import os
import re
from pathlib import Path
from datetime import datetime

try:
    from crypto_lib import sha256_hex, canonical_json, schnorr_sign
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False

router = APIRouter(prefix="/skills", tags=["Skills Configuration"])

sessions: Dict[str, dict] = {}


class SkillAuthChain:
    """技能授权哈希链 - 追踪所有技能安装/卸载操作"""

    def __init__(self, instance_dir: Path):
        self.instance_dir = instance_dir
        self.chain_path = instance_dir / "state" / "skill_auth_chain.json"
        self._load_chain()

    def _load_chain(self):
        if self.chain_path.exists():
            try:
                with open(self.chain_path, 'r', encoding='utf-8') as f:
                    self.data = json.load(f)
            except Exception:
                self.data = self._init_chain()
        else:
            self.data = self._init_chain()

    def _init_chain(self) -> dict:
        return {
            "head": "",
            "entries": [],
            "created_at": datetime.utcnow().isoformat() + "Z"
        }

    def _save_chain(self):
        self.chain_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.chain_path, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)

    def add_entry(self, skill_slug: str, action: str, user_pub_key: int = None) -> dict:
        """添加技能授权记录"""
        if not CRYPTO_AVAILABLE:
            return {"success": False, "error": "crypto_lib not available"}

        entry = {
            "skill_slug": skill_slug,
            "action": action,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "prev_head": self.data["head"]
        }

        entry_data = canonical_json(entry)
        entry_hash = sha256_hex(entry_data)

        if self.data["head"]:
            new_head = sha256_hex(self.data["head"] + entry_hash)
        else:
            new_head = sha256_hex(str(self.instance_dir))

        if user_pub_key:
            try:
                signature = schnorr_sign(user_pub_key, entry_hash.encode())
                entry["signature"] = {
                    "r": str(signature["r"]),
                    "e": str(signature["e"]),
                    "s": str(signature["s"])
                }
            except Exception:
                pass

        self.data["entries"].append({
            "entry": entry,
            "hash": entry_hash
        })
        self.data["head"] = new_head

        self._save_chain()

        return {
            "success": True,
            "skill_slug": skill_slug,
            "action": action,
            "entry_hash": entry_hash,
            "new_head": new_head
        }

    def verify_chain(self) -> bool:
        """验证哈希链完整性"""
        if not self.data["entries"]:
            return True

        expected_head = self.data["entries"][0]["prev_head"] or sha256_hex(str(self.instance_dir))

        for item in self.data["entries"]:
            entry = item["entry"]
            expected_entry_hash = sha256_hex(canonical_json(entry).encode())

            if item["hash"] != expected_entry_hash:
                return False

            expected_head = sha256_hex(expected_head + item["hash"])

        return expected_head == self.data["head"]

    def get_installed_skills(self) -> List[str]:
        """获取当前安装的技能列表"""
        installed = set()

        for item in self.data["entries"]:
            entry = item["entry"]
            if entry["action"] == "install":
                installed.add(entry["skill_slug"])
            elif entry["action"] == "uninstall":
                installed.discard(entry["skill_slug"])

        return list(installed)

    def get_chain_info(self) -> dict:
        """获取链信息"""
        return {
            "head": self.data["head"],
            "entry_count": len(self.data["entries"]),
            "created_at": self.data.get("created_at"),
            "verified": self.verify_chain()
        }


CLAWHUB_INSTALL_COMMAND = [
    "install",
    "-g",
    "clawhub",
    "--registry=https://registry.npmmirror.com",
]
CLAWHUB_DOWNLOAD_URL = "https://www.npmjs.com/package/clawhub"


class SkillsInstallRequest(BaseModel):
    user_name: str
    selected_skills: List[str]
    openclaw_path: Optional[str] = None


class SkillsDebugRequest(BaseModel):
    user_name: str
    skill_slug: str
    openclaw_path: Optional[str] = None


class SkillsSingleActionRequest(BaseModel):
    user_name: str
    skill_slug: str
    openclaw_path: Optional[str] = None


RECOMMENDED_SKILLS = [
    {"slug": "weather", "name": "天气查询", "description": "查询实时天气和天气预报（无需API密钥）", "recommended": True, "emoji": "🌤️"},
    {"slug": "github", "name": "GitHub集成", "description": "Issues管理、PR查看、CI状态查询", "recommended": True, "emoji": "🐙"},
    {"slug": "desearch-web-search", "name": "联网搜索", "description": "Desearch 网络搜索", "recommended": True, "emoji": "🔍"},
]


def _run_capture(cmd: List[str], timeout: int = 30, cwd: str | None = None, env: dict | None = None) -> tuple[bool, str]:
    run_cmd = list(cmd)
    # Windows 下 .cmd/.bat 不能直接被 CreateProcess 执行（shell=False 会抛
    # OSError: [WinError 193] %1 is not a valid Win32 application），必须交给
    # cmd.exe 解释执行。clawhub / npm 在 Windows 上都是 .cmd 包装脚本。
    if os.name == "nt" and run_cmd:
        exe = str(run_cmd[0] or "")
        if exe.lower().endswith((".cmd", ".bat")):
            run_cmd = ["cmd.exe", "/c"] + run_cmd
    try:
        proc = subprocess.run(
            run_cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=timeout,
            cwd=cwd,
            env=env,
            shell=False,
        )
        out = (proc.stdout or proc.stderr or "").strip()
        return proc.returncode == 0, out
    except Exception as exc:
        return False, str(exc)


def _resolve_clawhub_command() -> List[str] | None:
    local_appdata = os.environ.get("LOCALAPPDATA", "")
    appdata = os.environ.get("APPDATA", "")
    user_profile = os.environ.get("USERPROFILE", "")
    node_command = _resolve_node_command()
    node_exe = node_command[0] if node_command else None
    js_entry_candidates = [
        r"C:\npm-global\node_modules\clawhub\bin\clawhub.js",
        os.path.join(user_profile, "AppData", "Roaming", "npm", "node_modules", "clawhub", "bin", "clawhub.js") if user_profile else "",
        os.path.join(appdata, "npm", "node_modules", "clawhub", "bin", "clawhub.js") if appdata else "",
    ]
    if node_exe:
        for js_entry in js_entry_candidates:
            if js_entry and os.path.exists(js_entry):
                return [node_exe, js_entry]

    candidates = [
        shutil.which("clawhub.cmd"),
        shutil.which("clawhub"),
        os.path.join(user_profile, "AppData", "Roaming", "npm", "clawhub.cmd") if user_profile else "",
        os.path.join(user_profile, "AppData", "Roaming", "npm", "clawhub") if user_profile else "",
        os.path.join(appdata, "npm", "clawhub.cmd") if appdata else "",
        os.path.join(appdata, "npm", "clawhub") if appdata else "",
        r"C:\npm-global\clawhub.cmd",
        r"C:\npm-global\clawhub",
        os.path.join(local_appdata, "Programs", "nodejs", "clawhub.cmd") if local_appdata else "",
    ]
    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            # 优先用 node + clawhub.js 真实入口执行，避免 .cmd 包装脚本带来的
            # cmd.exe 转义 / 中文路径编码问题。
            if node_exe:
                js_entry = _clawhub_js_from_cmd(candidate)
                if js_entry:
                    return [node_exe, js_entry]
            return [candidate]
    return None


def _clawhub_js_from_cmd(cmd_path: str) -> str | None:
    """从 clawhub.cmd 的位置反推真实的 node 入口 clawhub.js。

    npm 全局安装时布局为：
      <npm-prefix>\\clawhub.cmd
      <npm-prefix>\\node_modules\\clawhub\\bin\\clawhub.js
    """
    try:
        parent = Path(cmd_path).parent
        js_entry = parent / "node_modules" / "clawhub" / "bin" / "clawhub.js"
        if js_entry.exists():
            return str(js_entry)
    except Exception:
        pass
    return None


def _resolve_npm_command() -> List[str] | None:
    local_appdata = os.environ.get("LOCALAPPDATA", "")
    user_profile = os.environ.get("USERPROFILE", "")
    candidates = [
        shutil.which("npm.cmd"),
        shutil.which("npm"),
        os.path.join(user_profile, "AppData", "Roaming", "npm", "npm.cmd") if user_profile else "",
        r"C:\npm-global\npm.cmd",
        os.path.join(local_appdata, "Programs", "nodejs", "npm.cmd") if local_appdata else "",
    ]
    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            return [candidate]
    return None


def _resolve_node_command() -> List[str] | None:
    local_appdata = os.environ.get("LOCALAPPDATA", "")
    user_profile = os.environ.get("USERPROFILE", "")
    candidates = [
        shutil.which("node.exe"),
        shutil.which("node"),
        os.path.join(local_appdata, "Programs", "nodejs", "node.exe") if local_appdata else "",
        os.path.join(user_profile, "AppData", "Roaming", "nvm", "node.exe") if user_profile else "",
        r"C:\nvm4w\nodejs\node.exe",
        r"C:\Program Files\nodejs\node.exe",
    ]
    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            return [candidate]
    return None


def _find_installed_skill_dir(instance_dir: Path, skill_slug: str) -> Path | None:
    candidates = [
        instance_dir / "skills" / skill_slug,
        Path.home() / ".openclaw" / "workspace" / "skills" / skill_slug,
        Path.home() / ".clawhub" / "skills" / skill_slug,
        Path.home() / ".openclaw" / "skills" / skill_slug,
    ]

    for path in candidates:
        if path.exists():
            return path

    search_roots = [
        Path.home() / ".openclaw",
        Path.home() / ".clawhub",
        instance_dir,
    ]
    for root in search_roots:
        if not root.exists():
            continue
        try:
            for match in root.rglob(skill_slug):
                if match.is_dir() and (match / "SKILL.md").exists():
                    return match
        except Exception:
            continue
    return None


def _with_command_path(env: dict, command: List[str] | None) -> dict:
    new_env = dict(env)
    extra_dirs: list[str] = []

    if command and command[0]:
        extra_dirs.append(str(Path(command[0]).resolve().parent))

    node_command = _resolve_node_command()
    if node_command and node_command[0]:
        extra_dirs.append(str(Path(node_command[0]).resolve().parent))

    current_path = new_env.get("PATH", "")
    path_parts = current_path.split(os.pathsep) if current_path else []
    for extra in extra_dirs:
        if extra and extra not in path_parts:
            path_parts.insert(0, extra)
    new_env["PATH"] = os.pathsep.join(path_parts)
    return new_env


def detect_clawhub() -> dict:
    command = _resolve_clawhub_command()
    path = command[0] if command else None
    installed = bool(path)
    version = None
    error = None
    if installed:
        for version_flag in ["--cli-version", "--version", "-v", "version"]:
            ok, out = _run_capture([path, version_flag], timeout=10)
            if ok and out:
                version = out.splitlines()[0].strip()
                break
            elif out and ("error" in out.lower() or "unknown" in out.lower()):
                continue
        if not version:
            ok, out = _run_capture([path, "--help"], timeout=10)
            if ok and out:
                version = "installed"
            elif out:
                error = out
    return {
        "success": True,
        "installed": installed,
        "path": path,
        "version": version,
        "error": error,
        "install_command": "npm install -g clawhub --registry=https://registry.npmmirror.com",
        "download_url": CLAWHUB_DOWNLOAD_URL,
        "ready": bool(installed and version and not error),
    }


def install_clawhub_cli() -> dict:
    npm_command = _resolve_npm_command()
    if not npm_command:
        return {
            "success": False,
            "message": "未找到 npm 命令，请先安装并配置 Node.js/npm。",
            "output": "npm not found",
        }

    env = _with_command_path(os.environ.copy(), npm_command)
    ok, out = _run_capture(npm_command + CLAWHUB_INSTALL_COMMAND, timeout=240, env=env)
    return {
        "success": ok,
        "message": "ClawHub CLI 安装成功！" if ok else f"安装失败: {out}",
        "output": out,
    }


def get_openclaw_instance_path(user_name: str) -> Path | None:
    agents_base = Path("local_store/agents")
    if not agents_base.exists():
        return None
    requested = str(user_name or "").strip()
    requested_variants = {
        requested,
        requested.replace(":", "_"),
        requested.replace("/", "_").replace("\\", "_"),
    }
    for agent_dir in agents_base.iterdir():
        if not agent_dir.is_dir():
            continue
        openclaw_package = agent_dir / "openclaw_package"
        if not openclaw_package.exists():
            continue
        if agent_dir.name in requested_variants:
            return openclaw_package
        manifest_path = agent_dir / "agent_manifest.json"
        if not manifest_path.exists():
            continue
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
            manifest_ids = {
                str(manifest.get(key) or "")
                for key in ("id", "phc_id", "user_name", "name", "idnum")
            }
            normalized_manifest_ids = {
                value.replace(":", "_").replace("/", "_").replace("\\", "_")
                for value in manifest_ids
            }
            if manifest_ids.intersection(requested_variants) or normalized_manifest_ids.intersection(requested_variants):
                return openclaw_package
        except Exception:
            pass
    return None


def install_skill_via_clawhub(instance_dir: Path, skill_slug: str, user_pub_key: int = None) -> dict:
    command = _resolve_clawhub_command()
    if not command:
        return {"success": False, "skill": skill_slug, "error": "未找到 clawhub 命令"}

    env = os.environ.copy()
    env = _with_command_path(env, command)
    env["CLAWHUB_WORKDIR"] = str(instance_dir)
    target_skills_dir = instance_dir / "skills"
    target_skills_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_skills_dir / skill_slug

    install_args = ["install", skill_slug, "--force", "--workdir", str(instance_dir)]
    ok, out = _run_capture(
        command + install_args,
        timeout=180,
        cwd=str(instance_dir),
        env=env
    )
    if not ok and "AMBIGUOUS_SKILL_SLUG" in out:
        refs = re.findall(r'"ref"\s*:\s*"([^"]+)"', out)
        if refs:
            ok, out = _run_capture(
                command + ["install", refs[0], "--force", "--workdir", str(instance_dir)],
                timeout=180,
                cwd=str(instance_dir),
                env=env,
            )
    if not ok:
        return {"success": False, "skill": skill_slug, "error": out or "安装失败"}

    if (target_path / "SKILL.md").exists():
        chain_result = SkillAuthChain(instance_dir).add_entry(skill_slug, "install", user_pub_key)
        return {"success": True, "skill": skill_slug, "path": str(target_path), "output": out, "chain_head": chain_result.get("new_head")}

    installed_skill_dir = _find_installed_skill_dir(instance_dir, skill_slug)
    if installed_skill_dir is None:
        return {"success": False, "skill": skill_slug, "error": "找不到已安装的技能目录"}

    if installed_skill_dir.resolve() != target_path.resolve():
        if target_path.exists():
            shutil.rmtree(target_path, ignore_errors=True)
        shutil.copytree(installed_skill_dir, target_path)

    skill_md = target_path / "SKILL.md"
    if not skill_md.exists():
        return {"success": False, "skill": skill_slug, "error": "复制后找不到 SKILL.md"}

    chain_result = SkillAuthChain(instance_dir).add_entry(skill_slug, "install", user_pub_key)
    return {"success": True, "skill": skill_slug, "path": str(target_path), "output": out, "chain_head": chain_result.get("new_head")}


def update_skill_via_clawhub(instance_dir: Path, skill_slug: str) -> dict:
    command = _resolve_clawhub_command()
    if not command:
        return {"success": False, "skill": skill_slug, "error": "未找到 clawhub 命令"}
    env = _with_command_path(os.environ.copy(), command)
    env["CLAWHUB_WORKDIR"] = str(instance_dir)
    ok, out = _run_capture(
        command + ["update", skill_slug, "--workdir", str(instance_dir)],
        timeout=180,
        cwd=str(instance_dir),
        env=env,
    )
    return {"success": ok, "skill": skill_slug, "output": out, "error": None if ok else (out or "更新失败")}


def uninstall_skill_via_clawhub(instance_dir: Path, skill_slug: str, user_pub_key: int = None) -> dict:
    command = _resolve_clawhub_command()
    if not command:
        return {"success": False, "skill": skill_slug, "error": "未找到 clawhub 命令"}
    env = _with_command_path(os.environ.copy(), command)
    env["CLAWHUB_WORKDIR"] = str(instance_dir)
    ok, out = _run_capture(
        command + ["uninstall", skill_slug, "--workdir", str(instance_dir)],
        timeout=180,
        cwd=str(instance_dir),
        env=env,
    )
    target_path = instance_dir / "skills" / skill_slug
    if target_path.exists():
        shutil.rmtree(target_path, ignore_errors=True)

    chain_result = SkillAuthChain(instance_dir).add_entry(skill_slug, "uninstall", user_pub_key)
    return {"success": ok, "skill": skill_slug, "output": out, "error": None if ok else (out or "卸载失败"), "chain_head": chain_result.get("new_head")}


@router.get("/recommended")
async def get_recommended_skills():
    return {"success": True, "skills": RECOMMENDED_SKILLS}


@router.get("/check-clawhub")
async def check_clawhub():
    return detect_clawhub()


@router.post("/install-clawhub")
async def install_clawhub():
    return install_clawhub_cli()


@router.get("/search")
async def search_skills(keyword: str = ""):
    clawhub_status = detect_clawhub()
    if not clawhub_status["ready"]:
        return {"success": False, "error": "ClawHub CLI 未安装", "clawhub": clawhub_status}

    command = _resolve_clawhub_command()
    if not command:
        return {"success": False, "error": "未找到 clawhub 命令", "clawhub": clawhub_status}
    cmd = command + (["search", keyword] if keyword else ["list", "--available"])
    ok, out = _run_capture(cmd, timeout=30)
    return {"success": ok, "output": out, "error": None if ok else out}


@router.get("/installed/{user_name}")
async def get_installed_skills(user_name: str):
    instance_dir = get_openclaw_instance_path(user_name)
    if not instance_dir:
        return {"success": False, "error": f"未找到 OpenClaw 实例: {user_name}"}
    skills_dir = instance_dir / "skills"
    installed = []
    if skills_dir.exists():
        for d in skills_dir.iterdir():
            if d.is_dir():
                installed.append({
                    "slug": d.name,
                    "path": str(d),
                    "has_skill_md": (d / "SKILL.md").exists(),
                })
    return {
        "success": True,
        "instance_dir": str(instance_dir),
        "installed_skills": installed,
        "installed_skill_slugs": [item["slug"] for item in installed],
    }


@router.get("/chain-info/{user_name}")
async def get_skill_chain_info(user_name: str):
    instance_dir = get_openclaw_instance_path(user_name)
    if not instance_dir:
        return {"success": False, "error": f"未找到 OpenClaw 实例: {user_name}"}
    chain = SkillAuthChain(instance_dir)
    return {
        "success": True,
        "instance_dir": str(instance_dir),
        "chain_info": chain.get_chain_info(),
        "installed_skills_from_chain": chain.get_installed_skills(),
    }


@router.post("/update-one")
async def update_one_skill(request: SkillsSingleActionRequest):
    instance_dir = Path(request.openclaw_path) if request.openclaw_path else get_openclaw_instance_path(request.user_name)
    if not instance_dir:
        raise HTTPException(status_code=404, detail=f"未找到 OpenClaw 实例: {request.user_name}")
    result = update_skill_via_clawhub(instance_dir, request.skill_slug)
    return {"success": bool(result.get("success")), "instance_dir": str(instance_dir), "result": result}


@router.post("/uninstall-one")
async def uninstall_one_skill(request: SkillsSingleActionRequest):
    instance_dir = Path(request.openclaw_path) if request.openclaw_path else get_openclaw_instance_path(request.user_name)
    if not instance_dir:
        raise HTTPException(status_code=404, detail=f"未找到 OpenClaw 实例: {request.user_name}")
    result = uninstall_skill_via_clawhub(instance_dir, request.skill_slug)
    return {"success": bool(result.get("success")), "instance_dir": str(instance_dir), "result": result}


@router.post("/update-installed")
async def update_installed_skills(request: SkillsInstallRequest):
    clawhub_status = detect_clawhub()
    if not clawhub_status["ready"]:
        raise HTTPException(status_code=400, detail={"message": "ClawHub CLI 未安装或不可用", "clawhub": clawhub_status})

    instance_dir = Path(request.openclaw_path) if request.openclaw_path else get_openclaw_instance_path(request.user_name)
    if not instance_dir:
        raise HTTPException(status_code=404, detail=f"未找到 OpenClaw 实例: {request.user_name}")

    command = _resolve_clawhub_command()
    if not command:
        raise HTTPException(status_code=400, detail="未找到 clawhub 命令")

    skills_dir = instance_dir / "skills"
    installed = [d.name for d in skills_dir.iterdir() if d.is_dir()] if skills_dir.exists() else []
    if not installed:
        return {
            "success": True,
            "instance_dir": str(instance_dir),
            "updated": [],
            "failed": [],
            "message": "当前实例没有已安装的 skills，无需更新。",
        }

    updated = []
    failed = []
    details = []
    for skill_slug in installed:
        ok, out = _run_capture(
            command + ["update", skill_slug, "--workdir", str(instance_dir)],
            timeout=180,
            cwd=str(instance_dir),
            env=os.environ.copy(),
        )
        detail = {"skill": skill_slug, "success": ok, "output": out}
        details.append(detail)
        if ok:
            updated.append(skill_slug)
        else:
            failed.append({"slug": skill_slug, "error": out or "更新失败"})

    return {
        "success": len(failed) == 0,
        "instance_dir": str(instance_dir),
        "updated": updated,
        "failed": failed,
        "details": details,
        "message": f"更新完成：成功 {len(updated)} 个，失败 {len(failed)} 个。",
    }


@router.post("/install")
async def install_skills(request: SkillsInstallRequest, background_tasks: BackgroundTasks):
    clawhub_status = detect_clawhub()
    if not clawhub_status["ready"]:
        raise HTTPException(status_code=400, detail={"message": "ClawHub CLI 未安装", "clawhub": clawhub_status})

    session_id = str(uuid.uuid4())[:8]
    instance_dir = Path(request.openclaw_path) if request.openclaw_path else get_openclaw_instance_path(request.user_name)
    if not instance_dir:
        raise HTTPException(status_code=404, detail=f"未找到 OpenClaw 实例: {request.user_name}")

    (instance_dir / "skills").mkdir(parents=True, exist_ok=True)
    sessions[session_id] = {
        "user_name": request.user_name,
        "instance_dir": str(instance_dir),
        "status": "installing",
        "selected_skills": request.selected_skills,
        "installed": [],
        "failed": [],
        "details": [],
    }
    background_tasks.add_task(_install_skills_task, session_id, instance_dir, request.selected_skills)
    return {"success": True, "session_id": session_id, "message": f"正在安装 {len(request.selected_skills)} 个技能"}


@router.post("/debug-install-once")
async def debug_install_once(request: SkillsDebugRequest):
    clawhub_status = detect_clawhub()
    if not clawhub_status["ready"]:
        return {"success": False, "message": "ClawHub CLI 不可用", "clawhub": clawhub_status}

    instance_dir = Path(request.openclaw_path) if request.openclaw_path else get_openclaw_instance_path(request.user_name)
    if not instance_dir:
        return {"success": False, "message": f"未找到 OpenClaw 实例: {request.user_name}"}

    result = install_skill_via_clawhub(instance_dir, request.skill_slug)
    return {
        "success": bool(result.get("success")),
        "instance_dir": str(instance_dir),
        "skill_slug": request.skill_slug,
        "result": result,
    }


@router.get("/status/{session_id}")
async def get_install_status(session_id: str):
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"success": True, **sessions[session_id]}


async def _install_skills_task(session_id: str, instance_dir: Path, skills: List[str]):
    sessions[session_id]["status"] = "installing"
    sessions[session_id]["message"] = "正在安装技能..."
    installed = []
    failed = []
    details = []
    for i, skill_slug in enumerate(skills):
        sessions[session_id]["message"] = f"正在安装: {skill_slug} ({i + 1}/{len(skills)})"
        result = install_skill_via_clawhub(instance_dir, skill_slug)
        details.append(result)
        if result.get("success"):
            installed.append(skill_slug)
        else:
            failed.append({"slug": skill_slug, "error": result.get("error", "未知错误")})
    sessions[session_id]["installed"] = installed
    sessions[session_id]["failed"] = failed
    sessions[session_id]["details"] = details
    sessions[session_id]["status"] = "completed"
    sessions[session_id]["message"] = f"完成！成功安装 {len(installed)}/{len(skills)} 个技能"
