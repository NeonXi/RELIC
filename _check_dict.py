"""检查字典文件编码"""
f = open('WarframeMonitor_v1.0/models/ppocr_keys_v1.txt', 'rb')
raw = f.read()
f.close()

print('=== 文件大小 & 行数 ===')
print(f'总字节: {len(raw)}')
lines = raw.split(b'\n')
print(f'总行数: {len(lines)} (含空行)')

print('\n=== 前15行（逐行分析）===')
for i, line in enumerate(lines[:15]):
    try:
        ch = line.decode('utf-8')
        print(f'  [{i:4d}] bytes={len(line):3d} | hex={line.hex()[:20]} | char="{ch}"')
    except:
        print(f'  [{i:4d}] bytes={len(line):3d} | DECODE_ERROR | raw={line.hex()[:30]}')

print('\n=== 关键索引检查 ===')
# 检查索引 0, 1, 2 应该是什么
for idx in [0, 1, 2, 10, 100, 500, 1000, 1221, 3539, 4902]:
    if idx < len(lines):
        try:
            ch = lines[idx].decode('utf-8')
            print(f'  索引[{idx:4d}] = "{ch}"')
        except:
            print(f'  索引[{idx:4d}] = <DECODE_ERROR>')

# 检查是否有 BOM
if raw[:3] == b'\xef\xbb\xbf':
    print('\n⚠ 发现 UTF-8 BOM!')
else:
    print(f'\n前3字节: {raw[:3].hex()} (无BOM)')
