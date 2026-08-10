# ASMR 音频格式选择参考

## 核心原则

视频画面可以丢，音频质量必须保。ASMR 对高频细节敏感（呼吸声、摩擦声），选错格式不可逆损失细节。

## YouTube 音频流

| 编码 | 格式 ID | 码率 | 采样率 | 特点 |
|------|---------|:----:|:------:|------|
| Opus | 251 | ~136kbps | **48kHz** | ASMR 最佳 |
| Opus | 250 | ~69kbps | 48kHz | 低码率 |
| AAC | 140 | ~129kbps | 44.1kHz | 合并格式默认音轨 |

## ASMR 模式关键参数

```
下载: -f "bestaudio[acodec=opus]" (仅音频 ~12MB, 不下视频流)
画面: VP9 黑帧 1920×1080 30fps
容器: .webm (原生 VP9 + Opus)
音频: -c:a copy (绝对不改, 否则破坏 Opus 48kHz)
时长: 黑帧 = 音频 + 30s 余量, -shortest 裁剪
编码加速: -deadline realtime -cpu-used 5 (2.9x speed)
```

## 一句话

> 用 Opus 48kHz → 仅下音频 → WebM 容器 → `-c:a copy` → 塞给 YouTube 转码，最大化保留 ASMR 原始细节。
