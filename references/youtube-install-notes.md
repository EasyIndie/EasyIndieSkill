# youtubeuploader 安装

```bash
# 中国大陆环境
go env -w GOPROXY=https://goproxy.cn,direct
go install github.com/porjo/youtubeuploader/cmd/youtubeuploader@latest
```

子包路径必须用 `cmd/youtubeuploader`，根包只有库代码非主入口。
