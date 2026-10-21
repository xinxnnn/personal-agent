#!/usr/bin/env python3
"""
AF 篡改检测测试（本地 PHC 加载 + 修正加密类型）
"""
import sys
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

import json
import hashlib

from crypto_lib import elgamal_decrypt_bytes, elgamal_encrypt_bytes, compute_af_formal
from user.crypto import dl_generate_user_keypair, sha256_hex
from user.models import PIIModel, BIModel, UserInfo
from user.apply_agent import request_cmm_init, request_cmm_submit

# ====== 使用你在 Web 界面注册时的实际信息 ======
USER = UserInfo(
    pii=PIIModel(
        name="Alice",
        id_number="IDCARD123456",
        email="alice@example.com"
    ),
    bi=BIModel(
        passport_number="P123456789",
        pic_string="face_base64"
    )
)
# =============================================

def load_phc_from_local(id_number: str):
    """从本地 tp_db 读取已签发的 PHC"""
    hid = sha256_hex(id_number)
    tp_db_path = os.path.join(PROJECT_ROOT, "local_store", "tp_db", f"{hid}.json")
    if not os.path.exists(tp_db_path):
        print(f"❌ 找不到本地 PHC 文件: {tp_db_path}")
        print("   请确认 TP 已经签发了该用户的 PHC（在 TP Console 中批准）")
        return None
    with open(tp_db_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    phc = data.get("phc")
    if not phc:
        print("❌ 本地 PHC 文件中没有 phc 字段")
    return phc

def main():
    print("=" * 60)
    print("AF 篡改检测测试（本地 PHC 加载）")
    print("=" * 60)

    ap_base = "http://127.0.0.1:8002"

    # 1. 加载本地 PHC（跳过远程请求）
    print("\n[1] 从本地加载 PHC...")
    phc = load_phc_from_local(USER.pii.id_number)
    if not phc:
        return
    print("✅ PHC 加载成功")

    hid = sha256_hex(USER.pii.id_number)
    print(f"   HID: {hid[:32]}...")

    # 2. 获取 CMM（仍然需要 AP）
    print("\n[2] 获取 CMM...")
    try:
        cmm_data = request_cmm_init(ap_base, phc, USER, agent_type="octopus")
        cmc = cmm_data["cmm"]
        sk = int(cmm_data["sk"])
        pk = int(cmm_data["pk"])
        print("✅ CMM 获取成功")
    except Exception as e:
        print(f"❌ 获取 CMM 失败: {e}")
        return

    # 3. 获取 PA
    print("\n[3] 向 AP 请求 PA...")
    try:
        result = request_cmm_submit(ap_base, cmc, hid, phc, pk)
        par = result.get("par")
        if not par:
            print("❌ 获取 PA 失败")
            return
        print("✅ PA 获取成功（已加密）")
    except Exception as e:
        print(f"❌ 获取 PA 失败: {e}")
        return

    # 4. 攻击者解密并篡改 AF
    print("\n[4] 攻击者截获并解密 PA...")
    raw = elgamal_decrypt_bytes(sk, par)
    obj = json.loads(raw.decode())

    old_af = obj.get("PHC", {}).get("ASO", {}).get("TPM", {}).get("AF")
    print(f"   原始 AF: {old_af}")

    print("\n[5] 攻击者篡改 AF...")
    new_af = "99999999999999999999999999999999999999"
    obj["PHC"]["ASO"]["TPM"]["AF"] = new_af
    print(f"   篡改 AF: {new_af}")

    print("\n[6] 攻击者重新加密并伪造响应...")
    # 关键修正：序列化为 bytes
    pt_bytes = json.dumps(obj).encode('utf-8')
    fake_par = elgamal_encrypt_bytes(pk, pt_bytes)

    print("\n[7] 用户端验证 AF...")
    fake_decrypted = json.loads(elgamal_decrypt_bytes(sk, fake_par).decode())

    ap_pk = int(fake_decrypted.get("ap_pk", 0))
    tp_pk = int(fake_decrypted.get("tp_pk", 0))
    cmi = int(fake_decrypted.get("PA", {}).get("APM", {}).get("CMI", 0))
    crf = int(fake_decrypted.get("PHC", {}).get("SCID", {}).get("RF", 0))
    r_bind2 = int(fake_decrypted.get("r_bind2", 0))
    af_received = fake_decrypted.get("PHC", {}).get("ASO", {}).get("TPM", {}).get("AF")

    af_calc = compute_af_formal(hid, ap_pk, tp_pk, cmi, crf, r_bind2)

    print("\n" + "=" * 60)
    print("验证结果")
    print("=" * 60)
    print(f"接收到的 AF: {af_received}")
    print(f"重算的 AF:   {af_calc}")
    print(f"是否一致:    {af_received == str(af_calc)}")

    if af_received == str(af_calc):
        print("\n⚠️ 警告：AF 验证通过，攻击可能成功！")
    else:
        print("\n✅ 攻击被检测到！AF 验证失败，PA 被拒绝。")

    print("\n" + "=" * 60)

if __name__ == "__main__":
    main()