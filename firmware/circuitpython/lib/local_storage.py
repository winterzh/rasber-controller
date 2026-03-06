# local_storage.py - Local CSV storagemodule
# CircuitPython Ver

import os
import time

class LocalStorage:
    """
    Local CSV storage
    
    fileformat:
    sensor编号,time1,time2,...
    Aaxis
    address1,val1,val2,...
    address2,val1,val2,...
    Baxis
    address1,val1,val2,...
    Zaxis (optional)
    address1,val1,val2,...
    """
    
    # UTF-8 BOM，For Excel Chinese support
    UTF8_BOM = "\ufeff"
    
    def __init__(self, config, log_func=print):
        self.config = config
        self.log = log_func
        self.data_dir = "/Sensor_local_storage"
        self._ensure_dir()
    
    def _ensure_dir(self):
        """确保datadirexist"""
        try:
            os.listdir(self.data_dir)
        except OSError:
            try:
                os.mkdir(self.data_dir)
                self.log(f"[Storage] mkdir {self.data_dir}")
            except Exception as e:
                self.log(f"[Storage] mkdir failed: {e}")
    
    @property
    def enabled(self):
        return self.config.get("local_storage.enabled", False)
    
    @property
    def period(self):
        return self.config.get("local_storage.period", "month")
    
    def _get_filename(self, timestamp=None):
        """get当beforefile名"""
        if timestamp is None:
            t = time.localtime()
        else:
            t = time.localtime(timestamp)
        
        if self.period == "day":
            return f"{self.data_dir}/data_{t.tm_year:04d}-{t.tm_mon:02d}-{t.tm_mday:02d}.csv"
        else:
            return f"{self.data_dir}/data_{t.tm_year:04d}-{t.tm_mon:02d}.csv"
    
    def _get_timestamp_str(self, timestamp=None):
        """gettime戳string"""
        if timestamp is None:
            t = time.localtime()
        else:
            t = time.localtime(timestamp)
        return f"{t.tm_year:04d}-{t.tm_mon:02d}-{t.tm_mday:02d} {t.tm_hour:02d}:{t.tm_min:02d}"
    
    def _file_exists(self, filepath):
        """Check file exists"""
        try:
            os.stat(filepath)
            return True
        except OSError:
            return False
    
    def _read_existing_data(self, filepath):
        """read现has CSV data"""
        if not self._file_exists(filepath):
            return None
        
        try:
            with open(filepath, "r") as f:
                lines = f.readlines()
            return [line.strip() for line in lines if line.strip()]
        except Exception as e:
            self.log(f"[Storage] read failed: {e}")
            return None
    
    def save_readings(self, readings, timestamp=None):
        """
        savesensorread数
        
        Args:
            readings: Readings list [{"address": int, "a": float, "b": float, "z": float or None}, ...]
            timestamp: time戳，default当beforetime
        """
        if not self.enabled:
            return
        
        if not readings:
            return
        
        filepath = self._get_filename(timestamp)
        ts_str = self._get_timestamp_str(timestamp)
        
        # checkifhas Z axisdata
        has_z = any(r.get("z") is not None for r in readings)
        
        # byaddresssort
        address_list = sorted(set(r["address"] for r in readings))
        readings_map = {r["address"]: r for r in readings}
        
        existing = self._read_existing_data(filepath)
        
        if existing is None:
            # New file
            self._create_new_file(filepath, address_list, readings_map, ts_str, has_z)
        else:
            # Append column
            self._append_column(filepath, existing, address_list, readings_map, ts_str, has_z)
        
        self.log(f"[Storage] saved {len(readings)} 条data到 {filepath}")
    
    def _create_new_file(self, filepath, address_list, readings_map, ts_str, has_z):
        """Createnew CSV file"""
        lines = []
        
        # Header
        lines.append(f"sensor编号,{ts_str}")
        
        # Aaxis
        lines.append("Aaxis")
        for address in address_list:
            r = readings_map.get(address, {})
            a_val = f"{r.get('a', 0):.2f}"
            lines.append(f"{address},{a_val}")
        
        # Baxis
        lines.append("Baxis")
        for address in address_list:
            r = readings_map.get(address, {})
            b_val = f"{r.get('b', 0):.2f}"
            lines.append(f"{address},{b_val}")
        
        # Zaxis
        if has_z:
            lines.append("Zaxis")
            for address in address_list:
                r = readings_map.get(address, {})
                z_val = f"{r.get('z', 0):.2f}" if r.get('z') is not None else ""
                lines.append(f"{address},{z_val}")
        
        try:
            with open(filepath, "w") as f:
                f.write(self.UTF8_BOM + "\n".join(lines) + "\n")
        except Exception as e:
            self.log(f"[Storage] write failed: {e}")
    
    def _append_column(self, filepath, existing, address_list, readings_map, ts_str, has_z):
        """Append new column to existing file"""
        new_lines = []
        section = None
        line_idx = 0
        
        for line in existing:
            if line_idx == 0:
                # Headerrorow，appendtime戳
                new_lines.append(f"{line},{ts_str}")
            elif line in ("Axis_A", "Axis_B", "Axis_Z", "Aaxis", "Baxis", "Zaxis"):
                section = line
                new_lines.append(line)
            else:
                # datarow
                parts = line.split(",")
                if parts:
                    try:
                        address = int(parts[0])
                        r = readings_map.get(address, {})
                        
                        if section in ("Axis_A", "Aaxis"):
                            val = f"{r.get('a', 0):.2f}"
                        elif section in ("Axis_B", "Baxis"):
                            val = f"{r.get('b', 0):.2f}"
                        elif section in ("Axis_Z", "Zaxis"):
                            val = f"{r.get('z', 0):.2f}" if r.get('z') is not None else ""
                        else:
                            val = ""
                        
                        new_lines.append(f"{line},{val}")
                    except:
                        new_lines.append(line)
                else:
                    new_lines.append(line)
            
            line_idx += 1
        
        # if现hasfile没has Z axis但newdatahas
        if has_z and "Zaxis" not in existing:
            new_lines.append("Zaxis")
            # needspadding之before的nullcolumn
            prev_cols = len(existing[0].split(",")) - 1 if existing else 0
            for address in address_list:
                r = readings_map.get(address, {})
                z_val = f"{r.get('z', 0):.2f}" if r.get('z') is not None else ""
                empty_cols = "," * prev_cols
                new_lines.append(f"{address}{empty_cols},{z_val}")
        
        try:
            with open(filepath, "w") as f:
                f.write("\n".join(new_lines) + "\n")
        except Exception as e:
            self.log(f"[Storage] write failed: {e}")
    
    def list_files(self):
        """columnoutalldatafile"""
        try:
            files = []
            for f in os.listdir(self.data_dir):
                if f.endswith(".csv"):
                    stat = os.stat(f"{self.data_dir}/{f}")
                    files.append({
                        "name": f,
                        "size": stat[6]
                    })
            return sorted(files, key=lambda x: x["name"], reverse=True)
        except Exception as e:
            self.log(f"[Storage] columnoutfilefail: {e}")
            return []
    
    def read_file(self, filename):
        """read指定fileinner容"""
        filepath = f"{self.data_dir}/{filename}"
        try:
            with open(filepath, "r") as f:
                return f.read()
        except Exception as e:
            self.log(f"[Storage] read failed: {e}")
            return None
    
    def delete_file(self, filename):
        """Delete file"""
        filepath = f"{self.data_dir}/{filename}"
        try:
            os.remove(filepath)
            self.log(f"[Storage] deleted {filename}")
            return True
        except Exception as e:
            self.log(f"[Storage] delete failed: {e}")
            return False
