from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import List, Optional, Dict
import json
import uuid
from pathlib import Path

router = APIRouter(prefix="/hooks", tags=["Hooks Configuration"])

# 存储会话状态
sessions: Dict[str, dict] = {}


# ==================== 数据模型 ====================

class HooksSelection(BaseModel):
    """用户选择的 Hooks 配置"""
    session_memory: bool = False
    bootstrap_extra_files: bool = False
    command_logger: bool = False
    boot_md: bool = False


class HooksConfigRequest(BaseModel):
    """Hooks 配置请求"""
    user_name: str
    selected_hooks: HooksSelection
    openclaw_path: Optional[str] = None


# ==================== 核心函数 ====================

def get_openclaw_instance_path(user_name: str) -> Path:
    """
    获取用户 OpenClaw 实例路径
    直接查找 local_store/agents/{phc_id}/openclaw_package/
    """
    agents_base = Path("local_store/agents")
    if agents_base.exists():
        for agent_dir in agents_base.iterdir():
            if agent_dir.is_dir():
                openclaw_package = agent_dir / "openclaw_package"
                if openclaw_package.exists():
                    # 如果传入的是 phc_id，直接匹配
                    if agent_dir.name == user_name:
                        return openclaw_package

                    # 尝试读取 manifest 匹配用户名
                    manifest_path = agent_dir / "agent_manifest.json"
                    if manifest_path.exists():
                        try:
                            with open(manifest_path, 'r', encoding='utf-8') as f:
                                manifest = json.load(f)
                                if manifest.get("user_name") == user_name or \
                                        manifest.get("name") == user_name or \
                                        manifest.get("idnum") == user_name:
                                    return openclaw_package
                        except:
                            pass
    return None


def configure_hooks_via_config_file(instance_dir: Path, hooks: HooksSelection) -> dict:
    """
    直接修改配置文件来配置 Hooks（无需 CLI）
    """
    results = {
        "enabled": [],
        "failed": []
    }

    # 配置文件路径
    config_path = instance_dir / "state" / "openclaw.json"

    if not config_path.exists():
        results["failed"].append({
            "name": "config",
            "error": f"配置文件不存在: {config_path}"
        })
        return results

    try:
        # 读取现有配置
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)

        # 确保 hooks 结构存在
        if "hooks" not in config:
            config["hooks"] = {}
        if "internal" not in config["hooks"]:
            config["hooks"]["internal"] = {}
        if "entries" not in config["hooks"]["internal"]:
            config["hooks"]["internal"]["entries"] = {}

        # 配置各个 Hook
        hook_mapping = {
            "session-memory": hooks.session_memory,
            "bootstrap-extra-files": hooks.bootstrap_extra_files,
            "command-logger": hooks.command_logger,
            "boot-md": hooks.boot_md
        }

        for hook_name, should_enable in hook_mapping.items():
            if hook_name not in config["hooks"]["internal"]["entries"]:
                config["hooks"]["internal"]["entries"][hook_name] = {}

            config["hooks"]["internal"]["entries"][hook_name]["enabled"] = should_enable

            if should_enable:
                results["enabled"].append(hook_name)

        # 写回配置文件
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)

    except Exception as e:
        results["failed"].append({"name": "config", "error": str(e)})

    return results


# ==================== API 接口 ====================

@router.get("/available")
async def get_available_hooks():
    """获取所有可用的 Hooks 列表"""
    return {
        "success": True,
        "hooks": [
            {
                "id": "session-memory",
                "name": "会话记忆备份",
                "description": "执行 /new 或 /reset 时，自动保存上一轮对话的最后15条消息到记忆文件",
                "category": "记忆",
                "recommended": True
            },
            {
                "id": "bootstrap-extra-files",
                "name": "额外引导文件注入",
                "description": "Agent 启动时自动注入额外的 AGENTS.md、TOOLS.md 等引导文件",
                "category": "引导",
                "recommended": False
            },
            {
                "id": "command-logger",
                "name": "命令审计日志",
                "description": "将所有斜杠命令记录到 ~/.openclaw/logs/commands.log，JSONL 格式",
                "category": "审计",
                "recommended": True
            },
            {
                "id": "boot-md",
                "name": "启动脚本执行",
                "description": "Gateway 启动时自动执行 BOOT.md 中的指令，适合初始化检查",
                "category": "自动化",
                "recommended": False
            }
        ]
    }


@router.get("/verify/{user_name}")
async def verify_hooks_config(user_name: str):
    """验证 Hooks 配置状态"""
    instance_dir = get_openclaw_instance_path(user_name)

    if not instance_dir:
        return {
            "success": True,
            "data": {
                "user_name": user_name,
                "verified": False,
                "enabled_hooks": [],
                "details": {"error": f"未找到 OpenClaw 实例: {user_name}"}
            }
        }

    result = {
        "user_name": user_name,
        "verified": False,
        "enabled_hooks": [],
        "details": {"instance_dir": str(instance_dir)}
    }

    # 检查配置文件
    config_path = instance_dir / "state" / "openclaw.json"
    if config_path.exists():
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)

            hooks_config = config.get("hooks", {}).get("internal", {}).get("entries", {})
            for hook_name, hook_cfg in hooks_config.items():
                if hook_cfg.get("enabled"):
                    result["enabled_hooks"].append(hook_name)

            result["verified"] = len(result["enabled_hooks"]) > 0
            result["details"]["config"] = hooks_config
        except Exception as e:
            result["details"]["config_error"] = str(e)
    else:
        result["details"]["error"] = f"配置文件不存在: {config_path}"

    return {"success": True, "data": result}


@router.post("/configure")
async def configure_hooks(request: HooksConfigRequest, background_tasks: BackgroundTasks):
    """配置 Hooks"""
    session_id = str(uuid.uuid4())[:8]

    # 获取 OpenClaw 实例路径
    if request.openclaw_path:
        instance_dir = Path(request.openclaw_path)
    else:
        instance_dir = get_openclaw_instance_path(request.user_name)

    if not instance_dir:
        raise HTTPException(status_code=404, detail=f"未找到 OpenClaw 实例: {request.user_name}")

    sessions[session_id] = {
        "user_name": request.user_name,
        "instance_dir": str(instance_dir),
        "status": "configuring",
        "selected_hooks": request.selected_hooks.dict()
    }

    # 后台执行配置
    background_tasks.add_task(
        _configure_hooks_task,
        session_id,
        instance_dir,
        request.selected_hooks
    )

    return {
        "success": True,
        "session_id": session_id,
        "message": "Hooks 配置任务已启动"
    }


@router.get("/status/{session_id}")
async def get_config_status(session_id: str):
    """获取配置进度"""
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="会话不存在")

    return {
        "success": True,
        **sessions[session_id]
    }


async def _configure_hooks_task(session_id: str, instance_dir: Path, hooks: HooksSelection):
    """后台配置任务"""
    sessions[session_id]["status"] = "configuring"
    sessions[session_id]["message"] = "正在配置 Hooks..."

    try:
        # 直接修改配置文件
        config_result = configure_hooks_via_config_file(instance_dir, hooks)

        sessions[session_id]["config_result"] = config_result

        if config_result["failed"]:
            sessions[session_id]["status"] = "failed"
            sessions[session_id]["message"] = f"配置失败: {config_result['failed']}"
        else:
            sessions[session_id]["status"] = "completed"
            sessions[session_id]["message"] = f"Hooks 配置完成！已启用: {', '.join(config_result['enabled'])}"

    except Exception as e:
        sessions[session_id]["status"] = "failed"
        sessions[session_id]["message"] = f"配置失败: {str(e)}"