"""找星球中文翻译 — game_translations 里 planet 在哪?或者是别的地方?"""
import sqlite3
db = sqlite3.connect(r"d:\MyProgram\WARFRAME-RELIC\data\warframe.db")
cur = db.cursor()

# 查 game_translations 里所有 'category' 是 Planet 或 Locations
cur.execute("""SELECT DISTINCT category FROM game_translations ORDER BY category""")
print("=== game_translations 全部 category ===")
for r in cur.fetchall():
    print(" ", r)

# Mars / Mercury 翻译在哪?
print("\n=== 找 Mars/Mercury 翻译 ===")
for kw in ("Mars", "Mercury", "Höllvania", "Zariman", "Duviri", "Lua", "Deimos"):
    cur.execute("""SELECT key, en, zh FROM game_translations
                   WHERE en=? OR key LIKE ?""", (kw, f"%{kw}%"))
    rows = cur.fetchall()
    print(f"\n  搜索 '{kw}':")
    for r in rows[:5]:
        print(f"    {r[0]:60s}  en='{r[1]}'  zh='{r[2]}'")

# 找 星球 类目在哪
cur.execute("""SELECT key, en, zh FROM game_translations
               WHERE LOWER(en) IN ('mars','mercury','earth','venus','jupiter','saturn',
                                    'uranus','neptune','pluto','ceres','eris','sedna',
                                    'europa','void','phobos','deimos','lua',
                                    'kuva fortress','sanctuary','veil proxima',
                                    'zariman','duviri','höllvania','dark refractory, deimos')""")
print("\n=== Planet 英文名直接搜 ===")
for r in cur.fetchall():
    print(f"  {r[0]:65s}  en='{r[1]}'  zh='{r[2]}'")

# game_translations 找 H\303\266llvania / H\303\266lle
print("\n=== 找 H\u00f6llvania 编码 ===")
cur.execute("SELECT key, en, zh FROM game_translations WHERE en LIKE '%llvania%'")
for r in cur.fetchall():
    print(" ", r)
cur.execute("SELECT key, en, zh FROM game_translations WHERE zh LIKE '%霍尔%'")
print("\n=== zh 含 '霍尔' ===")
for r in cur.fetchall():
    print(" ", r)

db.close()
