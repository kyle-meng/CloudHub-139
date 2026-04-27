import zipfile
import os
import shutil
import argparse
import json
from datetime import datetime

def export_library(output_name=None):
    """将 data 目录和 links.json 打包导出"""
    if not output_name:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_name = f"cloudhub_library_backup_{timestamp}.zip"
    
    # 确保以 .zip 结尾
    if not output_name.endswith('.zip'):
        output_name += '.zip'

    print(f"📦 正在导出全量库源文件...")
    
    files_to_backup = []
    
    # 1. 收集 links.json
    if os.path.exists("links.json"):
        files_to_backup.append("links.json")
    else:
        print("⚠️ 警告: 未找到 links.json，备份可能不完整。")

    # 2. 收集 data 目录
    if os.path.exists("data"):
        for root, dirs, files in os.walk("data"):
            for file in files:
                files_to_backup.append(os.path.join(root, file))
    else:
        print("⚠️ 警告: 未找到 data 目录，无可导出的库数据。")

    if not files_to_backup:
        print("❌ 错误: 没有任何数据可供导出。")
        return

    try:
        with zipfile.ZipFile(output_name, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for file in files_to_backup:
                # 保持相对路径
                zipf.write(file)
                if count := files_to_backup.index(file) + 1:
                    if count % 50 == 0:
                        print(f"  ... 已打包 {count} 个文件")
        
        print(f"\n✅ 导出完成！")
        print(f"✨ 备份文件: {os.path.abspath(output_name)}")
        print(f"📊 文件总数: {len(files_to_backup)}")
    except Exception as e:
        print(f"❌ 导出失败: {e}")

def import_library(zip_path, merge=True):
    """从压缩包导入数据"""
    if not os.path.exists(zip_path):
        print(f"❌ 错误: 找不到备份文件 '{zip_path}'")
        return

    print(f"📥 正在解析备份包: {zip_path} ...")
    
    try:
        with zipfile.ZipFile(zip_path, 'r') as zipf:
            # 校验格式
            namelist = zipf.namelist()
            has_data = any(n.startswith('data/') for n in namelist)
            has_links = 'links.json' in namelist
            
            if not has_data and not has_links:
                print("❌ 错误: 压缩包格式不符合 CloudHub-139 备份标准。")
                return

            # 如果是合并模式，且本地已有 links.json，需要处理冲突
            if merge and has_links and os.path.exists("links.json"):
                print("🔄 正在合并 links.json 配置...")
                # 读取备份中的 links
                with zipf.open('links.json') as f:
                    backup_links = json.load(f)
                # 读取本地 links
                with open("links.json", "r", encoding="utf-8") as f:
                    local_links = json.load(f)
                
                # 合并字典 (本地优先或增量合并)
                new_count = 0
                for k, v in backup_links.items():
                    if k not in local_links:
                        local_links[k] = v
                        new_count += 1
                
                with open("links.json", "w", encoding="utf-8") as f:
                    json.dump(local_links, f, indent=2, ensure_ascii=False)
                print(f"  [+] 已从备份中新增 {new_count} 个链接配置")
                
                # 仅解压 data 目录（跳过 links.json，因为已经手动合并了）
                for member in namelist:
                    if member.startswith('data/'):
                        zipf.extract(member)
            else:
                # 直接全量解压
                print("🚚 正在执行全量覆盖导入...")
                zipf.extractall()
                print("  [+] data 目录与 links.json 已恢复")

        print("\n✅ 导入完成！")
        print("💡 建议重启 cloudhub-139 以加载最新数据。")
    except Exception as e:
        print(f"❌ 导入失败: {e}")

def main():
    parser = argparse.ArgumentParser(description="CloudHub-139 库文件管理工具")
    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # Export
    exp = subparsers.add_parser("export", help="导出库数据到压缩包")
    exp.add_argument("-o", "--output", help="指定输出文件名")

    # Import
    imp = subparsers.add_parser("import", help="从压缩包导入/合并数据")
    imp.add_argument("file", help="压缩包路径")
    imp.add_argument("--no-merge", action="store_false", dest="merge", help="不执行合并，直接覆盖本地配置")

    args = parser.parse_args()

    if args.command == "export":
        export_library(args.output)
    elif args.command == "import":
        import_library(args.file, args.merge)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
