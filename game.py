# -*- coding: utf-8 -*-
"""
库尔斯克会战·浪尖战场 —— 像素风 2D 坦克对战游戏
Python + Pygame 实现（对应《坦克对战游戏技术文档》v1.0）

操作：鼠标左键点击 移动（炮口随移动方向转向），右键点击 开火
自检：python game.py --selftest
"""

import array
import math
import os
import random
import sys
from collections import deque

import pygame

# ------------------------------------------------------------------
# 常量配置
# ------------------------------------------------------------------
TILE = 24
COLS, ROWS = 40, 20
MAP_W, MAP_H = COLS * TILE, ROWS * TILE        # 960 × 480（宽高比 2:1）
WIN_W, WIN_H = 1440, 720                        # 窗口尺寸（逻辑画面 1.5 倍）
SCALE = WIN_W / MAP_W
FPS = 60

STATE_HOME, STATE_PLAY, STATE_VICTORY, STATE_DEFEAT = 0, 1, 2, 3

WHITE = (240, 240, 235)
DARK = (24, 22, 20)
GOLD = (255, 202, 64)
RED = (224, 66, 52)
GREEN = (92, 200, 92)
YELLOW = (255, 220, 90)
GRAY_TXT = (180, 178, 170)

PLAYER_PAL = ((64, 132, 64), (36, 82, 36), (128, 190, 118))    # 车体 / 暗 / 亮
ENEMY_PAL = ((150, 62, 58), (94, 36, 34), (196, 124, 112))

SAND_COLORS = [(200, 162, 86), (184, 147, 74), (196, 158, 84), (176, 140, 70)]

CFG = dict(
    p_hp=100, p_speed=120, p_dmg=34, p_fire_cd=0.4,
    ammo_max=30, ammo_regen=4.0,
    e_hp=100, e_speed=80, e_dmg=25, e_fire_cd=1.8, e_count=5,
    b_speed=360,
)

DIRS = {'up': (0, -1), 'down': (0, 1), 'left': (-1, 0), 'right': (1, 0)}

PLAYER_SPAWN = (2, 17)
ENEMY_SPAWNS = [(37, 2), (32, 2), (6, 2), (37, 10), (20, 2)]

# LZH 障碍字形：7 列 × 6 行 / 字距 4 格，从左到右 L → Z → H（L 顶部无横杠）
LZH_MASK = {
    "L": ("1000000", "1000000", "1000000", "1000000", "1000000", "1111111"),
    "Z": ("1111111", "0000001", "0000010", "0000100", "0001000", "1111111"),
    "H": ("1000001", "1000001", "1111111", "1000001", "1000001", "1000001"),
}
LZH_ORIGIN = {"L": (6, 7), "Z": (17, 7), "H": (28, 7)}

FONT_PATHS = [
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\simsun.ttc",
]

_font_cache = {}


def get_font(size):
    """加载中文字体（优先微软雅黑/黑体，兼容打包后的 exe）"""
    if size in _font_cache:
        return _font_cache[size]
    f = None
    for p in FONT_PATHS:
        if os.path.exists(p):
            try:
                f = pygame.font.Font(p, size)
                break
            except Exception:
                pass
    if f is None:
        f = pygame.font.SysFont("microsoftyahei,simhei,dengxian,simsun", size)
    _font_cache[size] = f
    return f


# ------------------------------------------------------------------
# 音效系统：Web Audio 思路 → pygame 程序化合成（无外部素材）
# ------------------------------------------------------------------
class SFX:
    def __init__(self):
        self.sounds = {}
        self.ok = False
        try:
            if pygame.mixer.get_init() is None:
                pygame.mixer.init(22050, -16, 2, 512)
            self.ok = pygame.mixer.get_init() is not None
        except Exception:
            self.ok = False
        if self.ok:
            try:
                self._build()
            except Exception:
                self.ok = False

    # ---- 波形生成（返回 float 样本列表）----
    def _tone(self, freq, dur, wave="square", vol=1.0, slide=None):
        rate = pygame.mixer.get_init()[0]
        n = max(1, int(rate * dur))
        out = []
        for i in range(n):
            f = freq if slide is None else freq + (slide - freq) * (i / (n - 1))
            ph = (i / rate * f) % 1.0
            if wave == "square":
                v = 1.0 if ph < 0.5 else -1.0
            elif wave == "saw":
                v = 2.0 * ph - 1.0
            elif wave == "sine":
                v = math.sin(2 * math.pi * ph)
            else:  # noise
                v = random.uniform(-1, 1)
            a = min(1.0, i / (rate * 0.004))          # 快速起音
            d = 1.0 - i / n                            # 线性衰减
            out.append(v * a * d * vol)
        return out

    def _silence(self, dur):
        rate = pygame.mixer.get_init()[0]
        return [0.0] * int(rate * dur)

    def _mix(self, *layers):
        n = max(len(l) for l in layers)
        return [sum(l[i] for l in layers if i < len(l)) for i in range(n)]

    def _to_sound(self, samples, vol):
        buf = array.array('h')
        for s in samples:
            v = int(max(-1.0, min(1.0, s * vol)) * 32767)
            buf.append(v)
            buf.append(v)                              # 双声道
        return pygame.mixer.Sound(buffer=buf.tobytes())

    def _build(self):
        # 胜利：C 大调上行琶音 C5→E5→G5→C6 + 尾部三和弦长音
        seq = []
        for f in (523.25, 659.25, 783.99, 1046.5):
            seq += self._tone(f, 0.12, "square", 1.0)
            seq += self._silence(0.02)
        chord = self._mix(self._tone(523.25, 0.6, "square", 0.8),
                          self._tone(659.25, 0.6, "square", 0.8),
                          self._tone(783.99, 0.6, "square", 0.8),
                          self._tone(1046.5, 0.6, "square", 0.6))
        self.sounds['victory'] = self._to_sound(seq + chord, 0.16)

        # 失败：下行滑音 400→120Hz 锯齿波 + 低沉噪声
        sweep = self._tone(400, 0.8, "saw", 1.0, slide=120)
        noise = self._tone(0, 0.8, "noise", 0.4)
        self.sounds['defeat'] = self._to_sound(self._mix(sweep, noise), 0.22)

        # 发射：短促方波 + 噪声爆破
        shot = self._mix(self._tone(220, 0.06, "square", 0.9),
                         self._tone(0, 0.035, "noise", 0.7))
        self.sounds['shoot'] = self._to_sound(shot, 0.22)

        # 击中：短噪声
        self.sounds['hit'] = self._to_sound(self._tone(0, 0.06, "noise", 1.0), 0.30)

        # 爆炸：噪声 + 低频闷响
        boom = self._mix(self._tone(0, 0.28, "noise", 1.0),
                         self._tone(70, 0.12, "sine", 1.0))
        self.sounds['explode'] = self._to_sound(boom, 0.55)

        # 空仓"咔哒"
        click = self._tone(1200, 0.012, "square", 1.0) + \
            self._silence(0.012) + self._tone(1200, 0.012, "square", 1.0)
        self.sounds['click'] = self._to_sound(click, 0.18)

    def play(self, name):
        if self.ok and name in self.sounds:
            self.sounds[name].play()


SFX_MGR = None  # 在 main() 中初始化


# ------------------------------------------------------------------
# 网格与障碍
# ------------------------------------------------------------------
def build_grid():
    g = [[False] * COLS for _ in range(ROWS)]
    for i in range(COLS):                       # 边界砖墙
        g[0][i] = g[ROWS - 1][i] = True
    for j in range(ROWS):
        g[j][0] = g[j][COLS - 1] = True
    for ch, (ox, oy) in LZH_ORIGIN.items():     # LZH 字形障碍
        rows_ = LZH_MASK[ch]
        for r in range(len(rows_)):
            for c in range(len(rows_[r])):
                if rows_[r][c] == '1':
                    g[oy + r][ox + c] = True
    return g


GRID = None  # 在 main() 中初始化（全局共享）


def rect_hits_grid(rect):
    """AABB 与障碍网格碰撞检测"""
    x0 = max(0, rect.left // TILE)
    x1 = min(COLS - 1, (rect.right - 1) // TILE)
    y0 = max(0, rect.top // TILE)
    y1 = min(ROWS - 1, (rect.bottom - 1) // TILE)
    for cy in range(y0, y1 + 1):
        for cx in range(x0, x1 + 1):
            if GRID[cy][cx]:
                return True
    return False


def line_of_sight(x1, y1, x2, y2):
    """视线检测：沿连线采样，遇到障碍格即被遮挡"""
    d = math.hypot(x2 - x1, y2 - y1)
    steps = int(d // (TILE // 2)) + 1
    for i in range(steps + 1):
        t = i / steps
        x = x1 + (x2 - x1) * t
        y = y1 + (y2 - y1) * t
        if GRID[int(y // TILE)][int(x // TILE)]:
            return False
    return True


# ------------------------------------------------------------------
# 实体
# ------------------------------------------------------------------
class Tank:
    def __init__(self, cell, palette, is_player):
        self.rect = pygame.Rect(cell[0] * TILE + 1, cell[1] * TILE + 1,
                                TILE - 2, TILE - 2)
        self.pal = palette
        self.is_player = is_player
        self.dir = 'up' if is_player else 'down'
        self.angle = 0.0        # 玩家朝向角（度，0=上，顺时针，炮口随移动方向）
        self.target = None      # 玩家鼠标左键移动目标 (x, y)
        self.max_hp = CFG['p_hp'] if is_player else CFG['e_hp']
        self.hp = self.max_hp
        self.alive = True
        self.flash = 0.0        # 受击闪白
        self.muzzle = 0.0       # 炮口闪光
        self.dust_t = 0.0       # 履带扬尘计时
        self.fire_cd = 0.0
        self.shield = 0.0       # 出生护盾（免伤）
        # --- AI ---
        self.state = 'PATROL'
        self.ai_t = random.uniform(0, 0.2)
        self.patrol_t = 0.0
        self.path = None          # BFS 追踪路径（格坐标列表）
        self.path_cell = None     # 计算路径时的玩家格（用于失效判断）
        self.blocked = False


class Bullet:
    def __init__(self, x, y, vx, vy, owner, dmg):
        self.rect = pygame.Rect(int(x) - 2, int(y) - 2, 5, 5)
        self.vx = vx
        self.vy = vy
        self.owner = owner      # 'p' / 'e'
        self.dmg = dmg


class Particle:
    __slots__ = ('x', 'y', 'vx', 'vy', 'size', 'color', 'life',
                 'max_life', 'gravity', 'floor')

    def __init__(self, x, y, vx, vy, size, color, life, gravity=0, floor=None):
        self.x, self.y, self.vx, self.vy = x, y, vx, vy
        self.size, self.color = size, color
        self.life = self.max_life = life
        self.gravity = gravity
        self.floor = floor


class Button:
    def __init__(self, rect, text, font):
        self.rect = pygame.Rect(rect)
        self.text = text
        self.font = font

    def hit(self, mouse):
        return self.rect.collidepoint(mouse)

    def draw(self, surf, mouse):
        hovered = self.hit(mouse)
        color = (105, 105, 122) if hovered else (72, 72, 86)
        pygame.draw.rect(surf, color, self.rect, border_radius=6)
        pygame.draw.rect(surf, (32, 32, 40) if not hovered else GOLD,
                         self.rect, 2, border_radius=6)
        label = self.font.render(self.text, True, WHITE)
        surf.blit(label, label.get_rect(center=self.rect.center))


# ------------------------------------------------------------------
# 绘制：像素风贴图（代码绘制，类迷你世界方块颗粒感）
# ------------------------------------------------------------------
def draw_rock_tile(surf, px, py):
    pygame.draw.rect(surf, (112, 112, 120), (px, py, TILE, TILE))
    pygame.draw.rect(surf, (74, 74, 80), (px, py, TILE, TILE), 2)
    pygame.draw.rect(surf, (142, 142, 150), (px + 2, py + 2, TILE - 4, 3))
    for _ in range(6):
        s = random.randint(3, 6)
        x = px + random.randint(2, TILE - s - 2)
        y = py + random.randint(3, TILE - s - 2)
        c = random.choice([(96, 96, 102), (128, 128, 136), (88, 88, 94)])
        pygame.draw.rect(surf, c, (x, y, s, s))


def draw_tank_at(surf, rect, direction, pal, flash=0.0, muzzle=0.0):
    x, y, w, h = rect.x, rect.y, rect.w, rect.h
    body, dark, light = pal
    dark2 = (dark[0] // 2, dark[1] // 2, dark[2] // 2)

    if direction in ('up', 'down'):
        pygame.draw.rect(surf, dark, (x, y - 1, 6, h + 2))          # 左履带
        pygame.draw.rect(surf, dark, (x + w - 6, y - 1, 6, h + 2))  # 右履带
        for ty in range(y + 2, y + h - 3, 6):                        # 履带链节
            pygame.draw.rect(surf, dark2, (x + 1, ty, 4, 3))
            pygame.draw.rect(surf, dark2, (x + w - 5, ty, 4, 3))
        pygame.draw.rect(surf, body, (x + 6, y + 2, w - 12, h - 4))  # 车体
        pygame.draw.rect(surf, light, (x + 7, y + 3, w - 14, 3))     # 高光
    else:
        pygame.draw.rect(surf, dark, (x - 1, y, w + 2, 6))
        pygame.draw.rect(surf, dark, (x - 1, y + h - 6, w + 2, 6))
        for tx in range(x + 2, x + w - 3, 6):
            pygame.draw.rect(surf, dark2, (tx, y + 1, 3, 4))
            pygame.draw.rect(surf, dark2, (tx, y + h - 5, 3, 4))
        pygame.draw.rect(surf, body, (x + 2, y + 6, w - 4, h - 12))
        pygame.draw.rect(surf, light, (x + 3, y + 7, 3, h - 14))

    cx, cy = rect.center
    pygame.draw.rect(surf, light, (cx - 6, cy - 6, 12, 12))          # 炮塔
    pygame.draw.rect(surf, dark, (cx - 6, cy - 6, 12, 12), 2)

    if direction == 'up':                                            # 炮管
        br = (cx - 2, y - 6, 4, h // 2 + 6)
    elif direction == 'down':
        br = (cx - 2, cy, 4, h // 2 + 6)
    elif direction == 'left':
        br = (x - 6, cy - 2, w // 2 + 6, 4)
    else:
        br = (cx, cy - 2, w // 2 + 6, 4)
    pygame.draw.rect(surf, dark, br)

    if muzzle > 0:                                                   # 炮口闪光
        dx, dy = DIRS[direction]
        ex, ey = cx + dx * (w // 2 + 7), cy + dy * (h // 2 + 7)
        pygame.draw.rect(surf, YELLOW, (ex - 4, ey - 4, 8, 8))
        pygame.draw.rect(surf, WHITE, (ex - 2, ey - 2, 4, 4))

    if flash > 0:                                                    # 受击白闪
        s = pygame.Surface((w, h), pygame.SRCALPHA)
        s.fill((255, 255, 255, 150))
        surf.blit(s, (x, y))


def draw_player_tank(surf, rect, angle, pal, flash=0.0, muzzle=0.0):
    """玩家坦克：任意角度旋转渲染（angle 单位度，0=上，顺时针，炮口随移动方向）"""
    S = 48
    base = pygame.Surface((S, S), pygame.SRCALPHA)
    cx = cy = S // 2
    x, y, w, h = cx - 11, cy - 11, 22, 22
    body, dark, light = pal
    dark2 = (dark[0] // 2, dark[1] // 2, dark[2] // 2)
    pygame.draw.rect(base, dark, (x, y - 1, 6, h + 2))              # 左履带
    pygame.draw.rect(base, dark, (x + w - 6, y - 1, 6, h + 2))      # 右履带
    for ty in range(y + 2, y + h - 3, 6):                           # 履带链节
        pygame.draw.rect(base, dark2, (x + 1, ty, 4, 3))
        pygame.draw.rect(base, dark2, (x + w - 5, ty, 4, 3))
    pygame.draw.rect(base, body, (x + 6, y + 2, w - 12, h - 4))     # 车体
    pygame.draw.rect(base, light, (x + 7, y + 3, w - 14, 3))        # 高光
    pygame.draw.rect(base, light, (cx - 6, cy - 6, 12, 12))         # 炮塔
    pygame.draw.rect(base, dark, (cx - 6, cy - 6, 12, 12), 2)
    pygame.draw.rect(base, dark, (cx - 2, y - 6, 4, h // 2 + 6))    # 炮管朝上
    if muzzle > 0:                                                  # 炮口闪光
        pygame.draw.rect(base, YELLOW, (cx - 4, y - 13, 8, 8))
        pygame.draw.rect(base, WHITE, (cx - 2, y - 11, 4, 4))
    if flash > 0:                                                   # 受击白闪
        s = pygame.Surface((w, h), pygame.SRCALPHA)
        s.fill((255, 255, 255, 150))
        base.blit(s, (x, y))
    rot = pygame.transform.rotate(base, -angle)                     # 顺时针旋转
    surf.blit(rot, rot.get_rect(center=rect.center))


def draw_text_outline(surf, text, font, pos, color, outline=(20, 18, 16)):
    label = font.render(text, True, color)
    ol = font.render(text, True, outline)
    x, y = pos
    for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2)):
        surf.blit(ol, (x + dx - label.get_width() // 2,
                       y + dy - label.get_height() // 2))
    surf.blit(label, (x - label.get_width() // 2, y - label.get_height() // 2))


# ------------------------------------------------------------------
# 游戏主类
# ------------------------------------------------------------------
class Game:
    def __init__(self):
        self.main = pygame.Surface((MAP_W, MAP_H))
        self.mouse = (0, 0)
        self.state = STATE_HOME
        self.state_t = 0.0
        self.shake_t = 0.0
        self._build_static()
        self._build_buttons()
        self.reset_world()

    # ---------- 静态资源 ----------
    def _build_static(self):
        # 地面：沙土方块 + 4×4 子像素颗粒（迷你世界质感）
        bg = pygame.Surface((MAP_W, MAP_H))
        for cy in range(ROWS):
            for cx in range(COLS):
                base = random.choice(SAND_COLORS)
                pygame.draw.rect(bg, base, (cx * TILE, cy * TILE, TILE, TILE))
                sub = TILE // 4
                for i in range(4):
                    for j in range(4):
                        if random.random() < 0.35:
                            c = tuple(max(0, min(255, v + random.randint(-14, 14)))
                                      for v in base)
                            pygame.draw.rect(bg, c,
                                             (cx * TILE + i * sub, cy * TILE + j * sub,
                                              sub, sub))
        # 底图水印：平铺半透明"浪尖战场"
        wm = get_font(28).render("浪尖战场", True, (255, 255, 255))
        wm = pygame.transform.rotate(wm, -30)
        wm.set_alpha(30)
        yy = -60
        row = 0
        while yy < MAP_H + 60:
            xx = -80 + (row % 2) * 80
            while xx < MAP_W + 80:
                bg.blit(wm, (xx, yy))
                xx += 160
            yy += 80
            row += 1
        self.bg = bg

        # 障碍层：边界砖墙 + LZH 岩石
        obs = pygame.Surface((MAP_W, MAP_H), pygame.SRCALPHA)
        for cy in range(ROWS):
            for cx in range(COLS):
                if GRID[cy][cx]:
                    draw_rock_tile(obs, cx * TILE, cy * TILE)
        self.obs = obs

        # HUD 半透明条
        hud = pygame.Surface((MAP_W, 32), pygame.SRCALPHA)
        hud.fill((0, 0, 0, 150))
        self.hud_bar = hud

    def _build_buttons(self):
        f20 = get_font(20)
        f22 = get_font(22)
        self.btn_start = Button((390, 272, 180, 54), "开始游戏", f22)
        self.btn_home_d = Button((300, 288, 160, 48), "返回主页", f20)   # 失败弹窗
        self.btn_retry = Button((500, 288, 160, 48), "重新挑战", f20)
        self.btn_again = Button((300, 330, 160, 48), "再来一局", f20)    # 胜利横幅
        self.btn_home_v = Button((500, 330, 160, 48), "返回主页", f20)

    # ---------- 世界重置 ----------
    def reset_world(self):
        self.player = Tank(PLAYER_SPAWN, PLAYER_PAL, True)
        self.player.shield = 3.0                     # 出生 3 秒护盾
        self.enemies = [Tank(c, ENEMY_PAL, False) for c in ENEMY_SPAWNS]
        self.tanks = [self.player] + self.enemies
        self.bullets = []
        self.particles = []
        self.confetti = []
        self.kills = 0
        self.ammo = CFG['ammo_max']
        self.regen_t = 0.0
        self.shake_t = 0.0
        self.ammo_flash = 0.0
        self.pending_state = None
        self.pending_t = 0.0
        self.state_t = 0.0

    def start_game(self):
        self.reset_world()
        self._set_state(STATE_PLAY)

    def to_home(self):
        self._set_state(STATE_HOME)

    def _set_state(self, s):
        self.state = s
        self.state_t = 0.0
        if s == STATE_VICTORY:
            SFX_MGR.play('victory')
        elif s == STATE_DEFEAT:
            SFX_MGR.play('defeat')

    # ---------- 输入 ----------
    def set_mouse(self, pos):
        self.mouse = (pos[0] / SCALE, pos[1] / SCALE)

    def click(self):
        m = self.mouse
        if self.state == STATE_HOME:
            if self.btn_start.hit(m):
                self.start_game()
        elif self.state == STATE_DEFEAT:
            if self.btn_home_d.hit(m):
                self.to_home()
            elif self.btn_retry.hit(m):
                self.start_game()
        elif self.state == STATE_VICTORY and self.state_t > 3:
            if self.btn_again.hit(m):
                self.start_game()
            elif self.btn_home_v.hit(m):
                self.to_home()

    def player_fire(self):
        p = self.player
        if not p.alive or p.fire_cd > 0:
            return
        if self.ammo <= 0:
            SFX_MGR.play('click')
            self.ammo_flash = 0.5
            return
        self.ammo -= 1
        p.fire_cd = CFG['p_fire_cd']
        p.muzzle = 0.06
        self.spawn_bullet(p, 'p')
        SFX_MGR.play('shoot')

    def spawn_bullet(self, tank, owner):
        cx, cy = tank.rect.center
        if tank.is_player:                          # 玩家：沿炮口角度
            rad = math.radians(tank.angle)
            dx, dy = math.sin(rad), -math.cos(rad)
        else:                                       # 敌方：四向
            dx, dy = DIRS[tank.dir]
        bx = cx + dx * (tank.rect.w // 2 + 7)
        by = cy + dy * (tank.rect.h // 2 + 7)
        dmg = CFG['p_dmg'] if owner == 'p' else CFG['e_dmg']
        spd = CFG['b_speed']
        self.bullets.append(Bullet(bx, by, dx * spd, dy * spd, owner, dmg))

    def set_move_target(self, screen_pos):
        """鼠标左键：设定移动目标（屏幕坐标 → 地图坐标）"""
        x = max(TILE, min(MAP_W - TILE, screen_pos[0] / SCALE))
        y = max(TILE, min(MAP_H - TILE, screen_pos[1] / SCALE))
        self.player.target = (x, y)

    # ---------- 移动与碰撞 ----------
    def collide_any(self, rect, self_ent):
        if rect_hits_grid(rect):
            return True
        for t in self.tanks:
            if t is self_ent or not t.alive:
                continue
            if rect.colliderect(t.rect):
                return True
        return False

    def try_move(self, ent, dx, dy):
        moved = False
        r = ent.rect.move(dx, 0)
        if not self.collide_any(r, ent):
            ent.rect.x = r.x
            moved = True
        r = ent.rect.move(0, dy)
        if not self.collide_any(r, ent):
            ent.rect.y = r.y
            moved = True
        ent.blocked = not moved

    # ---------- 更新 ----------
    def update(self, dt):
        self.state_t += dt
        self.shake_t = max(0.0, self.shake_t - dt)
        self.ammo_flash = max(0.0, self.ammo_flash - dt)
        self.update_particles(dt)

        if self.state == STATE_PLAY:
            self.update_player(dt)
            self.update_enemies(dt)
            self.update_bullets(dt)
            # 弹药自动恢复：每 4 秒 +1
            self.regen_t += dt
            if self.regen_t >= CFG['ammo_regen']:
                self.regen_t -= CFG['ammo_regen']
                if self.ammo < CFG['ammo_max']:
                    self.ammo += 1
            # 延迟切场（让爆炸特效先播放）
            if self.pending_state is not None:
                self.pending_t -= dt
                if self.pending_t <= 0:
                    self._set_state(self.pending_state)
                    self.pending_state = None
        elif self.state == STATE_VICTORY:
            self.update_confetti(dt)

    def update_player(self, dt):
        p = self.player
        if not p.alive:
            return
        p.shield = max(0.0, p.shield - dt)
        p.fire_cd = max(0.0, p.fire_cd - dt)
        p.flash = max(0.0, p.flash - dt)
        p.muzzle = max(0.0, p.muzzle - dt)
        if p.target is None:
            return
        tx, ty = p.target
        cx, cy = p.rect.center
        dx, dy = tx - cx, ty - cy
        dist = math.hypot(dx, dy)
        if dist < 2:                                 # 已到达目标
            p.target = None
            return
        p.angle = math.degrees(math.atan2(dx, -dy)) % 360   # 炮口对齐移动方向
        step = CFG['p_speed'] * dt
        if dist <= step:
            mvx, mvy = dx, dy
            p.target = None
        else:
            mvx, mvy = dx / dist * step, dy / dist * step
        self.try_move(p, mvx, mvy)
        if p.blocked:                                # 完全受阻则停车
            p.target = None
            return
        p.dust_t -= dt
        if p.dust_t <= 0:
            self.spawn_dust(p)
            p.dust_t = 0.09

    def update_enemies(self, dt):
        for e in self.enemies:
            if not e.alive:
                continue
            e.fire_cd = max(0.0, e.fire_cd - dt)
            e.flash = max(0.0, e.flash - dt)
            e.muzzle = max(0.0, e.muzzle - dt)
            e.ai_t -= dt
            if e.ai_t <= 0:
                self.enemy_decide(e)
                e.ai_t = 0.2
            if e.state != 'ATTACK':
                self.enemy_follow_path(e, dt)

    def enemy_decide(self, e):
        p = self.player
        if not p.alive:                          # 玩家已亡：随机巡逻
            e.state = 'PATROL'
            e.path = None
            e.patrol_t -= 0.2
            if e.patrol_t <= 0 or e.blocked:
                e.dir = random.choice(list(DIRS))
                e.patrol_t = random.uniform(1.5, 3.0)
            return

        ex, ey = e.rect.center
        px, py = p.rect.center
        dist = math.hypot(px - ex, py - ey)
        e.dir = self.aim_dir(e)

        if (line_of_sight(ex, ey, px, py) and dist <= 300
                and self.can_hit_player(e)):     # 视线+对准+弹道无墙才开炮
            e.state = 'ATTACK'
            if e.fire_cd <= 0:
                if self.ally_in_fire_line(e):    # 隔着队友不打：绕开再打
                    e.state = 'CHASE'
                    e.path = None                # 重算路径避开队友
                else:
                    e.fire_cd = CFG['e_fire_cd']
                    e.muzzle = 0.06
                    self.spawn_bullet(e, 'e')
                    SFX_MGR.play('shoot')
            return

        # CHASE：BFS 寻路绕过障碍物逼近玩家
        e.state = 'CHASE'
        pcell = (int(p.rect.centerx // TILE), int(p.rect.centery // TILE))
        if e.path is None or e.path_cell != pcell or e.blocked:
            e.path = self.bfs_path(e, pcell)
            e.path_cell = pcell
        if e.path:
            return                               # 沿路径走（逐帧执行）
        if e.blocked:                            # 无路径可达（罕见）：脱困
            e.dir = self.escape_dir(e)
        else:
            e.dir = self.aim_dir(e)

    def enemy_follow_path(self, e, dt):
        """沿 BFS 路径逐帧移动；无路径时沿当前方向探测前进"""
        if e.path:
            while e.path:                        # 弹出已到达的路点
                wx = e.path[0][0] * TILE + TILE // 2
                wy = e.path[0][1] * TILE + TILE // 2
                if math.hypot(wx - e.rect.centerx,
                              wy - e.rect.centery) < 3:
                    e.path.pop(0)
                else:
                    break
            if e.path:                           # 朝下一路点行进
                wx = e.path[0][0] * TILE + TILE // 2
                wy = e.path[0][1] * TILE + TILE // 2
                dx = wx - e.rect.centerx
                dy = wy - e.rect.centery
                if abs(dx) >= abs(dy):
                    e.dir = 'right' if dx > 0 else 'left'
                else:
                    e.dir = 'down' if dy > 0 else 'up'
        dx, dy = DIRS[e.dir]
        step = CFG['e_speed'] * dt
        probe = e.rect.move(dx * step, dy * step)
        if self.collide_any(probe, e):
            e.blocked = True                     # 前方受阻，待下次决策绕行
        else:
            e.blocked = False
            self.try_move(e, dx * step, dy * step)

    def bfs_path(self, e, goal_cell):
        """BFS 最短路：避开障碍格与其他敌方坦克格，返回 下一格→目标 的格列表"""
        sx = int(e.rect.centerx // TILE)
        sy = int(e.rect.centery // TILE)
        blocked = {(int(o.rect.centerx // TILE), int(o.rect.centery // TILE))
                   for o in self.enemies if o is not e and o.alive}
        q = deque([(sx, sy)])
        prev = {(sx, sy): None}
        while q:
            cx, cy = q.popleft()
            if (cx, cy) == goal_cell:
                path = []
                cur = goal_cell
                while prev[cur] is not None:
                    path.append(cur)
                    cur = prev[cur]
                path.reverse()
                return path
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx, ny = cx + dx, cy + dy
                if (0 <= nx < COLS and 0 <= ny < ROWS and (nx, ny) not in prev
                        and not GRID[ny][nx]
                        and ((nx, ny) == goal_cell or (nx, ny) not in blocked)):
                    prev[(nx, ny)] = (cx, cy)
                    q.append((nx, ny))
        return None

    def dir_free(self, e, d):
        """方向 d 前方一小步是否可通行"""
        dx, dy = DIRS[d]
        probe = e.rect.move(dx * 4, dy * 4)
        return not self.collide_any(probe, e)

    def escape_dir(self, e):
        """被卡住时的脱困方向（优先选朝玩家侧的可行方向）"""
        px, py = self.player.rect.center
        ex, ey = e.rect.center
        dx, dy = px - ex, py - ey
        hx = 'right' if dx >= 0 else 'left'
        hy = 'down' if dy >= 0 else 'up'
        ox = 'left' if hx == 'right' else 'right'
        oy = 'up' if hy == 'down' else 'down'
        if abs(dx) >= abs(dy):
            cands = [hx, hy, ox, oy]
        else:
            cands = [hy, hx, oy, ox]
        for d in cands:
            if self.dir_free(e, d):
                return d
        return e.dir

    def can_hit_player(self, e):
        """炮轴是否对准玩家（偏移小于坦克宽）且弹道无墙（按炮弹 5×5 实体采样）"""
        cx, cy = e.rect.center
        px, py = self.player.rect.center
        dx, dy = DIRS[e.dir]
        if dx != 0:                              # 水平炮：需 y 对齐
            if abs(py - cy) > 12:
                return False
            limit = abs(px - cx)
        else:                                    # 垂直炮：需 x 对齐
            if abs(px - cx) > 12:
                return False
            limit = abs(py - cy)
        d = 14
        while d < limit:                         # 弹体逐步推进检测墙体
            r = pygame.Rect(int(cx + dx * d) - 2, int(cy + dy * d) - 2, 5, 5)
            if rect_hits_grid(r):
                return False                     # 墙挡在玩家之前
            d += 4
        return True

    def ally_in_fire_line(self, e):
        """己方坦克是否挡在炮线上（防止红坦克互相开炮）"""
        cx, cy = e.rect.center
        px, py = self.player.rect.center
        dx, dy = DIRS[e.dir]
        limit = min(340, math.hypot(px - cx, py - cy) + 20)
        d = 14
        while d < limit:
            x = cx + dx * d
            y = cy + dy * d
            if x < 0 or x >= MAP_W or y < 0 or y >= MAP_H:
                return False
            if GRID[int(y // TILE)][int(x // TILE)]:
                return False                     # 炮线先撞墙，无碍
            for o in self.enemies:
                if o is e or not o.alive:
                    continue
                if o.rect.collidepoint(x, y):
                    return True
            d += 6
        return False

    def aim_dir(self, e):
        px, py = self.player.rect.center
        ex, ey = e.rect.center
        dx, dy = px - ex, py - ey
        if abs(dx) >= abs(dy):
            return 'right' if dx > 0 else 'left'
        return 'down' if dy > 0 else 'up'

    def update_bullets(self, dt):
        for b in self.bullets[:]:
            b.rect.move_ip(b.vx * dt, b.vy * dt)
            r = b.rect
            if (r.right < 0 or r.left > MAP_W or r.bottom < 0 or r.top > MAP_H
                    or rect_hits_grid(r)):
                self.spawn_sparks(r.center, (150, 150, 150))
                self.bullets.remove(b)
                continue
            # 命中坦克
            hit = False
            for t in self.tanks:
                if not t.alive:
                    continue
                if b.owner == 'p' and t.is_player:
                    continue
                if b.owner == 'e' and not t.is_player:
                    continue
                if r.colliderect(t.rect):
                    self.damage(t, b.dmg)
                    self.spawn_sparks(r.center, t.pal[2])
                    hit = True
                    break
            if hit:
                self.bullets.remove(b)
        # 炮弹对撞抵消（彩蛋）
        for i in range(len(self.bullets)):
            for j in range(len(self.bullets) - 1, i, -1):
                b1, b2 = self.bullets[i], self.bullets[j]
                if b1.owner != b2.owner and b1.rect.colliderect(b2.rect):
                    self.spawn_sparks(b1.rect.center, YELLOW)
                    self.bullets.remove(b2)
                    self.bullets.remove(b1)
                    break

    def damage(self, t, dmg):
        if t.is_player and t.shield > 0:         # 出生护盾期间免伤
            self.spawn_sparks(t.rect.center, (120, 220, 255))
            return
        t.hp -= dmg
        t.flash = 0.15
        SFX_MGR.play('hit')
        if t.hp <= 0 and t.alive:
            t.alive = False
            self.explode(t)
            if t.is_player:
                self.pending_state = STATE_DEFEAT
                self.pending_t = 0.6
            else:
                self.kills += 1
                if self.kills >= CFG['e_count']:
                    self.pending_state = STATE_VICTORY
                    self.pending_t = 0.8

    # ---------- 粒子特效 ----------
    def explode(self, t):
        """坦克击毁：炸裂为小方块（带重力 + 落地弹跳）"""
        cx, cy = t.rect.center
        pal = [t.pal[0], t.pal[1], t.pal[2], (255, 160, 60), (120, 120, 120)]
        floor = t.rect.y + t.rect.h + 8
        for _ in range(28):
            ang = random.uniform(0, math.tau)
            spd = random.uniform(60, 220)
            self.particles.append(Particle(
                cx + random.uniform(-6, 6), cy + random.uniform(-6, 6),
                math.cos(ang) * spd, math.sin(ang) * spd - random.uniform(0, 80),
                random.randint(3, 6), random.choice(pal),
                random.uniform(0.6, 1.2), gravity=300, floor=floor))
        self.shake_t = 0.2
        SFX_MGR.play('explode')

    def spawn_sparks(self, pos, color):
        for _ in range(6):
            self.particles.append(Particle(
                pos[0], pos[1], random.uniform(-90, 90), random.uniform(-110, 30),
                random.randint(2, 4), color, random.uniform(0.2, 0.45)))

    def spawn_dust(self, t):
        cx, cy = t.rect.center
        if t.is_player:                              # 玩家：沿炮口反方向扬尘
            rad = math.radians(t.angle)
            dx, dy = math.sin(rad), -math.cos(rad)
        else:
            dx, dy = DIRS[t.dir]
        self.particles.append(Particle(
            cx - dx * 13 + random.uniform(-4, 4),
            cy - dy * 13 + random.uniform(-4, 4),
            random.uniform(-12, 12), random.uniform(-18, -4),
            random.randint(2, 4), (172, 154, 122), 0.35))

    def update_particles(self, dt):
        for p in self.particles[:]:
            p.vy += p.gravity * dt
            p.x += p.vx * dt
            p.y += p.vy * dt
            if p.floor is not None and p.y > p.floor and p.vy > 0:
                p.y = p.floor
                p.vy *= -0.4
                p.vx *= 0.7
            p.life -= dt
            if p.life <= 0:
                self.particles.remove(p)
        if len(self.particles) > 420:
            del self.particles[:len(self.particles) - 420]

    def update_confetti(self, dt):
        for c in self.confetti[:]:
            c.vy += 200 * dt
            c.x += c.vx * dt
            c.y += c.vy * dt
            c.life -= dt
            if c.life <= 0 or c.y > MAP_H + 10:
                self.confetti.remove(c)
        for _ in range(3):
            self.confetti.append(Particle(
                random.uniform(0, MAP_W), -8,
                random.uniform(-30, 30), random.uniform(60, 140),
                random.randint(4, 6),
                random.choice([(255, 90, 80), (90, 200, 255), GOLD,
                               (140, 230, 120), (255, 150, 240)]),
                3.0))

    # ---------- 渲染 ----------
    def render(self, screen):
        m = self.main
        if self.state == STATE_HOME:
            self.render_home(m)
        else:
            self.render_world(m)
            self.render_hud(m)
            if self.state == STATE_VICTORY:
                self.render_victory(m)
            elif self.state == STATE_DEFEAT:
                self.render_defeat(m)

        # 整体放大到窗口（保持像素锐利），附加震屏偏移
        ox = oy = 0
        if self.shake_t > 0:
            mag = 4 * (self.shake_t / 0.2)
            ox = random.uniform(-mag, mag) * SCALE
            oy = random.uniform(-mag, mag) * SCALE
        screen.fill((0, 0, 0))
        scaled = pygame.transform.scale(m, (WIN_W, WIN_H))
        screen.blit(scaled, (int(ox), int(oy)))

    def render_world(self, m):
        m.blit(self.bg, (0, 0))
        m.blit(self.obs, (0, 0))
        for t in self.tanks:                        # 坦克 + 头顶迷你血条
            if not t.alive:
                continue
            if t.is_player:                         # 玩家：任意角度旋转渲染
                draw_player_tank(m, t.rect, t.angle, t.pal, t.flash, t.muzzle)
            else:
                draw_tank_at(m, t.rect, t.dir, t.pal, t.flash, t.muzzle)
            if t.hp < t.max_hp:
                pct = max(0.0, t.hp / t.max_hp)
                bw, bx, by = 22, t.rect.x, t.rect.y - 7
                color = GREEN if pct > 0.5 else YELLOW if pct > 0.25 else RED
                pygame.draw.rect(m, (30, 30, 30), (bx - 1, by - 1, bw + 2, 6))
                pygame.draw.rect(m, color, (bx, by, int(bw * pct), 4))
            if t.is_player and t.shield > 0:      # 出生护盾青色边框
                if int(t.shield * 8) % 2 == 0:
                    pygame.draw.rect(m, (120, 220, 255),
                                     t.rect.inflate(6, 6), 1)
        p = self.player
        if p.alive and p.target:                  # 左键移动目标标记（青色脉冲）
            tx, ty = int(p.target[0]), int(p.target[1])
            r = 5 + int(2 * math.sin(self.state_t * 12))
            pygame.draw.circle(m, (120, 220, 255), (tx, ty), r, 1)
            pygame.draw.rect(m, (120, 220, 255), (tx - 1, ty - 1, 2, 2))
        for b in self.bullets:                      # 炮弹
            pygame.draw.rect(m, (255, 200, 80), b.rect)
            pygame.draw.rect(m, WHITE, (b.rect.x + 1, b.rect.y + 1, 3, 3))
        for p in self.particles:                    # 小方块粒子
            s = max(1, int(p.size * (p.life / p.max_life)))
            m.fill(p.color, (int(p.x - s / 2), int(p.y - s / 2), s, s))
        for c in self.confetti:
            m.fill(c.color, (int(c.x), int(c.y), c.size, c.size))

    def render_hud(self, m):
        m.blit(self.hud_bar, (0, 0))
        p = self.player
        # 血条
        pct = max(0.0, p.hp / p.max_hp)
        color = GREEN if pct > 0.5 else YELLOW if pct > 0.25 else RED
        pygame.draw.rect(m, (60, 60, 60), (10, 9, 150, 14))
        pygame.draw.rect(m, color, (10, 9, int(150 * pct), 14))
        pygame.draw.rect(m, WHITE, (10, 9, 150, 14), 1)
        hp_txt = get_font(13).render(f"{max(0, p.hp)}/{p.max_hp}", True, WHITE)
        m.blit(hp_txt, (166, 9))
        # 弹药（空仓变红闪烁）
        ammo_col = RED if (self.ammo <= 0 or self.ammo_flash > 0
                           and int(self.ammo_flash * 10) % 2 == 0) else WHITE
        ammo_txt = get_font(16).render(
            f"弹药 {self.ammo}/{CFG['ammo_max']}", True, ammo_col)
        m.blit(ammo_txt, (280, 8))
        # 击毁数
        kill_txt = get_font(16).render(
            f"击毁 {self.kills}/{CFG['e_count']}", True, WHITE)
        m.blit(kill_txt, (470, 8))

    def render_home(self, m):
        m.blit(self.bg, (0, 0))
        m.blit(self.obs, (0, 0))
        ov = pygame.Surface((MAP_W, MAP_H), pygame.SRCALPHA)
        ov.fill((10, 12, 26, 205))
        m.blit(ov, (0, 0))
        # 装饰坦克
        draw_tank_at(m, pygame.Rect(120, 350, 22, 22), 'right', PLAYER_PAL)
        draw_tank_at(m, pygame.Rect(806, 110, 22, 22), 'left', ENEMY_PAL)
        # 主页游戏名
        draw_text_outline(m, "库尔斯克会战浪尖战场", get_font(44), (480, 130), GOLD)
        sub = get_font(18).render("浪尖战场 · 像素坦克对战 · 击毁全部敌方坦克即可获胜",
                                  True, GRAY_TXT)
        m.blit(sub, sub.get_rect(center=(480, 175)))
        self.btn_start.draw(m, self.mouse)
        c1 = get_font(16).render("鼠标左键点击 移动（炮口随移动方向）", True, WHITE)
        c2 = get_font(16).render("鼠标右键点击 开火", True, WHITE)
        m.blit(c1, c1.get_rect(center=(390, 385)))
        m.blit(c2, c2.get_rect(center=(570, 385)))
        tip = get_font(14).render("弹药每 4 秒自动补充 1 发", True, GRAY_TXT)
        m.blit(tip, tip.get_rect(center=(480, 420)))

    def render_victory(self, m):
        t01 = min(1.0, self.state_t / 0.5)
        ease = 1 - (1 - t01) ** 3
        cy = -90 + ease * 210                       # 横幅滑入
        ban = pygame.Surface((480, 110), pygame.SRCALPHA)
        ban.fill((30, 26, 18, 215))
        m.blit(ban, (240, cy - 55))
        pygame.draw.rect(m, GOLD, (240, cy - 55, 480, 110), 3, border_radius=4)
        bounce = 1.0
        if self.state_t > 0.5:                      # 缩放弹跳
            k = (self.state_t - 0.5) / 0.8
            if k < 1:
                bounce = 1 + 0.1 * math.sin(k * math.pi * 3) * (1 - k)
        draw_text_outline(m, "胜利", get_font(int(72 * bounce)), (480, cy), GOLD)
        if self.state_t > 3:
            self.btn_again.draw(m, self.mouse)
            self.btn_home_v.draw(m, self.mouse)

    def render_defeat(self, m):
        ov = pygame.Surface((MAP_W, MAP_H), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 165))
        m.blit(ov, (0, 0))
        box = pygame.Surface((540, 250), pygame.SRCALPHA)
        box.fill((38, 38, 46, 235))
        m.blit(box, (210, 115))
        pygame.draw.rect(m, (96, 96, 108), (210, 115, 540, 250), 3, border_radius=8)
        draw_text_outline(m, "若是巅峰留不住，那就重走来时路",
                          get_font(24), (480, 190), WHITE)
        stat = get_font(16).render(f"本局击毁坦克 {self.kills}/{CFG['e_count']}",
                                   True, GRAY_TXT)
        m.blit(stat, stat.get_rect(center=(480, 240)))
        self.btn_home_d.draw(m, self.mouse)
        self.btn_retry.draw(m, self.mouse)


# ------------------------------------------------------------------
# 主入口
# ------------------------------------------------------------------
def handle_event(game, e):
    """处理单个 Pygame 事件，返回游戏是否继续运行"""
    if e.type == pygame.QUIT:
        return False
    if e.type == pygame.MOUSEMOTION:
        game.set_mouse(e.pos)
    elif e.type == pygame.MOUSEBUTTONDOWN:
        if e.button == 1:                            # 左键：战斗中移动 / 菜单确认
            if game.state == STATE_PLAY:
                game.set_move_target(e.pos)
            else:
                game.click()
        elif e.button == 3 and game.state == STATE_PLAY:
            game.player_fire()                       # 右键：开火
    return True


def main():
    selftest = "--selftest" in sys.argv
    if selftest:
        os.environ["SDL_VIDEODRIVER"] = "dummy"
        os.environ["SDL_AUDIODRIVER"] = "dummy"

    pygame.mixer.pre_init(22050, -16, 2, 512)
    pygame.init()

    screen = pygame.display.set_mode((WIN_W, WIN_H))
    pygame.display.set_caption("库尔斯克会战浪尖战场")
    icon = pygame.Surface((32, 32))
    icon.fill((46, 44, 40))
    pygame.draw.rect(icon, PLAYER_PAL[0], (6, 6, 20, 20))
    pygame.draw.rect(icon, PLAYER_PAL[2], (12, 12, 8, 8))
    pygame.display.set_icon(icon)

    global GRID, SFX_MGR
    GRID = build_grid()
    SFX_MGR = SFX()

    game = Game()
    clock = pygame.time.Clock()

    if selftest:
        # 覆盖全部状态的渲染路径，拦截未定义名称等运行时错误
        game.update(0.016)
        game.render(screen)                          # 主页
        game.start_game()
        # —— 鼠标移动路径测试：左键目标 → 坦克朝目标移动（炮口对齐）——
        y0 = game.player.rect.y
        px, py = game.player.rect.center
        game.set_move_target((int(px * SCALE), int((py - 100) * SCALE)))
        assert game.player.target is not None, "左键未设定移动目标"
        for _ in range(60):
            game.update(0.016)
        assert game.player.rect.y < y0, "左键目标移动失败：坦克未上移"
        assert abs(game.player.angle) < 1 or abs(game.player.angle - 360) < 1, \
            f"炮口未对齐移动方向: angle={game.player.angle}"
        # —— 右键开火测试 ——
        n0 = len(game.bullets)
        game.player_fire()
        assert len(game.bullets) == n0 + 1, "右键开火失败"
        # —— 敌方追踪测试：最远敌坦克应持续逼近玩家（无视线也追踪）——
        far = max(game.enemies, key=lambda t: math.hypot(
            t.rect.centerx - game.player.rect.centerx,
            t.rect.centery - game.player.rect.centery))
        d0 = math.hypot(far.rect.centerx - game.player.rect.centerx,
                        far.rect.centery - game.player.rect.centery)
        for _ in range(60):
            game.update(0.016)
        d1 = math.hypot(far.rect.centerx - game.player.rect.centerx,
                        far.rect.centery - game.player.rect.centery)
        assert d1 < d0, f"敌方坦克未追踪玩家: {d0:.0f} -> {d1:.0f}"
        # —— 友军保护测试：敌坦克开火时炮线上不得有队友 ——
        for e in game.enemies:
            if e.alive and e.state == 'ATTACK':
                assert not game.ally_in_fire_line(e), "敌坦克朝队友开火"
        # —— 绕障开炮测试：挂机模拟，敌方须绕过 LZH 障碍打到玩家 ——
        for _ in range(900):
            game.update(0.016)
            if game.player.hp < 100:
                break
        assert game.player.hp < 100, "敌方未能绕过障碍物开炮"
        # —— 隔墙不开炮测试：敌我同行但中间隔 L 字障碍 ——
        game.state = STATE_PLAY
        game.pending_state = None
        game.bullets = []
        p = game.player
        p.alive = True
        p.hp = 100
        p.shield = 0.0
        p.target = None
        p.rect.topleft = (8 * TILE + 1, 9 * TILE + 1)      # 玩家在 L 右侧
        for i, en in enumerate(game.enemies):
            en.alive = True
            en.state = 'CHASE'
            en.path = None
            if i == 0:
                en.fire_cd = 0.0
                en.rect.topleft = (4 * TILE + 1, 9 * TILE + 1)  # 同行左侧
            else:
                en.fire_cd = 99.0                # 其他坦克暂不参战
        for _ in range(60):
            game.update(0.016)
        assert game.player.hp == 100, "敌方隔着障碍物开炮"
        game.player.hp = 20                          # 触发低血量血条分支
        for _ in range(20):
            game.update(0.016)
        game.render(screen)                          # 战斗 + HUD
        for e in game.enemies:
            e.alive = False
        game.kills = CFG['e_count']
        game._set_state(STATE_VICTORY)
        game.update(0.016)
        game.render(screen)                          # 胜利横幅
        game._set_state(STATE_DEFEAT)
        game.update(0.016)
        game.render(screen)                          # 失败弹窗
        print("SELFTEST OK")
        pygame.quit()
        return

    if "--autostart" in sys.argv or "--diag" in sys.argv:
        game.start_game()

    diag = "--diag" in sys.argv                  # 诊断模式：屏幕显示事件与坦克状态
    evlog = []
    running = True
    while running:
        dt = min(clock.tick(FPS) / 1000.0, 0.05)
        for e in pygame.event.get():
            if diag and e.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP):
                evlog.append(f"{pygame.event.event_name(e.type)} btn={e.button}")
                evlog = evlog[-8:]
            if not handle_event(game, e):
                running = False

        game.update(dt)
        game.render(screen)
        if diag:
            f = get_font(24)
            p = game.player
            info = [f"y={p.rect.y} x={p.rect.x} angle={p.angle:.0f} "
                    f"target={p.target}"]
            mind = min((math.hypot(e.rect.centerx - p.rect.centerx,
                                   e.rect.centery - p.rect.centery)
                        for e in game.enemies if e.alive), default=-1)
            print(f"DIAG y={p.rect.y} x={p.rect.x} angle={p.angle:.0f} "
                  f"target={p.target} bullets={len(game.bullets)} "
                  f"emin={mind:.0f}", flush=True)
            for i, line in enumerate(evlog[::-1]):
                info.append(line)
            for i, line in enumerate(info):
                t = f.render(line, True, (255, 80, 80))
                screen.blit(t, (30, 60 + i * 30))
        pygame.display.flip()

    pygame.quit()


if __name__ == "__main__":
    main()
