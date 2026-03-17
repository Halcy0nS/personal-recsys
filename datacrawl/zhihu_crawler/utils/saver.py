"""
数据保存工具
"""
import json
import csv
from pathlib import Path
from typing import List, Dict, Any
from datetime import datetime
from rich.console import Console

console = Console()


class DataSaver:
    """数据保存器"""

    def __init__(self, data_dir: str = "./data"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def _generate_filename(self, prefix: str, ext: str) -> str:
        """生成文件名"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"{prefix}_{timestamp}.{ext}"

    def save_json(self, data: List[Dict[str, Any]], prefix: str = "zhihu_data") -> str:
        """保存为JSON格式"""
        filename = self._generate_filename(prefix, "json")
        filepath = self.data_dir / filename

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        console.print(f"[green]✓ JSON数据已保存: {filepath}[/green]")
        return str(filepath)

    def save_csv(self, data: List[Dict[str, Any]], prefix: str = "zhihu_data") -> str:
        """保存为CSV格式"""
        if not data:
            console.print("[yellow]⚠ 没有数据需要保存[/yellow]")
            return ""

        filename = self._generate_filename(prefix, "csv")
        filepath = self.data_dir / filename

        # 扁平化嵌套数据
        flat_data = []
        for item in data:
            flat_item = self._flatten_dict(item)
            flat_data.append(flat_item)

        # 写入CSV
        with open(filepath, 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=flat_data[0].keys())
            writer.writeheader()
            writer.writerows(flat_data)

        console.print(f"[green]✓ CSV数据已保存: {filepath}[/green]")
        return str(filepath)

    def _flatten_dict(self, d: Dict[str, Any], parent_key: str = "", sep: str = "_") -> Dict[str, Any]:
        """扁平化嵌套字典"""
        items = []
        for k, v in d.items():
            new_key = f"{parent_key}{sep}{k}" if parent_key else k
            if isinstance(v, dict):
                items.extend(self._flatten_dict(v, new_key, sep).items())
            else:
                items.append((new_key, v))
        return dict(items)

    def save_all_formats(self, data: List[Dict[str, Any]], prefix: str = "zhihu_data") -> List[str]:
        """同时保存为JSON和CSV格式"""
        files = []

        json_file = self.save_json(data, prefix)
        if json_file:
            files.append(json_file)

        csv_file = self.save_csv(data, prefix)
        if csv_file:
            files.append(csv_file)

        return files
