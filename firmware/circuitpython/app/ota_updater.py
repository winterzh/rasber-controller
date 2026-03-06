# ota_updater.py - OTA 远程固件更新
# CircuitPython Ver
#
# 通过 WiFi HTTP 从服务器下载新版本 Python 文件并替换
# 使用 adafruit_requests + socketpool
#
# 流程:
#   1. GET /api/ota/check?version=当前版本 → 有更新?
#   2. 逐文件 GET /api/ota/download/{ver}/{path} → 下载到 .tmp
#   3. SHA256 校验 → 通过则 rename 替换，失败则删除 .tmp
#   4. 全部成功 → microcontroller.reset() 重启

import os
import json
import hashlib
import gc


def check_and_update(config):
    """主入口: 检查并执行 OTA 更新
    
    仅支持 WiFi (需要 socketpool + adafruit_requests)
    4G HTTP 暂未实现
    """
    ota_url = config.get("system.ota_url", "")
    current_ver = config.get("system.firmware_version", "")
    
    if not ota_url:
        return False
    
    print(f"[OTA] check: current={current_ver}, server={ota_url}")
    
    # 建立 HTTP 会话
    session = _make_http_session()
    if session is None:
        print("[OTA] no WiFi HTTP session, skip")
        return False
    
    try:
        # 1. 检查更新
        update_info = _check_update(session, ota_url, current_ver)
        if update_info is None:
            print("[OTA] no update available")
            return False
        
        new_ver = update_info["version"]
        files = update_info["files"]
        print(f"[OTA] update found: {new_ver}, {len(files)} files")
        
        # 2. 逐个下载并替换
        success = _do_update(session, ota_url, new_ver, files)
        
        if success:
            # 3. 更新 config.json 中的版本号
            _update_config_version(config, new_ver)
            print(f"[OTA] update complete! rebooting...")
            
            # 4. 重启
            import microcontroller
            microcontroller.reset()
        else:
            print("[OTA] update failed, keeping current version")
            return False
            
    except Exception as e:
        print(f"[OTA] error: {e}")
        return False
    finally:
        try:
            session._free_sockets()
        except:
            pass
    
    return True


def _make_http_session():
    """创建 HTTP 会话 (仅 WiFi)"""
    try:
        import wifi
        if not wifi.radio.connected:
            print("[OTA] WiFi not connected")
            return None
        
        import socketpool
        import adafruit_requests
        
        pool = socketpool.SocketPool(wifi.radio)
        session = adafruit_requests.Session(pool)
        return session
    except ImportError as e:
        print(f"[OTA] missing lib: {e}")
        return None
    except Exception as e:
        print(f"[OTA] session error: {e}")
        return None


def _check_update(session, ota_url, current_ver):
    """查询服务器是否有新版本
    
    GET {ota_url}/check?version={current_ver}
    返回: {"update_available": true, "version": "...", "files": [...]}
    """
    url = f"{ota_url}/check?version={current_ver}"
    
    try:
        resp = session.get(url, timeout=15)
        if resp.status_code != 200:
            print(f"[OTA] check failed: HTTP {resp.status_code}")
            resp.close()
            return None
        
        data = resp.json()
        resp.close()
        
        if not data.get("update_available", False):
            return None
        
        files = data.get("files", [])
        if not files:
            print("[OTA] update has no files")
            return None
        
        return {
            "version": data["version"],
            "files": files,
            "force": data.get("force", False)
        }
    except Exception as e:
        print(f"[OTA] check error: {e}")
        return None


def _do_update(session, ota_url, version, files):
    """逐个文件下载、校验、替换
    
    files: [{"path": "code.py", "hash": "sha256..."}, ...]
    """
    downloaded = []  # 已成功替换的文件 (用于失败回滚)
    
    for i, file_info in enumerate(files):
        path = file_info["path"]
        expected_hash = file_info.get("hash", "")
        
        print(f"[OTA] ({i+1}/{len(files)}) {path}")
        gc.collect()
        
        # 下载
        url = f"{ota_url}/download/{version}/{path}"
        tmp_path = f"/{path}.tmp"
        
        try:
            ok = _download_file(session, url, tmp_path, expected_hash)
            if not ok:
                print(f"[OTA] FAIL: {path}")
                _cleanup_tmp(tmp_path)
                _rollback(downloaded)
                return False
            
            # 确保目标目录存在
            dest_path = f"/{path}"
            _ensure_dir(dest_path)
            
            # 原子替换: 删旧 → 重命名
            try:
                os.remove(dest_path)
            except OSError:
                pass  # 文件不存在也没关系 (新增文件)
            
            os.rename(tmp_path, dest_path)
            downloaded.append(path)
            print(f"[OTA] OK: {path}")
            
        except Exception as e:
            print(f"[OTA] error on {path}: {e}")
            _cleanup_tmp(tmp_path)
            _rollback(downloaded)
            return False
    
    print(f"[OTA] all {len(files)} files updated successfully")
    return True


def _download_file(session, url, tmp_path, expected_hash):
    """下载单个文件到 tmp_path 并校验 SHA256"""
    try:
        # 确保 tmp 所在目录存在
        _ensure_dir(tmp_path)
        
        resp = session.get(url, timeout=30)
        if resp.status_code != 200:
            print(f"[OTA] download HTTP {resp.status_code}: {url}")
            resp.close()
            return False
        
        # 流式写入 (CircuitPython 内存有限)
        content = resp.content
        resp.close()
        
        # 写入临时文件
        with open(tmp_path, "wb") as f:
            f.write(content)
        
        # SHA256 校验
        if expected_hash:
            actual_hash = _file_sha256(tmp_path)
            if actual_hash != expected_hash:
                print(f"[OTA] hash mismatch: expected {expected_hash[:16]}... got {actual_hash[:16]}...")
                return False
        
        return True
        
    except Exception as e:
        print(f"[OTA] download error: {e}")
        return False


def _file_sha256(filepath):
    """计算文件 SHA256"""
    h = hashlib.new("sha256")
    with open(filepath, "rb") as f:
        while True:
            chunk = f.read(512)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _ensure_dir(filepath):
    """确保文件所在目录存在"""
    parts = filepath.rsplit("/", 1)
    if len(parts) == 2 and parts[0]:
        dir_path = parts[0]
        try:
            os.stat(dir_path)
        except OSError:
            # 目录不存在，逐级创建
            _makedirs(dir_path)


def _makedirs(path):
    """递归创建目录 (CircuitPython 没有 os.makedirs)"""
    parts = path.strip("/").split("/")
    current = ""
    for part in parts:
        current += "/" + part
        try:
            os.stat(current)
        except OSError:
            try:
                os.mkdir(current)
            except OSError:
                pass


def _cleanup_tmp(tmp_path):
    """清理临时文件"""
    try:
        os.remove(tmp_path)
    except OSError:
        pass


def _rollback(downloaded_paths):
    """回滚: 注意 — 对于已替换的文件无法真正回滚
    (因为旧文件已被删除)，只记录警告
    """
    if downloaded_paths:
        print(f"[OTA] WARNING: {len(downloaded_paths)} files already replaced before failure:")
        for p in downloaded_paths:
            print(f"  - {p}")
        print("[OTA] device may need manual recovery via USB")


def _update_config_version(config, new_version):
    """更新 config.json 中的 firmware_version"""
    try:
        with open("/config.json", "r") as f:
            cfg = json.load(f)
        
        cfg["system"]["firmware_version"] = new_version
        
        with open("/config.json", "w") as f:
            json.dump(cfg, f)
        
        print(f"[OTA] config version updated to: {new_version}")
    except Exception as e:
        print(f"[OTA] config update error: {e}")
