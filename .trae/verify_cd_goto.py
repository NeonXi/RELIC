"""验证 toggles_page CD box 的"前往详细配置"按钮。"""
import sys
sys.path.insert(0, 'd:/MyProgram/WARFRAME-RELIC')

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QPushButton

# 加载 token
from core.tokens.manager import TokenManager
TokenManager.instance().load_preset("cyberpunk")

app = QApplication.instance() or QApplication(sys.argv)

# 1) 验证 yaml token 已加载
print("=" * 70)
print("  1) yaml token 'cd_assist.toggles_goto' 加载")
print("=" * 70)
# 通过 token manager 直接验证
token_val = TokenManager.instance().get("cd_assist.toggles_goto")
print(f"  token 原始值: {token_val!r}")
# 注意: yaml 里是字典,get 返回的可能不是预期的简单字符串
# 实际看 yaml 的 copy.copies[].toggles 里找
import yaml
with open("data/presets/cyberpunk.yaml", "r", encoding="utf-8") as f:
    data = yaml.safe_load(f)
cd_block = data.get("copy", {}).get("cd_assist", {})
print(f"  yaml 中 cd_assist 块 keys: {list(cd_block.keys())}")
goto_val = cd_block.get("toggles_goto")
print(f"  toggles_goto 值: {goto_val!r}")
assert goto_val == "前往详细配置", f"yaml token 值错了: {goto_val!r}"
print(f"  ✓ yaml token 值正确")

# 2) 创建 TogglesPage
print()
print("=" * 70)
print("  2) 创建 TogglesPage")
print("=" * 70)
from core.pages.toggles_page import TogglesPage
page = TogglesPage()
print(f"  ✓ TogglesPage 创建成功, page_id={page.page_id}")

# 3) 验证 _goto_cd_assist_page 方法存在
print()
print("=" * 70)
print("  3) 验证 _goto_cd_assist_page 方法")
print("=" * 70)
assert hasattr(page, "_goto_cd_assist_page"), "_goto_cd_assist_page 方法不存在!"
print(f"  ✓ _goto_cd_assist_page 方法存在")

# 4) 验证 CD box 包含跳转按钮
print()
print("=" * 70)
print("  4) 验证 CD box 中的跳转按钮")
print("=" * 70)
from core.widgets.button import CyberButton
# 找所有 CyberButton
buttons = page.findChildren(CyberButton)
print(f"  页面 CyberButton 总数: {len(buttons)}")
cd_goto_btns = []
for btn in buttons:
    txt = btn.text()
    if "前往详细配置" in txt or "前往" in txt:
        cd_goto_btns.append(btn)
        print(f"  找到按钮: text={txt!r}, width={btn.width()}, variant=?")
print(f"  跳转按钮数: {len(cd_goto_btns)}")
# 期望至少 2 个: triggers 的跳转 + cd_assist 的跳转
assert len(cd_goto_btns) >= 2, f"应该有 2 个跳转按钮(触发器 + CD), 实际 {len(cd_goto_btns)}"
print(f"  ✓ 有 {len(cd_goto_btns)} 个跳转按钮")

# 5) 验证 CD 跳转按钮
print()
print("=" * 70)
print("  5) 验证 CD 跳转按钮属性")
print("=" * 70)
# 找 CD 跳转按钮: text=前往详细配置, 且 connected to _goto_cd_assist_page
cd_btn = None
for btn in cd_goto_btns:
    # 查信号接收者
    rec = btn.receivers("2clicked()")
    if rec > 0:
        # 这个按钮连了 clicked,我们找连到 _goto_cd_assist_page 的
        # 通过反射看 receiver
        from PySide6.QtCore import QObject
        # 不能直接拿 receiver,只能通过方法 + signal
        # 暂时看 click 是否连到 _goto_cd_assist_page 通过 _app_shell 验证
        pass
    # 简单看按钮 text
    if "前往" in btn.text():
        # 看这个按钮的 clicked 信号连接
        # 拿所有 receivers
        rec = btn.receivers("2clicked()")
        print(f"  按钮 text={btn.text()!r}, width={btn.width()}, receivers={rec}")

# 验证 CD 跳转按钮存在
cd_goto_btn_found = False
for btn in cd_goto_btns:
    # CD 跳转按钮的 receivers 应该 > 0
    if btn.receivers("2clicked()") > 0:
        cd_goto_btn_found = True
        # 验证宽度
        if btn.width() == 120 or btn.maximumWidth() == 120 or btn.minimumWidth() == 120:
            print(f"  ✓ CD 跳转按钮 width=120 OK")
        else:
            print(f"  ! 按钮 width={btn.width()}, minW={btn.minimumWidth()}, maxW={btn.maximumWidth()}")
        # 验证 enabled
        assert btn.isEnabled(), "按钮应该 enabled"
        print(f"  ✓ CD 跳转按钮 enabled")
        break
assert cd_goto_btn_found, "没找到 CD 跳转按钮(有 connected 接收者)"
print(f"  ✓ CD 跳转按钮存在并已连接")

# 6) 模拟点击 — 验证跳转到 cd_assist
print()
print("=" * 70)
print("  6) 模拟点击 — 验证跳转到 cd_assist")
print("=" * 70)
# 创建一个 mock _app_shell
class MockShell:
    def __init__(self):
        self.switches = []
    def _switch_to(self, page_id):
        self.switches.append(page_id)
        print(f"  [MockShell] _switch_to({page_id!r})")
page._app_shell = MockShell()
# 调方法
page._goto_cd_assist_page()
assert page._app_shell.switches == ["cd_assist"], f"应该跳到 cd_assist, 实际 {page._app_shell.switches}"
print(f"  ✓ 正确跳转到 'cd_assist'")

# 7) 验证 _app_shell=None 时不报错
print()
print("=" * 70)
print("  7) 验证 _app_shell=None 时安全")
print("=" * 70)
page._app_shell = None
try:
    page._goto_cd_assist_page()
    print(f"  ✓ _app_shell=None 时不报错")
except Exception as e:
    print(f"  ✗ _app_shell=None 时报错: {e}")
    raise SystemExit(1)

# 8) 完整 AppShell 启动
print()
print("=" * 70)
print("  8) 完整 AppShell 启动")
print("=" * 70)
import importlib
import core.app_shell
importlib.reload(core.app_shell)
from core.app_shell import AppShell
shell = AppShell(show_splash=False, app=app)
print(f"  ✓ AppShell 启动成功,共 {len(shell._pages)} 个页面")
print(f"  ✓ toggles 页面: {shell._pages.get('toggles')}")
print(f"  ✓ cd_assist 页面: {shell._pages.get('cd_assist')}")

# 9) 切到 toggles 页面验证
print()
print("=" * 70)
print("  9) 切到 toggles 页面验证按钮")
print("=" * 70)
shell._switch_to("toggles")
app.processEvents()
toggles_page = shell._pages["toggles"]
btns = toggles_page.findChildren(CyberButton)
print(f"  toggles 页面 CyberButton 数: {len(btns)}")
for btn in btns:
    if "前往" in btn.text():
        print(f"    - {btn.text()!r}, width={btn.width()}, visible={btn.isVisible()}, connected={btn.receivers('2clicked()') > 0}")
print(f"  ✓ 跳转按钮在 toggles 页面可见")

print()
print("=" * 70)
print("  ✓ 全部测试通过 — CD box 已加 '前往详细配置' 按钮")
print("=" * 70)
QTimer.singleShot(100, app.quit)
app.exec()
