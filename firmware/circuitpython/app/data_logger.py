# data_logger.py - 本地datarecord器
# CircuitPython Ver

import os
import json
import time

class DataLogger:
    """本地 JSON datalog，支持 LRU 清理"""
    
    MAX_FILES = 100  # max保留file数
    DATA_DIR = "/data"
    
    def __init__(self):
        self._ensure_dir()
    
    def _ensure_dir(self):
        """确保datadirexist"""
        try:
            os.stat(self.DATA_DIR)
        except OSError:
            try:
                os.mkdir(self.DATA_DIR)
                print(f"[DataLogger] mkdir: {self.DATA_DIR}")
            except Exception as e:
                print(f"[DataLogger] mkdir failed: {e}")
    
    def log(self, data: dict) -> bool:
        """
        recorddata到file
        file名format: YYYYMMDD_HHMMSS.json
        """
        try:
            # 生成file名
            now = time.localtime()
            filename = "{:04d}{:02d}{:02d}_{:02d}{:02d}{:02d}.json".format(
                now.tm_year, now.tm_mon, now.tm_mday,
                now.tm_hour, now.tm_min, now.tm_sec
            )
            filepath = f"{self.DATA_DIR}/{filename}"
            
            # wrotefile
            with open(filepath, "w") as f:
                json.dump(data, f)
            
            # 清理oldfile
            self._cleanup()
            
            return True
            
        except Exception as e:
            print(f"[DataLogger] wrotefail: {e}")
            return False
    
    def log_segments(self, segments: list) -> bool:
        """record多dataseg"""
        try:
            now = time.localtime()
            filename = "{:04d}{:02d}{:02d}_{:02d}{:02d}{:02d}.json".format(
                now.tm_year, now.tm_mon, now.tm_mday,
                now.tm_hour, now.tm_min, now.tm_sec
            )
            filepath = f"{self.DATA_DIR}/{filename}"
            
            with open(filepath, "w") as f:
                f.write("[\n")
                for i, seg in enumerate(segments):
                    f.write(seg)
                    if i < len(segments) - 1:
                        f.write(",\n")
                    else:
                        f.write("\n")
                f.write("]\n")
            
            self._cleanup()
            return True
            
        except Exception as e:
            print(f"[DataLogger] wrotefail: {e}")
            return False
    
    def get_pending_files(self) -> list:
        """getpendingUpload的filelist (bytimesort)"""
        try:
            files = os.listdir(self.DATA_DIR)
            json_files = [f for f in files if f.endswith(".json")]
            json_files.sort()
            return [f"{self.DATA_DIR}/{f}" for f in json_files]
        except:
            return []
    
    def delete_file(self, filepath: str) -> bool:
        """deletedoneUpload的file"""
        try:
            os.remove(filepath)
            return True
        except:
            return False
    
    def _cleanup(self):
        """清理oldfile，保留最new的 MAX_FILES """
        try:
            files = os.listdir(self.DATA_DIR)
            json_files = [f for f in files if f.endswith(".json")]
            
            if len(json_files) <= self.MAX_FILES:
                return
            
            # byfile名sort (time顺序)
            json_files.sort()
            
            # delete最old的file
            to_delete = len(json_files) - self.MAX_FILES
            for i in range(to_delete):
                filepath = f"{self.DATA_DIR}/{json_files[i]}"
                try:
                    os.remove(filepath)
                    print(f"[DataLogger] 清理: {json_files[i]}")
                except:
                    pass
                    
        except Exception as e:
            print(f"[DataLogger] 清理fail: {e}")
    
    def get_stats(self) -> dict:
        """get存储统计"""
        try:
            files = os.listdir(self.DATA_DIR)
            json_files = [f for f in files if f.endswith(".json")]
            
            total_size = 0
            for f in json_files:
                try:
                    stat = os.stat(f"{self.DATA_DIR}/{f}")
                    total_size += stat[6]  # st_size
                except:
                    pass
            
            return {
                "file_count": len(json_files),
                "total_size_kb": total_size // 1024,
                "max_files": self.MAX_FILES
            }
        except:
            return {"file_count": 0, "total_size_kb": 0, "max_files": self.MAX_FILES}
