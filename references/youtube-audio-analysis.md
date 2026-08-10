# 音频内容分析

当原始标题/描述不明确或用户要求根据内容自动生成元数据时使用。

## 命令

```bash
# 时长
ffprobe -v error -show_entries format=duration -of csv=p=0 <file>

# 静音段检测（判断有无语音间隙）
ffmpeg -i <file> -af "silencedetect=n=-35dB:d=1.5" -f null - 2>&1 | grep silence_duration

# 响度分析
ffprobe -v error -show_entries stream=codec_name,sample_rate,channels -of default=noprint_wrappers=1 <file>
```

## 音频类型判定

| 类型 | 特征 |
|------|------|
| 语音/播客 | 有规律静音段（句间停顿），音量波动大 |
| ASMR 音效 | 几乎无静音（持续触碰声），音量稳定居中 |
| 纯音乐 | 连续无静音，响度稳定 |
| 混合 | 语音段 + 背景音间歇 |

## 元数据生成规则

- **ASMR 音效**：标题 `【ASMR】主题描述 (YYMMDD)`，描述简要说明触发音类型
- **纯中文**：标题和描述只使用简体中文，不包含韩文/英文
- **时长标注**：描述末尾标注时长
