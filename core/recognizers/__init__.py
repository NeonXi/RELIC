"""
[L-Recognizer] core.recognizers — OCR 识别层

依赖: PySide6 视情况(部分模块仅需 numpy/onnxruntime)
职责: 把截图/像素数据/原始文本转换为结构化结果

详见 .trae/rules/开发规范.md §6.3

## AI 硬约束 — 修改本文件前必读
归属层:    [L-Recognizer] (core/recognizers/)
允许依赖:  numpy, onnxruntime, opencv-python, sqlite3, rapidocr-onnxruntime
禁止依赖:  core.widgets/* / core.pages/* / core.state/*
           (不能调 UI,只能输出结构化结果)
必读规范:  .trae/rules/开发规范.md §6.3

本文件相关红线:
- 禁止返回 Qt 控件 → 只能返回 dict(含 en_name / zh_name / slug / quality)
- 禁止阻塞主线程的长任务 → 必须放 QThread/Signal
- 禁止吞掉 OCR 错误 → 必须 try/except 记录到日志
- 禁止在 OCR 链路里调网络 API → OCR 是离线识别
- 禁止 import 整个 core.* → 只 import 同层 (recognizers) 模块

OPTIONS: 有疑义先读 .trae/rules/开发规范.md §6.3。
"""
