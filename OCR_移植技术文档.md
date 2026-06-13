# WarframeMonitor - 截图→OCR→纠错→查询字符串 技术文档

> 本文档涵盖从截图获取、OCR文字识别、结果纠错、到生成Warframe Market查询字符串的完整流水线，供移植到其他项目使用。

---

## 一、整体技术栈

| 层级 | 技术/库 | 版本 | 用途 |
|------|---------|------|------|
| 编程语言 | C++ (MSVC) | VS2022 | 主体逻辑 |
| 推理引擎 | ONNX Runtime | - | 运行PP-OCRv3 ONNX模型 |
| 图像处理 | OpenCV | 4.x | 截图预处理、box绘制、图像变换 |
| 屏幕截图 | Windows GDI (BitBlt) | - | 游戏窗口截图 |
| OCR检测模型 | PP-OCRv3 DB-Net | ONNX格式 | 文字区域检测 |
| OCR方向分类 | PP-OCR Mobile v2 CLS | ONNX格式 | 文字方向180°分类 |
| OCR识别模型 | PP-OCRv3 CRNN | ONNX格式 | 文字内容识别 |
| OCR字典 | ppocr_keys_v1.txt | ~6600字符 | 中英文+符号字符集映射 |
| HTTP客户端 | libcurl | - | Warframe Market API 查询 |
| JSON解析 | nlohmann/json | v3.11.3 | API返回数据解析 |
| 字体渲染 | GDI+ (GdipDrawString) | - | 结果叠加显示 |
| SSL/TLS | Schannel / OpenSSL | - | HTTPS安全连接 |

---

## 二、完整流水线架构

```
┌─────────────────────────────────────────────────────────────────┐
│                     总流水线 (OCR Pipeline)                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  [1. 游戏状态检测]                                               │
│       │                                                          │
│       ▼                                                          │
│  [2. 屏幕截图] ─── Windows GDI BitBlt 捕获游戏窗口               │
│       │                                                          │
│       ▼                                                          │
│  [3. 图片预处理] ─── resize, cvtColor, normalize, copyMakeBorder │
│       │                                                          │
│       ▼                                                          │
│  [4. DB-Net 文字检测] ─── getTextBoxes()                         │
│       │  输出: TextBox[4角坐标 + 置信度score]                     │
│       ▼                                                          │
│  [5. Angle-Net 方向分类] ─── getAngles()                         │
│       │  输出: angle[index, score, time]                          │
│       ▼                                                          │
│  [6. CRNN-Net 文字识别] ─── getTextLine()                        │
│       │  输出: textScores[识别文字 + 置信度]                      │
│       ▼                                                          │
│  [7. 结果纠错] ─── 字符过滤 + 正则匹配 + 字符串替换               │
│       │                                                          │
│       ▼                                                          │
│  [8. 构建查询字符串] ─── 拼接Warframe Market API URL              │
│       │                                                          │
│       ▼                                                          │
│  [9. HTTP API 查询] ─── libcurl → https://api.warframe.market    │
│       │                                                          │
│       ▼                                                          │
│  [10. 结果叠加显示] ─── GDI+ 在截图上绘制结果(可选)               │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 三、OCR模型与参数（核心）

### 3.1 模型文件清单

| 模型文件 | 大小 | 用途 | 原始框架 |
|----------|------|------|----------|
| `models/ch_PP-OCRv3_det_infer.onnx` | 2.3 MB | 文字检测 (DB-Net) | PaddleOCR |
| `models/ch_ppocr_mobile_v2.0_cls_infer.onnx` | 572 KB | 文字方向分类 (AngleNet) | PaddleOCR |
| `models/ch_PP-OCRv3_rec_infer.onnx` | 10.2 MB | 文字识别 (CRNN) | PaddleOCR |
| `models/ppocr_keys_v1.txt` | ~6KB | 识别字符集字典 | PaddleOCR |

### 3.2 模型输入输出参数（标准PP-OCRv3规格）

#### DB-Net (检测模型)
```
模型名称: ch_PP-OCRv3_det_infer.onnx
输入节点:
  - x: shape [1, 3, 960, 960]  (NCHW格式, 动态batch, HxW默认960x960)
    - 数据类型: float32
    - 均值归一化: mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]
    - 像素值范围: [0, 1] (除以255后归一化)
    
输出节点:
  - sigmoid_0.tmp_0: shape [1, 1, H, W]  (概率图, probability map)
  - tmp_10: shape [1, 1, H, W]            (阈值图, threshold map)  

后处理参数 (DB后处理):
  - thresh: 0.3          (二值化阈值)
  - box_thresh: 0.6      (检测框置信度阈值)
  - max_candidates: 1000  (最大候选框数)
  - unclip_ratio: 1.5    (框膨胀系数)
  - use_dilation: false  (是否使用膨胀)
  - score_mode: "fast"   (评分模式)
```

#### AngleNet (方向分类模型)
```
模型名称: ch_ppocr_mobile_v2.0_cls_infer.onnx
输入节点:
  - x: shape [1, 3, 48, 192]  (NCHW格式)
    - 数据类型: float32
    - 均值归一化: mean=[0.5, 0.5, 0.5], std=[0.5, 0.5, 0.5]
    - 像素值范围: [0, 1]
    
输出节点:
  - softmax_0.tmp_0: shape [1, 2]  (二分类: 0度 / 180度)
  
分类逻辑:
  - label 0 → 文字角度 = 0° (正常方向)
  - label 1 → 文字角度 = 180° (需要翻转)
```

#### CRNN (识别模型)
```
模型名称: ch_PP-OCRv3_rec_infer.onnx
输入节点:
  - x: shape [1, 3, 48, 320]  (NCHW格式, 宽度动态)
    - 数据类型: float32
    - 均值归一化: mean=[0.5, 0.5, 0.5], std=[0.5, 0.5, 0.5]
    - 像素值范围: [0, 1]
    
输出节点:
  - softmax_0.tmp_0: shape [T, 1, num_classes]  (CTC解码前的概率序列)
    - T: 时间步长 (与输入宽度有关)
    - num_classes: 字符集大小 (~6625, 见字典文件)

CTC解码参数:
  - 字符集: ppocr_keys_v1.txt (6623个可识别字符)
  - 空白符索引: 0  (CTC blank)
  - 合并重复: true (CTC merge repeats)
```

---

## 四、核心代码逻辑（伪代码+关键实现）

### 4.1 模型初始化

```cpp
// ===== Init Models =====
// 从程序字符串中提取的初始化日志格式

// 1. 初始化ONNX Runtime环境
Ort::Env env(ORT_LOGGING_LEVEL_WARNING, "WfOCR");
Ort::SessionOptions sessionOptions;
sessionOptions.SetIntraOpNumThreads(1);
sessionOptions.SetGraphOptimizationLevel(GraphOptimizationLevel::ORT_ENABLE_ALL);

// 2. 加载三个ONNX模型
const wchar_t* detModelPath = L"models/ch_PP-OCRv3_det_infer.onnx";
const wchar_t* clsModelPath = L"models/ch_ppocr_mobile_v2.0_cls_infer.onnx";
const wchar_t* recModelPath = L"models/ch_PP-OCRv3_rec_infer.onnx";

Ort::Session dbNetSession(env, detModelPath, sessionOptions);    // "--- Init DbNet ---"
Ort::Session angleNetSession(env, clsModelPath, sessionOptions); // "--- Init AngleNet ---"
Ort::Session crnnNetSession(env, recModelPath, sessionOptions);  // "--- Init CrnnNet ---"

// 3. 加载字符字典
// 从程序字符串: "total keys size(%lu)" - 输出字典大小
// 从程序字符串: "The keys.txt file was not found" - 错误提示
std::vector<std::string> charDict;
std::ifstream keysFile("models/ppocr_keys_v1.txt");
std::string line;
while (std::getline(keysFile, line)) {
    if (!line.empty()) {
        charDict.push_back(line);  // 每个字符为一行
    }
}
// 字典大小约6623字符, 包含: 汉字、数字、英文大小写、标点符号
// 第0位为CTC blank占位符

printf("Init Models Success!\n");
```

### 4.2 截图获取

```cpp
// 游戏状态检测: 读取Warframe日志检查是否在遗物选择界面
// 程序字符串: "\Warframe\EE.log"
// 程序字符串: "VoidProjections: GetVoidProjectionRewards"

// 截图参数
cv::Mat captureScreen(HWND hWnd) {
    // 获取窗口客户区
    RECT rect;
    GetClientRect(hWnd, &rect);
    int width = rect.right - rect.left;
    int height = rect.bottom - rect.top;
    
    // Windows GDI 截图
    HDC hdcWindow = GetDC(hWnd);
    HDC hdcMemory = CreateCompatibleDC(hdcWindow);
    HBITMAP hBitmap = CreateCompatibleBitmap(hdcWindow, width, height);
    HBITMAP hOldBitmap = (HBITMAP)SelectObject(hdcMemory, hBitmap);
    
    BitBlt(hdcMemory, 0, 0, width, height, hdcWindow, 0, 0, SRCCOPY);
    
    // 转为OpenCV Mat (BGRA格式)
    BITMAPINFO bmi = {0};
    bmi.bmiHeader.biSize = sizeof(BITMAPINFOHEADER);
    bmi.bmiHeader.biWidth = width;
    bmi.bmiHeader.biHeight = -height;  // 负值表示从上到下
    bmi.bmiHeader.biPlanes = 1;
    bmi.bmiHeader.biBitCount = 32;
    bmi.bmiHeader.biCompression = BI_RGB;
    
    cv::Mat image(height, width, CV_8UC4);
    GetDIBits(hdcMemory, hBitmap, 0, height, image.data, &bmi, DIB_RGB_COLORS);
    
    SelectObject(hdcMemory, hOldBitmap);
    DeleteDC(hdcMemory);
    ReleaseDC(hWnd, hdcWindow);
    DeleteObject(hBitmap);
    
    // BGR转RGB
    cv::cvtColor(image, image, cv::COLOR_BGRA2RGB);
    return image;
}
```

### 4.3 图片预处理（核心参数）

```cpp
// 预处理函数: 缩放+填充+归一化
// 程序字符串: "ScaleParam(sw:%d,sh:%d,dw:%d,dh:%d,%f,%f)"
//   sw=源宽, sh=源高, dw=目标宽, dh=目标高, scaleX, scaleY

cv::Mat preprocessImage(const cv::Mat& src, 
                         int targetWidth, int targetHeight,
                         const std::vector<float>& mean,
                         const std::vector<float>& std) 
{
    // 1. 等比例缩放 (保持宽高比)
    float ratio = std::min(
        (float)targetWidth / src.cols, 
        (float)targetHeight / src.rows
    );
    int newW = (int)(src.cols * ratio);
    int newH = (int)(src.rows * ratio);
    
    cv::Mat resized;
    cv::resize(src, resized, cv::Size(newW, newH), 0, 0, cv::INTER_LINEAR);
    
    // 2. 填充到目标尺寸 (右下方填充)
    int padRight = targetWidth - newW;
    int padBottom = targetHeight - newH;
    cv::Mat padded;
    cv::copyMakeBorder(resized, padded, 
        0, padBottom, 0, padRight, 
        cv::BORDER_CONSTANT, cv::Scalar(0, 0, 0));
    
    // 3. 归一化: (pixel / 255.0 - mean) / std
    // 检测模型: mean=[0.485,0.456,0.406], std=[0.229,0.224,0.225]
    // 识别/分类模型: mean=[0.5,0.5,0.5], std=[0.5,0.5,0.5]
    cv::Mat normalized;
    padded.convertTo(normalized, CV_32FC3, 1.0 / 255.0);
    
    std::vector<cv::Mat> channels(3);
    cv::split(normalized, channels);
    for (int c = 0; c < 3; c++) {
        channels[c] = (channels[c] - mean[c]) / std[c];
    }
    cv::merge(channels, normalized);
    
    // 4. HWC → CHW
    cv::Mat chw(targetHeight, targetWidth, CV_32FC3);
    // ... 维度转换 ...
    
    return chw;
}
```

### 4.4 DB-Net 文字检测

```cpp
// ========== step: dbNet getTextBoxes ==========
// 程序字符串: "TextBox[%d](+padding)[score(%f),[x:%d,y:%d],[x:%d,y:%d],[x:%d,y:%d],[x:%d,y:%d]]"
// 程序字符串: "dbNetTime(%fms)"  - 检测耗时

struct TextBox {
    std::vector<cv::Point> boxPoints;  // 4个角点
    float score;                        // 置信度
};

std::vector<TextBox> dbNetDetect(cv::Mat& image) {
    // 1. 预处理: resize到960x960, 归一化 mean=[0.485,0.456,0.406], std=[0.229,0.224,0.225]
    cv::Mat input = preprocessImage(image, 960, 960, 
        {0.485f, 0.456f, 0.406f}, 
        {0.229f, 0.224f, 0.225f});
    
    // 2. ONNX推理
    auto outputTensors = dbNetSession.Run(...);
    cv::Mat probMap = outputTensors[0];   // 概率图 [1,1,H,W]
    cv::Mat threshMap = outputTensors[1]; // 阈值图 [1,1,H,W]
    
    // 3. DB后处理 (Differentiable Binarization decoder)
    //    - 二值化: probMap > 0.3
    //    - 查找轮廓: cv::findContours
    //    - 轮廓近似 + 最小外接矩形: cv::minAreaRect
    //    - unclip膨胀: unclip_ratio = 1.5
    //    - 置信度过滤: box_thresh = 0.6
    //    - 坐标缩放回原图尺寸
    
    // 4. 从概率图和阈值图计算近似二值图
    double threshold_val = 0.3;
    cv::Mat binary;
    cv::threshold(probMap, binary, threshold_val, 1.0, cv::THRESH_BINARY);
    binary.convertTo(binary, CV_8UC1, 255);
    
    // 5. 查找轮廓
    std::vector<std::vector<cv::Point>> contours;
    cv::findContours(binary, contours, cv::RETR_LIST, cv::CHAIN_APPROX_SIMPLE);
    
    std::vector<TextBox> results;
    for (const auto& contour : contours) {
        float area = (float)cv::contourArea(contour);
        if (area < 10) continue;  // 过滤太小的区域
        
        // 最小外接矩形
        cv::RotatedRect minRect = cv::minAreaRect(contour);
        
        // Unclip膨胀 (unclip_ratio = 1.5)
        // ... 膨胀逻辑 ...
        
        // 获取4个角点
        cv::Point2f pts[4];
        minRect.points(pts);
        
        // 计算置信度 (区域内概率图的均值)
        float score = computeBoxScore(probMap, minRect);
        if (score < 0.6f) continue;  // box_thresh
        
        // 坐标缩放回原图
        float scaleX = (float)image.cols / 960.0f;
        float scaleY = (float)image.rows / 960.0f;
        for (auto& pt : pts) {
            pt.x *= scaleX;
            pt.y *= scaleY;
        }
        
        TextBox box;
        box.boxPoints = {cv::Point(pts[0]), cv::Point(pts[1]), 
                         cv::Point(pts[2]), cv::Point(pts[3])};
        box.score = score;
        results.push_back(box);
        
        // 日志: "TextBox[%d](+padding)[score(%f),[x:%d,y:%d],...]"
    }
    
    return results;
}
```

### 4.5 AngleNet 方向分类

```cpp
// ========== step: angleNet getAngles ==========
// 程序字符串: "angle[%d][index(%d), score(%f), time(%fms)]"
// index: 0=0°, 1=180°

int classifyTextAngle(cv::Mat& textRegion) {
    // 1. 裁剪文字区域并预处理
    //    resize到48x192, 归一化 mean=[0.5,0.5,0.5], std=[0.5,0.5,0.5]
    cv::Mat input = preprocessImage(textRegion, 192, 48,
        {0.5f, 0.5f, 0.5f}, {0.5f, 0.5f, 0.5f});
    
    // 2. ONNX推理
    auto outputTensors = angleNetSession.Run(...);
    // 输出: [1, 2] - 两个类别的概率
    
    float* probs = outputTensors[0].GetTensorMutableData<float>();
    int label = (probs[0] > probs[1]) ? 0 : 1;
    float score = std::max(probs[0], probs[1]);
    
    // label=0 → 文字方向正常
    // label=1 → 文字方向翻转180°, 需要 cv::flip 或 cv::rotate
    return label;
}
```

### 4.6 CRNN 文字识别

```cpp
// ========== step: crnnNet getTextLine ==========
// 程序字符串: "textScores[%d]{%s}"  - 识别结果: 索引+文字+分数
// 程序字符串: "textLine[%d](%s)"    - 识别文字行

std::string crnnRecognize(cv::Mat& textRegion, float& avgScore) {
    // 1. 检测文字方向 - 调用AngleNet
    int angleLabel = classifyTextAngle(textRegion);
    if (angleLabel == 1) {
        // 翻转180°
        cv::rotate(textRegion, textRegion, cv::ROTATE_180);
    }
    
    // 2. 预处理: resize到高度48, 宽度按比例缩放, 最大320
    //    归一化 mean=[0.5,0.5,0.5], std=[0.5,0.5,0.5]
    float ratio = 48.0f / textRegion.rows;
    int targetW = std::min((int)(textRegion.cols * ratio), 320);
    cv::Mat input = preprocessImage(textRegion, targetW, 48,
        {0.5f, 0.5f, 0.5f}, {0.5f, 0.5f, 0.5f});
    
    // 3. ONNX推理
    auto outputTensors = crnnNetSession.Run(...);
    // 输出: [T, 1, num_classes] - CTC概率序列
    
    // 4. CTC贪心解码
    //    合并连续重复字符, 去除blank(索引0)
    std::string result;
    avgScore = 0.0f;
    int lastIdx = 0;  // blank index
    int T = outputShape[0];
    int numClasses = outputShape[2];
    
    for (int t = 0; t < T; t++) {
        // 找到最大概率字符索引
        int maxIdx = 0;
        float maxProb = 0;
        for (int c = 0; c < numClasses; c++) {
            float prob = probs[t * numClasses + c];
            if (prob > maxProb) {
                maxProb = prob;
                maxIdx = c;
            }
        }
        
        // CTC解码规则:
        // - 索引0为blank, 跳过
        // - 连续相同字符去重
        if (maxIdx > 0 && maxIdx < charDict.size() && maxIdx != lastIdx) {
            result += charDict[maxIdx];
            avgScore += maxProb;
        }
        lastIdx = maxIdx;
    }
    
    if (!result.empty()) {
        avgScore /= result.length();
    }
    
    return result;
}
```

### 4.7 文字纠错与过滤（核心后处理）

```cpp
// ========== 纠错流水线 ==========
// 从程序二进制中提取的关键参数:

// 1. 需过滤的特殊字符 (OCR常见误识别字符)
// 从程序字符串: "'_|\/=[]【】'",".=-~!()<>{}@#$%^&*2x"
const std::string FILTER_CHARS = 
    "_|\\/=[]【】\"',.=-~!()<>{}@#$%^&*2x";

// 2. 价格/数量验证正则
// 从程序字符串: "^[0-9]+$" 和 "^[✔✓]*[0-9]+$"
const std::regex PRICE_REGEX(R"(^[0-9]+$)");
const std::regex MARKED_PRICE_REGEX(R"(^[✔✓]*[0-9]+$)");

// 3. 字符串替换纠错表 (从程序字符串: "Replaced" 推断)
// Warframe中常见OCR误识别 → 正确值 的映射
const std::map<std::string, std::string> OCR_CORRECTIONS = {
    // OCR常见混淆字符映射 (中英文)
    {"0", "O"},   // 数字0→字母O (取决于上下文)
    {"O", "0"},   // 字母O→数字0 (取决于上下文)
    {"l", "1"},   // 小写l→数字1
    {"I", "1"},   // 大写I→数字1
    {"S", "5"},   // 字母S→数字5
    {"B", "8"},   // 字母B→数字8
    // Warframe物品名常见OCR错误 (具体映射视实际场景)
};

// 4. 主纠错函数
std::string correctOCRText(const std::string& rawText) {
    std::string result = rawText;
    
    // Step 1: 去除首尾空白
    result.erase(0, result.find_first_not_of(" \t\n\r"));
    result.erase(result.find_last_not_of(" \t\n\r") + 1);
    
    // Step 2: 过滤特殊字符 (被硬编码过滤的字符集)
    for (char c : FILTER_CHARS) {
        result.erase(std::remove(result.begin(), result.end(), c), result.end());
    }
    
    // Step 3: 去除连续空格
    auto newEnd = std::unique(result.begin(), result.end(), 
        [](char a, char b) { return a == ' ' && b == ' '; });
    result.erase(newEnd, result.end());
    
    // Step 4: 应用字符替换纠错表
    // (程序中使用 "Replaced" 标记替换操作)
    for (const auto& [wrong, correct] : OCR_CORRECTIONS) {
        size_t pos = 0;
        while ((pos = result.find(wrong, pos)) != std::string::npos) {
            result.replace(pos, wrong.length(), correct);
            pos += correct.length();
        }
    }
    
    // Step 5: 正则验证(对价格/数量字段)
    if (std::regex_match(result, MARKED_PRICE_REGEX)) {
        // 去除✔✓标记, 仅保留数字
        result.erase(std::remove_if(result.begin(), result.end(),
            [](char c) { return c == L'✔' || c == L'✓'; }), result.end());
    }
    
    return result;
}

// 5. 游戏物品名特殊处理
// Warframe遗物奖励格式: "物品名 数量" 或 "物品名 (已拥有数量)"
// OCR识别后需要提取纯物品名, 用于API查询
std::string extractItemName(const std::string& ocrResult) {
    // 去除数量后缀 " x1", " x2" 等
    std::string name = ocrResult;
    size_t xPos = name.find(" x");
    if (xPos != std::string::npos) {
        name = name.substr(0, xPos);
    }
    
    // 去除括号内容 "(已拥有)"
    size_t parenPos = name.find("(");
    if (parenPos != std::string::npos) {
        name = name.substr(0, parenPos);
    }
    
    // Trim
    name.erase(0, name.find_first_not_of(" \t"));
    name.erase(name.find_last_not_of(" \t") + 1);
    
    return name;
}
```

### 4.8 构建查询字符串

```cpp
// ========== 构建查询参数 ==========
// Warframe Market API v2 端点:
//   https://api.warframe.market/v2/items           - 获取所有物品
//   https://api.warframe.market/v2/item/{slug}      - 按slug获取物品
//   https://api.warframe.market/v2/orders/item/{slug}?user=xxx  - 获取卖单
//   https://api.warframe.market/v2/item/vaulted/top - 入库物品排行

struct ItemInfo {
    std::string slug;      // API使用的URL友好名称
    std::string name;      // 英文物品名
    std::string zhName;    // 中文物品名 (OCR结果)
    int ducats;            // 杜卡德金币价值
    int platinum;          // 白金价格
    bool vaulted;          // 是否入库
};

// 根据OCR结果查询Warframe Market
std::string buildQueryURL(const std::string& ocrItemName) {
    // 1. 本地名称匹配 (OCR中文名 → 游戏内英文slug)
    //    程序会先从本地数据库/缓存中找到对应物品的slug
    //    这里使用了Warframe Market v2的items接口获取全量数据
    
    // 2. 构建查询URL
    std::string baseURL = "https://api.warframe.market/v2";
    
    // 示例: 查询物品所有卖单
    // GET https://api.warframe.market/v2/orders/item/{slug}/sell
    std::string queryURL = baseURL + "/orders/item/" + slug + "/sell";
    
    // 可选参数
    queryURL += "?user=pc";          // 平台: pc/xbox/ps4/switch
    // queryURL += "&platinum_min=0";  // 最低白金价过滤
    
    printf("[系统] 正在从 Warframe Market v2 拉取数据库...\n");
    return queryURL;
}

// 从API响应中解析价格信息
void parseMarketResponse(const std::string& jsonResponse) {
    // 使用nlohmann/json解析
    using json = nlohmann::json;
    auto data = json::parse(jsonResponse);
    
    // 提取关键字段
    // - slug: 物品标识
    // - ducats: 杜卡德价值
    // - i18n.name.en: 英文名
    // - vaulted: 是否入库
    
    printf("[系统] 数据库就绪。\n");
}
```

---

## 五、配置文件说明

```json
// config.json
{
    "displayDuration": 5,    // 结果显示时长(秒)
    "displayMode": 0,        // 显示模式: 0=叠加显示 1=弹窗
    "goldThreshold": 5       // 高亮阈值(白金价低于此值高亮显示)
}
```

---

## 六、移植清单

### 6.1 必须复制的文件

```
models/
├── ch_PP-OCRv3_det_infer.onnx          # 检测模型 (必须)
├── ch_ppocr_mobile_v2.0_cls_infer.onnx # 方向分类模型 (必须)
├── ch_PP-OCRv3_rec_infer.onnx          # 识别模型 (必须)
└── ppocr_keys_v1.txt                   # 字符字典 (必须)

config.json                              # 配置文件 (可选, 按需修改)
```

### 6.2 必须引入的依赖库

| 依赖库 | 用途 | Python替代方案 |
|--------|------|----------------|
| ONNX Runtime | 模型推理 | `onnxruntime` (pip) |
| OpenCV 4.x | 图像处理 | `opencv-python` (pip) |
| libcurl | HTTP请求 | `requests` 或 `httpx` |
| nlohmann/json | JSON解析 | 内置 `json` 模块 |
| GDI / GDI+ | 截图+渲染 | `PIL/Pillow` + `mss`/`pyautogui` |

### 6.3 Python移植推荐方案

如果移植到Python项目:

```python
# 推荐依赖
pip install onnxruntime        # ONNX推理
pip install opencv-python      # OpenCV图像处理
pip install pillow             # 图像处理辅助
pip install mss                # 快速跨平台截图
pip install requests           # HTTP请求
pip install numpy              # 数组运算
```

**Python核心代码示例:**

```python
import cv2
import numpy as np
import onnxruntime as ort

class PPOcrV3:
    """PP-OCRv3 文字识别引擎"""
    
    def __init__(self, model_dir="models"):
        # 模型路径
        self.det_model = f"{model_dir}/ch_PP-OCRv3_det_infer.onnx"
        self.cls_model = f"{model_dir}/ch_ppocr_mobile_v2.0_cls_infer.onnx"
        self.rec_model = f"{model_dir}/ch_PP-OCRv3_rec_infer.onnx"
        self.dict_path = f"{model_dir}/ppocr_keys_v1.txt"
        
        # ONNX Runtime 会话
        self.det_session = ort.InferenceSession(self.det_model)
        self.cls_session = ort.InferenceSession(self.cls_model)
        self.rec_session = ort.InferenceSession(self.rec_model)
        
        # 加载字符字典
        with open(self.dict_path, 'r', encoding='utf-8') as f:
            self.char_dict = [''] + [line.strip() for line in f if line.strip()]
        
        # 预处理参数
        self.det_mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
        self.det_std  = np.array([0.229, 0.224, 0.225], dtype=np.float32)
        self.rec_mean = np.array([0.5, 0.5, 0.5], dtype=np.float32)
        self.rec_std  = np.array([0.5, 0.5, 0.5], dtype=np.float32)
        
    def preprocess(self, img, target_w, target_h, mean, std):
        """图像预处理: 缩放+填充+归一化"""
        h, w = img.shape[:2]
        ratio = min(target_w / w, target_h / h)
        new_w, new_h = int(w * ratio), int(h * ratio)
        
        resized = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
        
        padded = np.zeros((target_h, target_w, 3), dtype=np.float32)
        padded[:new_h, :new_w] = resized
        
        padded = padded / 255.0
        padded = (padded - mean) / std
        padded = np.transpose(padded, (2, 0, 1))  # HWC → CHW
        padded = np.expand_dims(padded, axis=0)     # CHW → NCHW
        return padded.astype(np.float32)
    
    def detect(self, img):
        """DB-Net 文字检测"""
        input_tensor = self.preprocess(img, 960, 960, self.det_mean, self.det_std)
        
        outputs = self.det_session.run(None, {"x": input_tensor})
        prob_map = outputs[0]  # [1, 1, H, W]
        
        # DB后处理: 二值化 → 轮廓 → 文本框
        # ... 同前述C++逻辑 ...
        return text_boxes
    
    def recognize(self, img_crop):
        """CRNN 文字识别"""
        input_tensor = self.preprocess(img_crop, 320, 48, self.rec_mean, self.rec_std)
        
        outputs = self.rec_session.run(None, {"x": input_tensor})
        probs = outputs[0]  # [T, 1, num_classes]
        
        # CTC贪心解码
        # ... 同前述C++逻辑 ...
        return recognized_text, confidence
    
    def ocr(self, img):
        """完整OCR流水线: 检测 → 识别 → 纠错"""
        boxes = self.detect(img)
        results = []
        
        for box in boxes:
            # 裁剪文字区域
            crop = self.crop_region(img, box)
            
            # 方向分类 (可选, 调用AngleNet)
            # angle = self.classify_angle(crop)
            
            # 文字识别
            text, score = self.recognize(crop)
            
            # 纠错
            text = self.correct(text)
            
            results.append({"text": text, "score": score, "box": box})
        
        return results
    
    def correct(self, text):
        """OCR结果纠错"""
        # 过滤字符
        filter_chars = set('_|\\/=[]【】\"\',.=-~!()<>{}@#$%^&*')
        text = ''.join(c for c in text if c not in filter_chars)
        # 去首尾空白
        text = text.strip()
        return text
```

---

## 七、关键参数速查表

| 参数名 | 值 | 所属模块 | 说明 |
|--------|-----|----------|------|
| DB输入尺寸 | 960×960 | 检测 | 文字区域检测输入 |
| DB阈值(binary) | 0.3 | 检测 | 概率图二值化阈值 |
| DB框阈值(box_thresh) | 0.6 | 检测 | 文本框置信度过滤 |
| DB膨胀比(unclip) | 1.5 | 检测 | 文本框膨胀系数 |
| DB均值 | [0.485, 0.456, 0.406] | 检测 | 归一化均值 |
| DB标准差 | [0.229, 0.224, 0.225] | 检测 | 归一化标准差 |
| CLS输入尺寸 | 48×192 | 方向分类 | 文字方向检测输入 |
| CLS分类数 | 2 | 方向分类 | 0° / 180° |
| CLS均值/标准差 | [0.5, 0.5, 0.5] | 方向分类 | 归一化参数 |
| CRNN输入高度 | 48 | 识别 | 识别输入固定高度 |
| CRNN输入宽度 | ≤320 | 识别 | 识别输入动态宽度 |
| CRNN均值/标准差 | [0.5, 0.5, 0.5] | 识别 | 归一化参数 |
| CTC空白符索引 | 0 | 识别 | blank字符位置 |
| 字符集大小 | ~6623 | 识别 | ppocr_keys_v1.txt行数 |
| 缩放插值方式 | cv::INTER_LINEAR | 预处理 | 图像缩放算法 |
| screen capture | Windows GDI BitBlt | 截图 | 屏幕捕捉方式 |
| GoldThreshold | 5 | 配置 | 白金价格高亮阈值 |

---

## 八、数据流格式定义

### 文本框输出格式
```
TextBox[索引](+padding)[score(置信度),[x:左上X, y:左上Y], [x:右上X, y:右上Y], 
[x:右下X, y:右下Y], [x:左下X, y:左下Y]]
```

### 文字识别输出格式
```
textScores[索引]{识别文字内容}
textLine[索引](识别文字内容)
```

### 角度分类输出格式
```
angle[索引][index(类别0/1), score(置信度), time(耗时ms)]
```

### 缩放参数格式
```
ScaleParam(sw:源宽, sh:源高, dw:目标宽, dh:目标高, 缩放比例X, 缩放比例Y)
```

---

*文档基于 WarframeMonitor v1.0 二进制逆向分析生成，模型参数基于PP-OCRv3官方标准规格。*