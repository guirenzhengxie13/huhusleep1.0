import os
os.environ["MPLBACKEND"] = "Agg"
import matplotlib
matplotlib.use("Agg")

import glob
import re
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

# 支持中文字体显示（防止标题或标签乱码）
plt.rcParams['font.sans-serif'] = ['SimHei'] 
plt.rcParams['axes.unicode_minus'] = False

# ================= 🎛️ 全局配置区 =================
# 是否显示平均值线（True 显示，False 不显示）
SHOW_AVG_LINE = False 
# ===============================================


def _find_device_csv(timeline_root, device_id):
    device_dir = os.path.join(timeline_root, device_id)
    if not os.path.isdir(device_dir):
        return None
    csv_files = sorted(glob.glob(os.path.join(device_dir, "*.csv")))
    return csv_files[0] if csv_files else None


def _safe_output_name(device_id, start_time, end_time):
    return (
        f"{device_id}_{start_time.strftime('%Y%m%d_%H%M')}_"
        f"{end_time.strftime('%Y%m%d_%H%M')}.png"
    )


def plot_device_window(csv_path, output_path, device_id, start_time, end_time):
    df = pd.read_csv(csv_path)
    df["time"] = pd.to_datetime(df["time"], format="%Y-%m-%d %H:%M:%S", errors="coerce")
    df = df.dropna(subset=["time"])
    df = df[(df["time"] >= start_time) & (df["time"] <= end_time)]
    if df.empty:
        print(f"   - {device_id} 在指定时间窗内无数据，跳过")
        return False

    fig, axes = plt.subplots(3, 1, figsize=(15, 10), sharex=True)
    fig.suptitle(
        f"8:00-8:00 体征趋势图 - {device_id}",
        fontsize=16,
    )

    axes[0].plot(df["time"], df["heart_rate"], color="#FF5722", label="心率", linewidth=1.5)
    if SHOW_AVG_LINE:
        hr_mean = df["heart_rate"].mean()
        axes[0].axhline(y=hr_mean, color="gray", linestyle="--", alpha=0.8, label=f"平均心率 ({hr_mean:.1f})")
    axes[0].set_ylabel("心率 (bpm)", fontsize=12)
    axes[0].legend(loc="upper right")
    axes[0].grid(True, linestyle=":", alpha=0.6)

    axes[1].plot(df["time"], df["respiratory_rate"], color="#2196F3", label="呼吸率", linewidth=1.5)
    if SHOW_AVG_LINE:
        rr_mean = df["respiratory_rate"].mean()
        axes[1].axhline(y=rr_mean, color="gray", linestyle="--", alpha=0.8, label=f"平均呼吸 ({rr_mean:.1f})")
    axes[1].set_ylabel("呼吸率 (次/分)", fontsize=12)
    axes[1].legend(loc="upper right")
    axes[1].grid(True, linestyle=":", alpha=0.6)

    axes[2].plot(df["time"], df["body_movement"], color="#4CAF50", label="体动", linewidth=1.5)
    if SHOW_AVG_LINE:
        bm_mean = df["body_movement"].mean()
        axes[2].axhline(y=bm_mean, color="gray", linestyle="--", alpha=0.8, label=f"平均体动 ({bm_mean:.1f})")
    axes[2].set_ylabel("体动等级", fontsize=12)
    axes[2].set_xlabel("时间", fontsize=12)
    axes[2].legend(loc="upper right")
    axes[2].grid(True, linestyle=":", alpha=0.6)

    axes[2].xaxis.set_major_locator(mdates.HourLocator(interval=2))
    axes[2].xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    fig.autofmt_xdate(rotation=45)
    fig.tight_layout()
    fig.subplots_adjust(top=0.92)
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return True


def batch_plot_selected_devices(timeline_root, output_dir, device_ids, start_time, end_time):
    os.makedirs(output_dir, exist_ok=True)
    generated = []
    missing = []

    for device_id in device_ids:
        csv_path = _find_device_csv(timeline_root, device_id)
        if not csv_path:
            print(f"   - 未找到设备 timeline CSV: {device_id}")
            missing.append(device_id)
            continue

        output_path = os.path.join(output_dir, _safe_output_name(device_id, start_time, end_time))
        try:
            if plot_device_window(csv_path, output_path, device_id, start_time, end_time):
                generated.append(output_path)
                print(f"   -> {device_id} 保存: {output_path}")
        except Exception as e:
            print(f"   - {device_id} 绘图失败: {e}")
            missing.append(device_id)

    return {"generated": generated, "missing": missing, "output_dir": output_dir}

def batch_plot_vital_signs(target_device=None):
    # 1. 基础路径配置 (锁定最外层的画图目录)
    base_dir = r"C:\Users\Lenovo\Desktop\data\画图"
    output_base_dir = os.path.join(base_dir, "output")
    
    if not os.path.exists(base_dir):
        print(f"❌ 基础路径不存在: {base_dir}")
        return

    # 扫描基准路径下的所有内容
    all_items = os.listdir(base_dir)
    
    # ================= 🎯 核心设备过滤逻辑 =================
    if target_device:
        # 模式 A：单设备点杀模式
        if target_device.lower() == 'output':
            print("❌ 不能将 'output' 文件夹作为设备号进行处理！")
            return
            
        if target_device in all_items and os.path.isdir(os.path.join(base_dir, target_device)):
            device_folders = [target_device]
        else:
            print(f"❌ 在 {base_dir} 下找不到指定的设备文件夹: {target_device}")
            return
    else:
        # 模式 B：全局遍历模式
        device_folders = [
            f for f in all_items 
            if os.path.isdir(os.path.join(base_dir, f)) and f.lower() != 'output'
        ]
    # ========================================================
    
    if not device_folders:
        print(f"⚠️ 目录中没有符合条件的设备文件夹。")
        return

    mode_text = "单设备" if target_device else "全局自动化批量"
    print(f"✅ 发现 {len(device_folders)} 个设备文件夹，启动【{mode_text}】绘图...\n")

    # 外层循环：遍历设备
    for device_id in device_folders:
        input_dir = os.path.join(base_dir, device_id)
        output_dir = os.path.join(output_base_dir, device_id)
        
        # 自动为该设备创建专属的输出文件夹
        os.makedirs(output_dir, exist_ok=True)
        
        # 获取该设备下的所有 CSV 文件
        csv_files = glob.glob(os.path.join(input_dir, "*.csv"))
        
        if not csv_files:
            print(f"   - 设备 {device_id} 文件夹为空，已跳过。")
            continue
            
        print(f"🚀 正在处理设备: {device_id} (共找到 {len(csv_files)} 个文件)")

        # 内层循环：处理该设备下的每一天数据
        for file_path in csv_files:
            filename = os.path.basename(file_path)
            print(f"   正在绘制: {filename}")
            
            # 2. 读取数据
            try:
                df = pd.read_csv(file_path)
                df['time'] = pd.to_datetime(df['time'])
                
                # 时间截取逻辑
                match = re.search(r'\d{4}-\d{2}-\d{2}', filename)
                if match:
                    target_date_str = match.group(0)
                    end_date = pd.to_datetime(target_date_str)
                    
                    start_time = (end_date - pd.Timedelta(days=1)).replace(hour=20, minute=0, second=0)
                    end_time = end_date.replace(hour=8, minute=0, second=0)
                    
                    df = df[(df['time'] >= start_time) & (df['time'] <= end_time)]
                    
                    if df.empty:
                        print(f"      ⚠️ {filename} 在指定期间内无数据，已跳过。")
                        continue
                else:
                    print(f"      ⚠️ 无法从文件名解析日期，默认绘制全天数据。")
                
            except Exception as e:
                print(f"      ❌ 读取 {filename} 失败: {e}")
                continue
            
            # 3. 创建画布 
            fig, axes = plt.subplots(3, 1, figsize=(15, 10), sharex=True)
            fig.suptitle(f"夜间体征趋势图 (20:00 - 08:00) - {filename.replace('.csv', '')}", fontsize=16)

            # --- 图 1：心率 ---
            axes[0].plot(df['time'], df['heart_rate'], color='#FF5722', label='心率', linewidth=1.5)
            if SHOW_AVG_LINE:
                hr_mean = df['heart_rate'].mean()
                axes[0].axhline(y=hr_mean, color='gray', linestyle='--', alpha=0.8, label=f'平均心率 ({hr_mean:.1f})')
            axes[0].set_ylabel('心率 (bpm)', fontsize=12)
            axes[0].legend(loc='upper right')
            axes[0].grid(True, linestyle=':', alpha=0.6)

            # --- 图 2：呼吸率 ---
            axes[1].plot(df['time'], df['respiratory_rate'], color='#2196F3', label='呼吸率', linewidth=1.5)
            if SHOW_AVG_LINE:
                rr_mean = df['respiratory_rate'].mean()
                axes[1].axhline(y=rr_mean, color='gray', linestyle='--', alpha=0.8, label=f'平均呼吸 ({rr_mean:.1f})')
            axes[1].set_ylabel('呼吸率 (次/分)', fontsize=12)
            axes[1].legend(loc='upper right')
            axes[1].grid(True, linestyle=':', alpha=0.6)

            # --- 图 3：体动 ---
            axes[2].plot(df['time'], df['body_movement'], color='#4CAF50', label='体动', linewidth=1.5)
            if SHOW_AVG_LINE:
                bm_mean = df['body_movement'].mean()
                axes[2].axhline(y=bm_mean, color='gray', linestyle='--', alpha=0.8, label=f'平均体动 ({bm_mean:.1f})')
            axes[2].set_ylabel('体动等级', fontsize=12)
            axes[2].set_xlabel('时间', fontsize=12)
            axes[2].legend(loc='upper right')
            axes[2].grid(True, linestyle=':', alpha=0.6)

            # 4. 横坐标时间格式化
            axes[2].xaxis.set_major_locator(mdates.HourLocator(interval=2))
            axes[2].xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
            
            plt.xticks(rotation=45)
            plt.tight_layout()
            plt.subplots_adjust(top=0.92) 

            # 5. 保存图片
            output_filename = filename.replace('.csv', '.png')
            save_path = os.path.join(output_dir, output_filename)
            plt.savefig(save_path, dpi=150, bbox_inches='tight')
            
            # 关闭画布释放内存
            plt.close()
            print(f"      -> 成功保存: {output_filename}")

    print("\n🎉 指定的绘图任务全部完成！")


if __name__ == "__main__":
    # ==========================================
    # 🎛️ 智能指令输入区
    # 玩法说明：
    # 1. 留空 ("") -> 遍历画图目录下所有设备，跑全局模式
    # 2. 纯设备号 ("1031c823b67b618f") -> 仅针对该设备文件夹进行独立渲染
    # ==========================================
    
    USER_INPUT = ""  # <--- 日常需要画单设备时，修改这里！
    
    input_str = USER_INPUT.strip()

    if not input_str:
        print("🕒 检测到输入为空：将遍历所有设备。")
        batch_plot_vital_signs()
    else:
        print(f"🎯 检测到指定设备：仅处理设备 {input_str}。")
        batch_plot_vital_signs(target_device=input_str)
