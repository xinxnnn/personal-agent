#!/usr/bin/env python3
"""
CMI 篡改检测测试
"""
import sys
import os

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
from crypto_lib import dir_code_cmi_hid

# ====== 修改这些变量为你的实际值 ======
PHC_ID = "phc_8e9679970014fb1b"
HID = "adf229fd91ab4f92bb11ffa0d91d4d87bf5acb12cd7403b840320f31e2a45cd9"
# =====================================

def main():
    print("=" * 60)
    print("CMI 篡改检测测试")
    print("=" * 60)

    manifest_path = f"local_store/agents/{PHC_ID}/openclaw_package/manifest.json"

    if not os.path.exists(manifest_path):
        print(f"❌ 找不到 manifest 文件: {manifest_path}")
        return

    with open(manifest_path, 'r', encoding='utf-8') as f:
        manifest = json.load(f)

    recorded_cmi = manifest.get("package_cmi", "未记录")
    print(f"\n[1] manifest.json 中记录的 package_cmi:")
    print(f"    {recorded_cmi}")

    pkg_dir = f"local_store/agents/{PHC_ID}/openclaw_package"
    print(f"\n[2] 正在计算当前目录的实际 CMI...")
    print(f"    目录: {pkg_dir}")

    try:
        actual_cmi = dir_code_cmi_hid(pkg_dir, HID)
        print(f"\n    实际 CMI: {actual_cmi}")
    except Exception as e:
        print(f"❌ 计算 CMI 失败: {e}")
        return

    print("\n" + "=" * 60)
    print("验证结果")
    print("=" * 60)

    if str(recorded_cmi) == str(actual_cmi):
        print("✅ CMI 一致，配置未被篡改")
    else:
        print("❌ CMI 不一致！")
        print(f"   记录的 CMI: {recorded_cmi}")
        print(f"   实际的 CMI: {actual_cmi}")
        print("\n   → 攻击被检测到！配置已被篡改。")

if __name__ == "__main__":
    main()