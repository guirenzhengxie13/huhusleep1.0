import os
import glob
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

def plot_single_folder_interactive_html():
    # ================= 🎯 路径配置区 =================
    # 直接填入你想要处理的那个具体的设备文件夹路径
    target_dir = r"C:\Users\Lenovo\Desktop\data\画图\this" 
    
    # 自动在当前文件夹下建一个专属的输出文件夹，防止和原文件混在一起
    output_dir = os.path.join(target_dir, "output_html")
    # ===============================================
    
    os.makedirs(output_dir, exist_ok=True)
    
    # 获取该指定文件夹下的所有 CSV 文件
    csv_files = glob.glob(os.path.join(target_dir, "*.csv"))
    
    if not csv_files:
        print(f"⚠️ 在目录中没有找到 CSV 文件: {target_dir}")
        return

    print(f"✅ 发现 {len(csv_files)} 个 CSV 文件，开始生成 24H 动态网页...\n")

    # 直接遍历该文件夹下的文件
    for file_path in csv_files:
        filename = os.path.basename(file_path)
        print(f"   正在生成动态网页: {filename}")
        
        # 1. 读取数据（全天 24 小时数据）
        try:
            df = pd.read_csv(file_path)
            df['time'] = pd.to_datetime(df['time'])
        except Exception as e:
            print(f"      ❌ 读取 {filename} 失败: {e}")
            continue

        # 2. 创建 3行1列 的交互式子图 (共享X轴设为 False，保持独立缩放)
        fig = make_subplots(rows=3, cols=1, 
                            shared_xaxes=False,
                            vertical_spacing=0.08, 
                            subplot_titles=("心率 (Heart Rate)", "呼吸率 (Respiratory Rate)", "体动 (Body Movement)"))

        # --- 添加心率 ---
        fig.add_trace(go.Scatter(x=df['time'], y=df['heart_rate'], 
                                 mode='lines', name='心率', line=dict(color='#FF5722')), 
                      row=1, col=1)
        
        # --- 添加呼吸率 ---
        fig.add_trace(go.Scatter(x=df['time'], y=df['respiratory_rate'], 
                                 mode='lines', name='呼吸率', line=dict(color='#2196F3')), 
                      row=2, col=1)

        # --- 添加体动 ---
        fig.add_trace(go.Scatter(x=df['time'], y=df['body_movement'], 
                                 mode='lines', name='体动', line=dict(color='#4CAF50')), 
                      row=3, col=1)

        # 3. 优化布局和大小
        clean_title = filename.replace('.csv', '')
        fig.update_layout(height=800, width=1200, 
                          title_text=f"全天 24H 体征动态分析图 - {clean_title} (支持鼠标滚轮单独缩放)",
                          hovermode="x unified") 

        # 4. 导出网页文件
        output_filename = filename.replace('.csv', '.html')
        output_path = os.path.join(output_dir, output_filename)
        
        # 开启鼠标滚轮缩放功能
        fig.write_html(output_path, config={'scrollZoom': True})
        print(f"      -> 成功保存网页: {output_filename}")

    print("\n🎉 该文件夹下的所有交互式图表已生成完毕！")
    print(f"📁 请前往这里查看: {output_dir}")

if __name__ == "__main__":
    plot_single_folder_interactive_html()
