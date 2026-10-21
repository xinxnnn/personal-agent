from __future__ import annotations

from typing import Any, Dict, List
import shutil
import subprocess


NODE_WINGET_ID = "OpenJS.NodeJS.LTS"
GIT_WINGET_ID = "Git.Git"
NODE_DOWNLOAD_URL = "https://nodejs.org/en/download"
GIT_DOWNLOAD_URL = "https://git-scm.com/download/win"


def _run_capture(cmd: List[str]) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=8,
            shell=False,
        )
        out = (proc.stdout or proc.stderr or "").strip()
        return proc.returncode == 0, out
    except Exception as exc:
        return False, str(exc)


def _command_version(command: str, version_args: List[str]) -> Dict[str, Any]:
    path = shutil.which(command)
    installed = bool(path)
    version = None
    error = None

    if installed:
        ok, out = _run_capture([command, *version_args])
        if ok and out:
            version = out.splitlines()[0].strip()
        elif out:
            error = out

    return {
        "installed": installed,
        "path": path,
        "version": version,
        "error": error,
    }


def detect_windows_dependencies() -> Dict[str, Any]:
    node = _command_version("node", ["--version"])
    git = _command_version("git", ["--version"])
    winget_path = shutil.which("winget")

    return {
        "success": True,
        "platform": "windows",
        "winget": {
            "installed": bool(winget_path),
            "path": winget_path,
        },
        "node": {
            **node,
            "winget_id": NODE_WINGET_ID,
            "download_url": NODE_DOWNLOAD_URL,
        },
        "git": {
            **git,
            "winget_id": GIT_WINGET_ID,
            "download_url": GIT_DOWNLOAD_URL,
        },
        "ready_for_openclaw": bool(node["installed"] and git["installed"]),
    }


def _build_install_ps(packages: List[str]) -> str:
    joined = "; ".join(
        [
            f'winget install --id "{pkg}" -e --accept-package-agreements --accept-source-agreements'
            for pkg in packages
        ]
    )
    return (
        "$Host.UI.RawUI.WindowTitle = 'OpenClaw Dependency Installer'; "
        "Write-Host 'Starting dependency installation...' -ForegroundColor Cyan; "
        f"{joined}; "
        "Write-Host ''; "
        "Write-Host 'Installation command finished. Please reopen the app or re-check dependencies.' -ForegroundColor Green; "
        "Read-Host 'Press Enter to close this window'"
    )


def launch_dependency_installer(target: str) -> Dict[str, Any]:
    target = (target or "").strip().lower()
    winget_path = shutil.which("winget")
    if not winget_path:
        return {
            "success": False,
            "error": "winget_not_found",
            "detail": "未检测到 winget，无法执行快捷安装。",
            "node_download_url": NODE_DOWNLOAD_URL,
            "git_download_url": GIT_DOWNLOAD_URL,
        }

    package_map = {
        "node": [NODE_WINGET_ID],
        "git": [GIT_WINGET_ID],
        "all": [NODE_WINGET_ID, GIT_WINGET_ID],
    }
    packages = package_map.get(target)
    if not packages:
        return {
            "success": False,
            "error": "invalid_target",
            "detail": "安装目标必须是 node、git 或 all。",
        }

    ps_command = _build_install_ps(packages)
    try:
        subprocess.Popen(
            [
                "powershell",
                "-NoExit",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                ps_command,
            ],
            creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
        )
        return {
            "success": True,
            "started": True,
            "target": target,
            "packages": packages,
            "message": "已打开安装窗口，请根据提示完成安装。",
        }
    except Exception as exc:
        return {
            "success": False,
            "error": "installer_launch_failed",
            "detail": str(exc),
            "target": target,
            "packages": packages,
        }
