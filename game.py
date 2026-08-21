# -*- coding: utf-8 -*-
"""
库尔斯克会战 · 浪尖战场 —— 3D 坦克对战（单文件、零外部资源）
================================================================
技术路线：软件 3D 透视投影 + 画家算法(painter's algorithm) + pygame.draw.polygon，
所有贴图 / 水印 / 音效均由代码程序化生成，不依赖任何图片、音频文件。

【玩法】
  驾驶坦克在 100×200 单位的平坦草地上，击毁全部 4 辆敌方坦克（3 普通 + 1 精英）。
  弹药有限：初始 20 发、上限 20 发，每次击毁（含燃料桶连锁击杀）奖励 5 发。
  普通敌人 2 发击毁，精英 3 发击毁；你被敌方命中 4 发即被击毁。
  弹药耗尽且没有炮弹在飞行、场上仍有敌人时判负，请精打细算！

【操作】
  鼠标滚轮滚动        沿炮口方向移动（前滚前进/后滚倒退，停止滚动即停）
  空格              急停刹车（停止移动）
  鼠标移动          转动炮塔瞄准（移动方向始终跟随炮口朝向）
  鼠标左键          开炮
  鼠标右键(按住)     开瞄准镜（FOV 60°→20°，瞄准灵敏度减半）
  ESC              主页界面退出游戏 / 结算界面返回主页

【胜负判定】
  胜利：击毁全部 4 辆敌方坦克（同帧双条件满足时优先判胜利）。
  失败：玩家血量归零，或 弹药为 0 且无玩家炮弹在飞行 且仍有存活敌人。
"""

import os
import sys
import math
import random
import wave
import struct
import traceback

import pygame

# ============================================================
# ██  区块 1  全局配置(CONFIG 唯一事实源) / 状态常量 / 颜色
# ============================================================

CONFIG = {
    # ---- 战场：宽100 × 长200 的平坦矩形（X∈[-50,50]，Z∈[-100,100]，Y=0）----
    "battlefield": {"width": 100, "length": 200},
    # ---- 玩家坦克 ----
    "player": {
        "hp": 100, "damage": 34, "reload": 2.5, "ammo": 20, "maxAmmo": 20,
        "speed": 12, "turnSpeed": 90, "shellSpeed": 80,
    },
    # ---- 敌方坦克（4 辆 = 3 普通 + 1 精英）----
    "enemy": {
        "count": 4, "hp": 60, "eliteHp": 100, "damage": 25,
        "reload": 3.5, "eliteReload": 2.5, "speed": 8, "shellSpeed": 60,
    },
    # ---- 炮弹 ----
    "shell": {"maxDistance": 300, "lifetime": 4, "radius": 0.25},
    # ---- 敌方 AI ----
    "ai": {
        "engageRange": 120, "keepDistance": 25, "combatRange": 30,
        "decisionInterval": 0.2,
    },
    # ---- 障碍物数量 ----
    "obstacles": {"rock": 8, "bunker": 3, "crate": 12, "barrel": 6},
    # ---- 燃料桶：半径1，被击中爆炸造成范围伤害 ----
    "fuelBarrel": {"radius": 1.0, "explodeRadius": 8.0, "damage": 40},
    # ---- 相机 ----
    "camera": {"fov": 60, "scopeFov": 20, "offset": (0, 4, -8)},
    # ---- 窗口 ----
    "window": {"width": 1280, "height": 720, "fps": 60},
    # ---- 粒子池上限 ----
    "particles": {"max": 150},
    # ---- 结算演出节奏 ----
    "timing": {"loseDialogDelay": 1.0, "winButtonDelay": 2.0},
    # ---- 布阵随机种子（固定布局）----
    "seed": 20260820,
    # ---- 出生点净空半径（米）----
    "spawnClearance": 15,
}

W = CONFIG["window"]["width"]
H = CONFIG["window"]["height"]
HALF_W = CONFIG["battlefield"]["width"] / 2      # 50
HALF_L = CONFIG["battlefield"]["length"] / 2     # 100

# ---- 游戏状态机四态：HOME → PLAYING → {WIN, LOSE} ----
STATE_HOME = "HOME"
STATE_PLAYING = "PLAYING"
STATE_WIN = "WIN"
STATE_LOSE = "LOSE"

# ---- AI 三态 ----
AI_PATROL = "PATROL"
AI_ATTACK = "ATTACK"
AI_COMBAT = "COMBAT"


class C:
    """全局调色板：草地军绿基调 + 战场暖色点缀。"""
    SKY_TOP = (116, 158, 202)
    SKY_BOTTOM = (214, 228, 226)
    GRASS_A = (96, 132, 62)
    GRASS_B = (88, 122, 56)
    GRASS_EDGE = (58, 84, 40)
    HUD_BG = (16, 22, 16)
    HUD_TEXT = (228, 232, 214)
    HUD_ACCENT = (214, 178, 74)
    HP_GREEN = (118, 196, 92)
    HP_RED = (214, 64, 52)
    ENEMY_NAME = (224, 96, 72)
    WHITE = (240, 240, 236)
    BLACK = (12, 14, 12)
    WATERMARK = (255, 255, 255)
    TITLE_GOLD = (222, 184, 92)
    BTN_FACE = (58, 74, 48)
    BTN_HOVER = (96, 120, 70)
    BTN_BORDER = (214, 178, 74)
    SMOKE = (70, 66, 60)
    FIRE = (255, 168, 52)


# ============================================================
# ██  区块 2  数学工具与 3D 透视投影（Camera）
# ============================================================

def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def lerp(a, b, t):
    return a + (b - a) * t


def norm_angle(a):
    """把角度归一到 [-pi, pi]。"""
    while a > math.pi:
        a -= 2 * math.pi
    while a < -math.pi:
        a += 2 * math.pi
    return a


def angle_diff(a, b):
    """从 a 转到 b 的最短角差。"""
    return norm_angle(b - a)


def turn_toward(cur, target, max_step):
    """角度朝目标转动，每帧最多转 max_step。"""
    d = angle_diff(cur, target)
    if abs(d) <= max_step:
        return target
    return cur + max_step if d > 0 else cur - max_step


def dist2d(ax, az, bx, bz):
    return math.hypot(ax - bx, az - bz)


def rot_y_point(p, yaw, pivot=(0.0, 0.0, 0.0)):
    """点 p 绕 Y 轴(经过 pivot)旋转 yaw；yaw=0 时局部 +Z 为世界前方。"""
    x, y, z = p
    c, s = math.cos(yaw), math.sin(yaw)
    dx, dz = x - pivot[0], z - pivot[2]
    return (pivot[0] + dx * c + dz * s, y, pivot[2] - dx * s + dz * c)


class Camera:
    """第三人称跟随相机：pos/yaw/pitch/fov，project() 做透视投影。"""

    def __init__(self):
        cam = CONFIG["camera"]
        self.pos = [0.0, 5.0, -97.0]
        self.yaw = 0.0
        self.pitch = 0.22
        self.base_fov = math.radians(cam["fov"])          # 60°
        self.scope_fov = math.radians(cam["scopeFov"])    # 20°
        self.fov = self.base_fov
        self.scope_t = 0.0        # 开镜插值系数 0~1
        self.scoping = False
        self.shake = 0.0          # 震屏强度
        self.shake_yaw = 0.0
        self.shake_pitch = 0.0
        self._rng = random.Random(99)

    # ---- 跟随：相机位于坦克炮塔局部坐标系 (0,4,-8)，lerp 平滑 ----
    def update_follow(self, tank, dt):
        target = 1.0 if self.scoping else 0.0
        self.scope_t += (target - self.scope_t) * min(1.0, dt * 7.0)
        if abs(self.scope_t - target) < 0.005:
            self.scope_t = target
        # 焦距 f=(W/2)/tan(fov/2)，随 FOV 插值变化
        self.fov = self.base_fov + (self.scope_fov - self.base_fov) * self.scope_t

        aim_yaw = tank.yaw + tank.turret_rel
        ox, oy, oz = CONFIG["camera"]["offset"]
        c, s = math.cos(aim_yaw), math.sin(aim_yaw)
        tx = tank.pos[0] + ox * c + oz * s
        tz = tank.pos[1] - ox * s + oz * c
        k = min(1.0, dt * 8.0)
        self.pos[0] += (tx - self.pos[0]) * k
        self.pos[1] += (oy - self.pos[1]) * k
        self.pos[2] += (tz - self.pos[2]) * k
        self.yaw = norm_angle(self.yaw + angle_diff(self.yaw, aim_yaw) * min(1.0, dt * 10.0))
        # 开镜时俯仰跟随炮管，保证十字线对准炮口指向；平时保持鸟瞰视角
        self.pitch = 0.22 - 0.17 * self.scope_t - tank.barrel_pitch * 0.9 * self.scope_t

    # ---- 震屏：开炮/爆炸/受击时叠加，指数衰减 ----
    def add_shake(self, amount):
        self.shake = min(self.shake + amount, 1.4)

    def update_shake(self, dt):
        self.shake = max(0.0, self.shake - dt * (1.2 + 2.5 * self.shake))
        a = self.shake
        self.shake_yaw = (self._rng.random() * 2 - 1) * 0.022 * a
        self.shake_pitch = (self._rng.random() * 2 - 1) * 0.016 * a

    def focal(self):
        return (W * 0.5) / math.tan(self.fov * 0.5)

    # ---- 世界坐标 → 相机坐标：平移 → 绕Y转-yaw → 绕X转-pitch ----
    def to_camera(self, p):
        dx = p[0] - self.pos[0]
        dy = p[1] - self.pos[1]
        dz = p[2] - self.pos[2]
        yaw = self.yaw + self.shake_yaw
        cy, sy = math.cos(yaw), math.sin(yaw)
        x1 = dx * cy - dz * sy
        z1 = dx * sy + dz * cy
        pitch = self.pitch + self.shake_pitch
        cp, sp = math.cos(pitch), math.sin(pitch)
        y2 = dy * cp + z1 * sp
        z2 = -dy * sp + z1 * cp
        return x1, y2, z2

    # ---- 透视投影：近平面 zc<0.5 剔除，返回 (屏幕x, 屏幕y, 深度) ----
    def project(self, p):
        xc, yc, zc = self.to_camera(p)
        if zc < 0.5:
            return None
        f = self.focal()
        return (W * 0.5 + f * xc / zc, H * 0.5 - f * yc / zc, zc)

    def horizon_y(self):
        """地平线在屏幕上的 y（无穷远处、Y=0 的平面投影成水平线）。"""
        pitch = self.pitch + self.shake_pitch
        return H * 0.5 - self.focal() * math.tan(pitch)


def los_clear(ax, az, bx, bz, obstacles):
    """视线射线检测：从 a 到 b 每 3 米采样，障碍物 AABB 遮挡则返回 False。"""
    d = dist2d(ax, az, bx, bz)
    if d < 1e-3:
        return True
    steps = max(2, int(d / 3.0))
    for i in range(1, steps):
        t = i / steps
        px = ax + (bx - ax) * t
        pz = az + (bz - az) * t
        for ob in obstacles:
            if not ob.alive or ob.kind == "barrel":
                continue  # 燃料桶低矮不挡视线，木箱残骸不计
            if ob.blocks_los and ob.contains(px, pz, 0.3):
                return False
    return True


# ============================================================
# ██  区块 3  程序化建模：盒子 / 八棱柱 / 坦克 / 障碍
# ============================================================

def make_box(size, center=(0.0, 0.0, 0.0), color=(200, 200, 200)):
    """生成长方体 8 顶点 + 6 面（顶点顺序保证法线朝外，供背面剔除）。"""
    sx, sy, sz = size
    cx, cy, cz = center
    hx, hy, hz = sx * 0.5, sy * 0.5, sz * 0.5
    v0 = (cx - hx, cy - hy, cz - hz)
    v1 = (cx + hx, cy - hy, cz - hz)
    v2 = (cx + hx, cy + hy, cz - hz)
    v3 = (cx - hx, cy + hy, cz - hz)
    v4 = (cx - hx, cy - hy, cz + hz)
    v5 = (cx + hx, cy - hy, cz + hz)
    v6 = (cx + hx, cy + hy, cz + hz)
    v7 = (cx - hx, cy + hy, cz + hz)
    return [
        ((v4, v5, v6, v7), color),   # 前 +Z
        ((v1, v0, v3, v2), color),   # 后 -Z
        ((v5, v1, v2, v6), color),   # 右 +X
        ((v0, v4, v7, v3), color),   # 左 -X
        ((v3, v7, v6, v2), color),   # 顶 +Y
        ((v0, v1, v5, v4), color),   # 底 -Y
    ]


def make_prism(radius, height, center=(0.0, 0.0, 0.0), color=(200, 200, 200),
               sides=8, top_color=None):
    """生成八棱柱（炮塔 / 燃料桶）：侧面 + 顶面（底面不可见，省略省性能）。"""
    cx, cy, cz = center
    yb = cy - height * 0.5
    yt = cy + height * 0.5
    top_color = top_color or color
    bot = []
    top = []
    for i in range(sides):
        a = i * 2.0 * math.pi / sides
        sx_ = math.sin(a) * radius
        sz_ = math.cos(a) * radius
        bot.append((cx + sx_, yb, cz + sz_))
        top.append((cx + sx_, yt, cz + sz_))
    faces = []
    for i in range(sides):
        j = (i + 1) % sides
        faces.append(((bot[i], bot[j], top[j], top[i]), color))
    faces.append((tuple(top), top_color))
    return faces


def transform_faces(faces, yaw, pos, pivot=(0.0, 0.0, 0.0)):
    """面片刚体变换：绕 pivot 旋转 yaw，再平移到 pos。"""
    out = []
    c, s = math.cos(yaw), math.sin(yaw)
    for verts, color in faces:
        nv = []
        for (x, y, z) in verts:
            dx, dz = x - pivot[0], z - pivot[2]
            nv.append((pivot[0] + dx * c + dz * s + pos[0],
                       y + pos[1],
                       pivot[2] - dx * s + dz * c + pos[2]))
        out.append((tuple(nv), color))
    return out


def blend(color_a, color_b, t):
    t = clamp(t, 0.0, 1.0)
    return (int(color_a[0] + (color_b[0] - color_a[0]) * t),
            int(color_a[1] + (color_b[1] - color_a[1]) * t),
            int(color_a[2] + (color_b[2] - color_a[2]) * t))


def shade(color, k):
    return (clamp(int(color[0] * k), 0, 255),
            clamp(int(color[1] * k), 0, 255),
            clamp(int(color[2] * k), 0, 255))


# ---- 阵营配色 ----
PLAYER_HULL = (104, 122, 66)
PLAYER_TRACK = (52, 56, 46)
PLAYER_TURRET = (92, 110, 58)
PLAYER_BARREL = (66, 72, 52)
ENEMY_HULL = (136, 106, 68)
ENEMY_TRACK = (58, 50, 42)
ENEMY_TURRET = (122, 92, 58)
ENEMY_BARREL = (74, 62, 48)
ELITE_ACCENT = (168, 58, 44)
WRECK_COLOR = (40, 38, 34)
ROCK_COLOR = (128, 126, 120)
ROCK_TOP = (148, 146, 138)
BUNKER_COLOR = (112, 108, 98)
BUNKER_TOP = (90, 88, 80)
CRATE_COLOR = (150, 112, 62)
CRATE_TOP = (168, 128, 74)
BARREL_COLOR = (158, 66, 44)
BARREL_TOP = (120, 50, 36)


class TankMesh:
    """坦克建模：车体(3.6×1.2×6) + 履带×2 + 八棱柱炮塔 + 炮管(后坐动画)。"""

    @staticmethod
    def build_hull(hull_c, track_c):
        faces = []
        faces += make_box((3.6, 1.2, 6.0), (0.0, 1.05, 0.0), hull_c)
        faces += make_box((1.05, 0.9, 6.4), (-1.85, 0.5, 0.0), track_c)
        faces += make_box((1.05, 0.9, 6.4), (1.85, 0.5, 0.0), track_c)
        # 车头楔形装甲（装饰小盒）
        faces += make_box((3.0, 0.5, 1.0), (0.0, 1.55, 2.7), hull_c)
        return faces

    @staticmethod
    def build_turret(turret_c, accent=None):
        faces = make_prism(1.35, 0.9, (0.0, 0.45, 0.0), turret_c,
                           top_color=accent or turret_c)
        # 炮塔后部储物箱
        faces += make_box((1.6, 0.6, 1.0), (0.0, 0.45, -1.55), turret_c)
        return faces

    @staticmethod
    def build_barrel(barrel_c, recoil):
        # 炮管沿炮塔局部 +Z 方向，后坐时向后缩最多 0.3
        return make_box((0.24, 0.24, 3.4), (0.0, 0.5, 2.35 - recoil), barrel_c)


# ============================================================
# ██  区块 4  事件总线 EventBus
# ============================================================

class EventBus:
    """轻量事件总线：emit 广播，on 订阅。

    统一事件名：shell:fired / shell:hit:tank(载荷含 team 字段) /
    tank:destroyed / player:damaged / game:win / game:lose
    """

    def __init__(self):
        self._handlers = {}

    def on(self, name, fn):
        self._handlers.setdefault(name, []).append(fn)

    def emit(self, name, **payload):
        for fn in self._handlers.get(name, ()):  # 拷贝避免回调中订阅修改
            fn(payload)

    def clear(self):
        self._handlers.clear()


# ============================================================
# ██  区块 5  实体：Tank 基类 / 玩家 / 敌方AI / 炮弹 / 障碍物
# ============================================================

class Tank:
    """坦克基类：位置(x,z)、朝向 yaw、炮塔相对角 turret_rel、血量、装填。"""
    RADIUS = 2.3  # 碰撞包围球半径

    def __init__(self, pos, yaw, hp, team, speed):
        self.pos = [float(pos[0]), float(pos[1])]
        self.yaw = yaw
        self.turret_rel = 0.0
        self.hp = hp
        self.max_hp = hp
        self.team = team           # "player" / "enemy"
        self.speed = speed
        self.alive = True
        self.reload_timer = 0.0
        self.flash = 0.0           # 受击闪白计时
        self.recoil = 0.0          # 炮管后坐量(0~0.3)
        self.barrel_pitch = 0.0    # 炮管俯仰角(弧度，鼠标上下控制，正值朝上)
        self.elite = False

    def turret_abs(self):
        return norm_angle(self.yaw + self.turret_rel)

    def update_timers(self, dt):
        if self.reload_timer > 0:
            self.reload_timer -= dt
        if self.flash > 0:
            self.flash -= dt
        if self.recoil > 0:
            self.recoil = max(0.0, self.recoil - dt * 1.4)  # 后坐 0.3 缓慢复位

    def take_damage(self, dmg, source=None, bus=None):
        """受伤。source 标识伤害来源("player"/"enemy"/"barrel")。"""
        if not self.alive:
            return
        self.hp -= dmg
        self.flash = 0.15
        if bus is not None and self.team == "player":
            bus.emit("player:damaged", damage=dmg, hp=max(0, self.hp))
        if self.hp <= 0:
            self.hp = 0
            self.alive = False
            if bus is not None:
                bus.emit("tank:destroyed", team=self.team, source=source,
                         pos=(self.pos[0], self.pos[1]), elite=self.elite)

    def muzzle_pos(self):
        """炮口世界坐标（炮管长 3.4，自炮塔枢轴向前 4.05，计入俯仰角）。"""
        a = self.turret_abs()
        bp = self.barrel_pitch
        return (self.pos[0] + math.sin(a) * 4.05 * math.cos(bp),
                2.15 + math.sin(bp) * 4.05,
                self.pos[1] + math.cos(a) * 4.05 * math.cos(bp))

    # ---- 收集全部面片(世界坐标)，供画家算法绘制 ----
    def get_faces(self, hull_faces, turret_faces):
        if self.alive:
            ft = self.flash
            k = min(1.0, ft * 8.0) if ft > 0 else 0.0
            hfaces = [((v, blend(c, C.WHITE, k)) if k > 0 else (v, c))
                      for v, c in hull_faces]
            barrel = TankMesh.build_barrel(
                PLAYER_BARREL if self.team == "player" else ENEMY_BARREL,
                self.recoil)
            tfaces = [((v, blend(c, C.WHITE, k)) if k > 0 else (v, c))
                      for v, c in turret_faces]
            bfaces = [((v, blend(c, C.WHITE, k)) if k > 0 else (v, c))
                      for v, c in barrel]
        else:
            hfaces = [(v, WRECK_COLOR) for v, _ in hull_faces]
            tfaces = [(v, WRECK_COLOR) for v, _ in turret_faces]
            bfaces = [(v, WRECK_COLOR) for v, _ in
                      TankMesh.build_barrel(WRECK_COLOR, 0.0)]
        # 炮管俯仰：炮管面片先绕炮塔局部 X 轴(枢轴 y=2.12)旋转 barrel_pitch
        bp_c, bp_s = math.cos(self.barrel_pitch), math.sin(self.barrel_pitch)
        piv_y, piv_z = 2.12, -0.35
        pitched = []
        for verts, color in bfaces:
            nv = []
            for (x, y, z) in verts:
                dy, dz = y - piv_y, z - piv_z
                nv.append((x, piv_y + dy * bp_c - dz * bp_s,
                           piv_z + dy * bp_s + dz * bp_c))
            pitched.append((tuple(nv), color))
        # 炮塔+炮管绕自身枢轴转 turret_rel，枢轴位于车体局部 (0,1.62,-0.35)
        pivot = (0.0, 1.62, -0.35)
        tf = []
        c, s = math.cos(self.turret_rel), math.sin(self.turret_rel)
        for verts, color in tfaces + pitched:
            nv = []
            for (x, y, z) in verts:
                dx, dz = x - pivot[0], z - pivot[2]
                nv.append((pivot[0] + dx * c + dz * s, y, pivot[2] - dx * s + dz * c))
            tf.append((tuple(nv), color))
        pos3 = (self.pos[0], 0.0, self.pos[1])
        return transform_faces(hfaces, self.yaw, pos3) + transform_faces(tf, self.yaw, pos3)


class PlayerTank(Tank):
    """玩家坦克：滚轮移动(滚动才走、停滚即停、沿炮口方向) + 鼠标瞄准，
    右键开镜灵敏度×0.5。"""

    # 车体朝炮塔朝向对齐的最大角速度（180°/s）
    ALIGN_SPEED = math.radians(180)
    # 滚动窗口时长(秒)：每次滚轮事件续期；停滚超过此时长即平滑停下（调参常量）
    WHEEL_WINDOW = 0.35

    def __init__(self):
        pc = CONFIG["player"]
        super().__init__((0.0, -85.0), 0.0, pc["hp"], "player", pc["speed"])
        self.ammo = pc["ammo"]
        self.max_ammo = pc["maxAmmo"]
        self.damage = pc["damage"]
        self.reload_time = pc["reload"]
        self.shell_speed = pc["shellSpeed"]
        self.turn_speed = math.radians(pc["turnSpeed"])
        # 滚轮移动状态：move_mode +1 前进 / 0 停驻 / -1 倒退；
        # move_timer 为滚动窗口倒计时，归零后目标速度置 0（停滚即停）
        self.move_mode = 0
        self.move_timer = 0.0
        self.move_speed_cur = 0.0   # 当前速度(带符号)，加速度插值平滑起步/刹车
        self.hull_faces = TankMesh.build_hull(PLAYER_HULL, PLAYER_TRACK)
        self.turret_faces = TankMesh.build_turret(PLAYER_TURRET)

    def handle_move(self, dt):
        """滚轮移动：沿炮塔世界朝向位移，move_mode ∈ {-1,0,+1}；
        滚动窗口(move_timer)过期后目标速度置 0，加速度插值平滑减速至停；
        移动中车体 yaw 朝炮塔朝向对齐。越界与碰撞由 CollisionSystem 处理。"""
        self.move_timer = max(0.0, self.move_timer - dt)
        # 窗口内才维持目标速度；停滚超窗即减速停止（不瞬移急停也不无限滑行）
        target = self.move_mode * self.speed if self.move_timer > 0 else 0.0
        # 加速度插值：起步平滑过渡，窗口过期/刹车时以更快的减速曲线停下
        k = min(1.0, dt * (1.4 if target != 0.0 else 3.0))
        self.move_speed_cur += (target - self.move_speed_cur) * k
        if target == 0.0 and abs(self.move_speed_cur) < 0.05:
            self.move_speed_cur = 0.0
        if self.move_speed_cur != 0.0:
            aim = self.turret_abs()   # 移动方向始终取炮口朝向，与车体 yaw 无关
            self.pos[0] += math.sin(aim) * self.move_speed_cur * dt
            self.pos[1] += math.cos(aim) * self.move_speed_cur * dt
            # 车体平滑转向炮塔朝向（正向对齐，倒退不倒转 180°）；
            # 同步反向补偿 turret_rel，保持炮塔世界指向(瞄准)不变
            d = angle_diff(self.yaw, aim)
            step = clamp(d, -self.ALIGN_SPEED * dt, self.ALIGN_SPEED * dt)
            if abs(step) > 1e-6:
                self.yaw = norm_angle(self.yaw + step)
                self.turret_rel = norm_angle(self.turret_rel - step)

    def handle_aim(self, dx_px, dy_px, scoping):
        """鼠标相对位移：水平转炮塔，垂直调炮管俯仰；开镜灵敏度减半。"""
        sens = math.radians(0.12) * (0.5 if scoping else 1.0)
        self.turret_rel = norm_angle(self.turret_rel + dx_px * sens)
        # 鼠标上移(相对位移为负)抬炮口；钳制 [-10°, +20°]
        self.barrel_pitch = clamp(self.barrel_pitch - dy_px * sens,
                                  math.radians(-10), math.radians(20))

    def can_fire(self):
        return self.alive and self.reload_timer <= 0 and self.ammo > 0

    def try_fire(self, game):
        if not self.can_fire():
            return False
        self.ammo -= 1
        self.reload_timer = self.reload_time
        self.recoil = 0.3
        game.spawn_shell(self)
        game.bus.emit("shell:fired", team="player")
        game.camera.add_shake(0.28)
        game.feedback.muzzle_flash(self.muzzle_pos())
        game.sounds.play("fire")
        return True


class EnemyTank(Tank):
    """敌方坦克 AI：PATROL/ATTACK/COMBAT 三态，0.2s 节流决策。"""
    TURRET_SPEED = math.radians(75)
    TURN_SPEED = math.radians(75)

    def __init__(self, pos, elite=False, rng=None):
        ec = CONFIG["enemy"]
        hp = ec["eliteHp"] if elite else ec["hp"]
        super().__init__(pos, math.pi, hp, "enemy", ec["speed"])
        self.elite = elite
        self.damage = ec["damage"]
        self.reload_time = ec["eliteReload"] if elite else ec["reload"]
        self.shell_speed = ec["shellSpeed"]
        accent = ELITE_ACCENT if elite else None
        self.hull_faces = TankMesh.build_hull(ENEMY_HULL, ENEMY_TRACK)
        self.turret_faces = TankMesh.build_turret(ENEMY_TURRET, accent)
        self.state = AI_PATROL
        self.decide_timer = random.random() * 0.2
        self.waypoint = [pos[0], pos[1]]
        self.orbit_dir = 1 if (rng or random).random() < 0.5 else -1
        self.orbit_flip = 4.0
        self.spread = 0.0
        self.frozen = False   # WIN 后冻结 AI 开火

    def pick_waypoint(self, rng):
        self.waypoint = [rng.uniform(-42, 42), rng.uniform(-60, 92)]

    def decide(self, game):
        """每 0.2s 决策一次：距离 + 视线(射线检测) 决定三态切换。"""
        ai = CONFIG["ai"]
        p = game.player
        if not p.alive:
            self.state = AI_PATROL
            return
        d = dist2d(self.pos[0], self.pos[1], p.pos[0], p.pos[1])
        visible = d < ai["engageRange"] and los_clear(
            self.pos[0], self.pos[1], p.pos[0], p.pos[1], game.obstacles)
        if visible and d < ai["combatRange"]:
            self.state = AI_COMBAT
        elif visible:
            self.state = AI_ATTACK
        else:
            self.state = AI_PATROL
        if self.state != AI_PATROL:
            # 瞄准时加入随机散布，给玩家反应空间
            self.spread = math.radians(random.uniform(-3.0, 3.0))

    def update_ai(self, dt, game):
        if self.frozen or not self.alive:
            return
        self.decide_timer -= dt
        if self.decide_timer <= 0:
            self.decide_timer = CONFIG["ai"]["decisionInterval"]
            self.decide(game)

        p = game.player
        ai = CONFIG["ai"]
        d = dist2d(self.pos[0], self.pos[1], p.pos[0], p.pos[1])
        ang_to_p = math.atan2(p.pos[0] - self.pos[0], p.pos[1] - self.pos[1])
        move_yaw = None
        move_speed = 0.0

        if self.state == AI_PATROL:
            dw = dist2d(self.pos[0], self.pos[1], self.waypoint[0], self.waypoint[1])
            if dw < 4.0:
                self.pick_waypoint(game.rng)
            else:
                move_yaw = math.atan2(self.waypoint[0] - self.pos[0],
                                      self.waypoint[1] - self.pos[1])
                move_speed = self.speed * 0.7
            self.turret_rel = turn_toward(self.turret_rel, 0.0,
                                          self.TURRET_SPEED * dt * 0.5)
        elif self.state == AI_ATTACK:
            move_yaw = ang_to_p
            move_speed = self.speed if d > ai["keepDistance"] else 0.0
            self._aim_and_fire(dt, game, ang_to_p, d)
        else:  # COMBAT：保持约 keepDistance 环绕走位
            self.orbit_flip -= dt
            if self.orbit_flip <= 0:
                self.orbit_flip = random.uniform(3.0, 6.0)
                self.orbit_dir = -self.orbit_dir
            radial = 0.0
            if d > ai["keepDistance"] + 3:
                radial = 0.7
            elif d < ai["keepDistance"] - 3:
                radial = -0.7
            tang = ang_to_p + self.orbit_dir * math.pi * 0.5
            vx = math.sin(ang_to_p) * radial + math.sin(tang) * 0.8
            vz = math.cos(ang_to_p) * radial + math.cos(tang) * 0.8
            move_yaw = math.atan2(vx, vz)
            move_speed = self.speed * 0.85
            self._aim_and_fire(dt, game, ang_to_p, d)

        if move_yaw is not None and move_speed > 0:
            self.yaw = turn_toward(self.yaw, move_yaw, self.TURN_SPEED * dt)
            if abs(angle_diff(self.yaw, move_yaw)) < math.radians(50):
                self.pos[0] += math.sin(self.yaw) * move_speed * dt
                self.pos[1] += math.cos(self.yaw) * move_speed * dt

    def _aim_and_fire(self, dt, game, ang_to_p, d):
        """炮塔转向目标+散布，对准且视线无遮挡时装填完毕即开火。"""
        target_rel = norm_angle(ang_to_p + self.spread - self.yaw)
        self.turret_rel = turn_toward(self.turret_rel, target_rel,
                                      self.TURRET_SPEED * dt)
        # 重力弹道补偿：远距离自动抬炮口，保持原有命中率(简化外弹道)
        t_flight = d / self.shell_speed
        self.barrel_pitch = clamp(math.atan(7.0 * t_flight * t_flight / max(1.0, d)),
                                  0.0, 0.3)
        aligned = abs(angle_diff(self.turret_abs(), ang_to_p)) < math.radians(6)
        visible = los_clear(self.pos[0], self.pos[1],
                            game.player.pos[0], game.player.pos[1], game.obstacles)
        if (self.reload_timer <= 0 and aligned and visible
                and d < CONFIG["ai"]["engageRange"] and game.player.alive):
            self.reload_timer = self.reload_time
            self.recoil = 0.3
            game.spawn_shell(self)
            game.bus.emit("shell:fired", team="enemy")
            game.feedback.muzzle_flash(self.muzzle_pos())
            game.sounds.play("fire_far" if d > 45 else "fire")


class Projectile:
    """炮弹：子步长积分（每步≤2米）防高速穿透。"""

    def __init__(self, owner):
        self.team = owner.team
        self.damage = owner.damage
        self.speed = owner.shell_speed
        self.pos = list(owner.muzzle_pos())
        a = owner.turret_abs()
        bp = owner.barrel_pitch  # 炮弹初速方向含俯仰分量(用 list 以便重力修改 y 分量)
        self.dir = [math.sin(a) * math.cos(bp), math.sin(bp),
                    math.cos(a) * math.cos(bp)]
        self.radius = CONFIG["shell"]["radius"]
        self.dist = 0.0
        self.age = 0.0
        self.alive = True
        self.prev = list(self.pos)

    def update(self, dt, game):
        if not self.alive:
            return
        n = max(1, int(math.ceil(self.speed * dt / 2.0)))  # 子步长≤2m
        step = self.speed * dt / n
        self.prev = list(self.pos)
        for _ in range(n):
            self.dir[1] -= 14.0 * (dt / n) / self.speed  # 重力下坠(简化弹道)
            self.pos[0] += self.dir[0] * step
            self.pos[1] += self.dir[1] * step
            self.pos[2] += self.dir[2] * step
            self.dist += step
            self.age += dt / n
            if game.collide_projectile(self):
                break
            if (self.pos[1] <= 0.02
                    or abs(self.pos[0]) > HALF_W + 2 or abs(self.pos[2]) > HALF_L + 2
                    or self.dist > CONFIG["shell"]["maxDistance"]
                    or self.age > CONFIG["shell"]["lifetime"]):
                if self.pos[1] <= 0.02:
                    game.feedback.impact(self.pos, small=True)
                self.alive = False
                break


class Obstacle:
    """障碍物：岩石(4×3×4) / 硚堡(8×4×8) / 木箱(2×2×2,1发可毁) / 燃料桶(半径1)。"""

    SIZES = {"rock": (4.0, 3.0, 4.0), "bunker": (8.0, 4.0, 8.0), "crate": (2.0, 2.0, 2.0)}

    def __init__(self, kind, x, z):
        self.kind = kind
        self.x = x
        self.z = z
        self.alive = True
        if kind == "barrel":
            self.sx = self.sz = CONFIG["fuelBarrel"]["radius"] * 2
            self.sy = 2.4
            self.blocks_los = False
        else:
            self.sx, self.sy, self.sz = self.SIZES[kind]
            self.blocks_los = True
        self.faces = self._build_faces()

    def _build_faces(self):
        if self.kind == "rock":
            f = make_box((self.sx, self.sy, self.sz),
                         (0, self.sy * 0.5, 0), ROCK_COLOR)
            f += make_box((self.sx * 0.55, self.sy * 0.5, self.sz * 0.55),
                          (0.4, self.sy * 0.95, -0.3), ROCK_TOP)
            return f
        if self.kind == "bunker":
            f = make_box((self.sx, self.sy, self.sz),
                         (0, self.sy * 0.5, 0), BUNKER_COLOR)
            f += make_box((self.sx * 0.8, 0.5, self.sz * 0.8),
                          (0, self.sy + 0.25, 0), BUNKER_TOP)
            # 射击孔（黑色薄片）
            f += make_box((2.4, 0.6, 0.2), (0, self.sy * 0.6, self.sz * 0.5), C.BLACK)
            return f
        if self.kind == "crate":
            f = make_box((self.sx, self.sy, self.sz),
                         (0, self.sy * 0.5, 0), CRATE_COLOR)
            return [((v, CRATE_TOP if i == 4 else c))
                    for i, (v, c) in enumerate(f)]
        # 燃料桶：八棱柱，红锈色
        return make_prism(CONFIG["fuelBarrel"]["radius"], 2.4,
                          (0, 1.2, 0), BARREL_COLOR, top_color=BARREL_TOP)

    def get_faces(self):
        return transform_faces(self.faces, 0.0, (self.x, 0.0, self.z))

    def contains(self, px, pz, pad=0.0):
        """点是否在 AABB(含膨胀)内；燃料桶用圆形判定。"""
        if self.kind == "barrel":
            return dist2d(px, pz, self.x, self.z) <= CONFIG["fuelBarrel"]["radius"] + pad
        hx, hz = self.sx * 0.5 + pad, self.sz * 0.5 + pad
        return abs(px - self.x) <= hx and abs(pz - self.z) <= hz



# ============================================================
# ██  区块 6  系统：音效/字体/水印/反馈/HUD/瞄准镜/UI
# ============================================================

class SoundBank:
    """程序化合成音效：wave/array/struct 思路生成 PCM，无任何外部音频文件。"""

    def __init__(self):
        self.enabled = False
        self.sounds = {}
        info = pygame.mixer.get_init()
        if not info:
            return  # 无声卡降级：静默运行
        self.rate = info[0]
        try:
            self._build_all()
            self.enabled = True
        except Exception:
            self.enabled = False

    def _mk(self, samples):
        """浮点采样序列(-1~1) → struct 打包 16bit PCM → wave 容器校验 → Sound。"""
        vals = [int(clamp(v, -1.0, 1.0) * 32000) for v in samples]
        raw = struct.pack("<%dh" % len(vals), *vals)
        # 写入内存 WAV 容器再读回，确保采样格式与 mixer 一致
        import io
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self.rate)
            wf.writeframes(raw)
        buf.seek(0)
        with wave.open(buf, "rb") as rf:
            pcm = rf.readframes(rf.getnframes())
        return pygame.mixer.Sound(buffer=pcm)

    def _tone(self, freq, dur, vol=0.5, decay=8.0, square=False):
        n = int(self.rate * dur)
        out = []
        for i in range(n):
            t = i / self.rate
            ph = math.sin(2 * math.pi * freq * t)
            v = (1.0 if ph >= 0 else -1.0) if square else ph
            out.append(v * vol * math.exp(-decay * t))
        return out

    def _noise(self, dur, vol=0.5, decay=8.0, rng=None):
        rng = rng or random
        n = int(self.rate * dur)
        return [(rng.random() * 2 - 1) * vol * math.exp(-decay * (i / self.rate))
                for i in range(n)]

    @staticmethod
    def _mix(*tracks):
        n = max(len(t) for t in tracks)
        out = [0.0] * n
        for tr in tracks:
            for i, v in enumerate(tr):
                out[i] += v
        return out

    def _build_all(self):
        m = self._mix
        self.sounds["fire"] = self._mk(m(self._noise(0.16, 0.65, 20),
                                         self._tone(70, 0.18, 0.8, 14)))
        self.sounds["fire_far"] = self._mk(m(self._noise(0.14, 0.2, 22),
                                             self._tone(60, 0.15, 0.25, 14)))
        self.sounds["explosion"] = self._mk(m(self._noise(0.7, 0.9, 5),
                                              self._tone(45, 0.6, 0.9, 6)))
        self.sounds["hit"] = self._mk(m(self._tone(880, 0.07, 0.4, 30),
                                        self._noise(0.06, 0.3, 40)))
        self.sounds["hurt"] = self._mk(m(self._tone(170, 0.22, 0.55, 9),
                                         self._noise(0.12, 0.35, 18)))
        self.sounds["reload"] = self._mk(self._tone(1400, 0.045, 0.3, 45, square=True))
        self.sounds["click"] = self._mk(self._tone(950, 0.05, 0.3, 40))
        seq = []
        for f in (523.25, 659.25, 783.99, 1046.5):
            seq += self._tone(f, 0.22, 0.4, 4)
        self.sounds["win"] = self._mk(seq)
        seq = []
        for f in (392.0, 330.0, 262.0, 196.0):
            seq += self._tone(f, 0.3, 0.4, 3)
        self.sounds["lose"] = self._mk(seq)

    def play(self, name):
        if self.enabled and name in self.sounds:
            try:
                self.sounds[name].play()
            except Exception:
                pass


class FontManager:
    """中文字体管理：Windows→跨平台 CJK 回退链，渲染“浪”验证字形，缓存复用。"""

    CANDIDATES = ("microsoftyahei", "simhei", "simsun",
                  "notosanscjksc", "wenquanyimicrohei", "pingfangsc")

    def __init__(self):
        self.base = None
        for name in self.CANDIDATES:
            try:
                f = pygame.font.SysFont(name, 32)
                probe = f.render("浪", True, (255, 255, 255))
                if probe.get_width() >= 16:  # 字形渲染成功(非豆腐块宽度)
                    self.base = name
                    break
            except Exception:
                continue
        self._cache = {}

    def get(self, size):
        f = self._cache.get(size)
        if f is None:
            if self.base is not None:
                f = pygame.font.SysFont(self.base, size)
            else:
                f = pygame.font.Font(None, size)  # 兵底：内置默认字体
            self._cache[size] = f
        return f


class Watermark:
    """“浪尖战场”水印双保险，四状态全程显示。

    地面层：预烘焙 Surface，文字旋转 -30°、透明度≥0.08，锚定在世界坐标上；
    屏幕层：平铺小字，字号≥16px、透明度≥0.08、旋转 -30°。
    """

    GROUND_SPOTS = ((0, -55), (0, 8), (-22, 58), (24, -18))

    def __init__(self, fonts):
        # ---- 屏幕层平铺 tile（预渲染缓存）----
        f = fonts.get(22)
        txt = f.render("浪尖战场", True, C.WATERMARK)
        txt.set_alpha(30)                      # 30/255 ≈ 0.118 ≥ 0.08
        rot = pygame.transform.rotate(txt, 30)  # 画面内视觉倾斜 -30°
        self.tile = pygame.Surface((380, 300), pygame.SRCALPHA)
        self.tile.blit(rot, (30, 120))
        self.tile.blit(rot, (230, 10))
        # ---- 地面层烘焙 Surface ----
        gf = fonts.get(90)
        gt = gf.render("浪尖战场", True, C.WATERMARK)
        gt.set_alpha(34)                       # ≈0.13 ≥ 0.08
        self.ground_img = pygame.transform.rotate(gt, 30)
        self.ground_world_w = 30.0             # 对应世界宽度(单位)

    def draw_screen(self, screen):
        y = -60
        while y < H:
            x = -80
            while x < W:
                screen.blit(self.tile, (x, y))
                x += 380
            y += 300

    def draw_ground(self, screen, cam):
        f = cam.focal()
        iw, ih = self.ground_img.get_size()
        for gx, gz in self.GROUND_SPOTS:
            pr = cam.project((gx, 0.06, gz))
            if pr is None:
                continue
            sx, sy, z = pr
            scale_px = f * self.ground_world_w / z   # 透视缩放
            if scale_px < 24:
                continue
            scale_px = min(scale_px, 360)  # 上限钳制：防止近距离生成超大 Surface 崩溃/掉帧
            ratio = ih / iw
            img = pygame.transform.smoothscale(
                self.ground_img, (int(scale_px), max(1, int(scale_px * ratio))))
            img.set_alpha(34)
            screen.blit(img, (sx - img.get_width() / 2, sy - img.get_height() / 2))


class FeedbackSystem:
    """操作反馈：粒子池(上限150)/受击红晕/命中标记/炮口火光/爆炸残骸。"""

    def __init__(self):
        self.particles = []
        self.muzzles = []          # [[pos], t]
        self.damage_t = 0.0        # 受击红晕
        self.hit_marker = 0.0      # 命中标记
        self._rng = random.Random(7)
        # 预渲染受击红晕(屏幕边缘红色渐变)
        self.vignette = pygame.Surface((W, H), pygame.SRCALPHA)
        max_r = int(math.hypot(W, H) / 2) + 8
        cx, cy = W // 2, H // 2
        for r in range(max_r, max_r - 260, -6):
            a = int(140 * (1 - (max_r - r) / 260.0) ** 2)
            pygame.draw.circle(self.vignette, (190, 22, 18, a), (cx, cy), r, 8)

    def muzzle_flash(self, pos):
        self.muzzles.append([list(pos), 0.09])
        self.spawn(pos, 6, (C.FIRE, (255, 220, 120)), 6.0, 4.0, 0.22, 0.30)

    def impact(self, pos, small=False):
        n = 5 if small else 10
        self.spawn(pos, n, ((120, 110, 90), (160, 150, 120)), 5.0, 5.0, 0.4, 0.22)

    def explosion(self, pos, big=True):
        n = 26 if big else 14
        self.spawn(pos, n, (C.FIRE, (255, 96, 40), (255, 220, 130)),
                   13.0 if big else 8.0, 9.0, 0.7, 0.45)
        self.spawn((pos[0], pos[1] + 1.0, pos[2]), n // 2,
                   (C.SMOKE, (100, 96, 88)), 4.0, 3.5, 1.3, 0.6)

    def spark(self, pos):
        self.spawn(pos, 8, ((255, 240, 180), (255, 180, 90)), 7.0, 6.0, 0.3, 0.2)

    def spawn(self, pos, count, colors, speed, up, life, size):
        cap = CONFIG["particles"]["max"]
        for _ in range(count):
            if len(self.particles) >= cap:
                self.particles.pop(0)  # 池满则淘汰最旧粒子
            a = self._rng.random() * 2 * math.pi
            b = self._rng.random() * 2 - 1
            sp = speed * (0.35 + self._rng.random() * 0.65)
            self.particles.append({
                "p": [pos[0], max(0.1, pos[1]), pos[2]],
                "v": [math.cos(a) * sp * math.cos(b),
                      abs(math.sin(b)) * sp * 0.8 + up * self._rng.random(),
                      math.sin(a) * sp * math.cos(b)],
                "life": life * (0.6 + self._rng.random() * 0.4),
                "max": life,
                "color": colors[self._rng.randrange(len(colors))],
                "size": size,
            })

    def update(self, dt):
        for pt in self.particles:
            pt["life"] -= dt
            pt["v"][1] -= 14.0 * dt
            pt["p"][0] += pt["v"][0] * dt
            pt["p"][1] += pt["v"][1] * dt
            pt["p"][2] += pt["v"][2] * dt
            if pt["p"][1] < 0.05:
                pt["p"][1] = 0.05
                pt["v"][1] *= -0.3
        self.particles = [pt for pt in self.particles if pt["life"] > 0]
        self.damage_t = max(0.0, self.damage_t - dt * 1.6)
        self.hit_marker = max(0.0, self.hit_marker - dt)
        for mz in self.muzzles:
            mz[1] -= dt
        self.muzzles = [mz for mz in self.muzzles if mz[1] > 0]

    def on_player_damaged(self, payload):
        self.damage_t = 0.55

    def on_shell_hit(self, payload):
        if payload.get("target") == "enemy":
            self.hit_marker = 0.16

    # ---- 世界层绘制(粒子/炮口火光，投影后画在面片之后) ----
    def draw_world(self, screen, cam):
        f = cam.focal()
        for pt in self.particles:
            pr = cam.project(tuple(pt["p"]))
            if pr is None:
                continue
            sx, sy, z = pr
            r = max(1, int(f * pt["size"] * (pt["life"] / pt["max"]) / z))
            if r > 60:
                r = 60
            pygame.draw.circle(screen, pt["color"], (int(sx), int(sy)), r)
        for mz in self.muzzles:
            pr = cam.project(tuple(mz[0]))
            if pr is None:
                continue
            sx, sy, z = pr
            r = max(2, int(f * 0.9 / z))
            pygame.draw.circle(screen, (255, 230, 150), (int(sx), int(sy)), r)
            pygame.draw.circle(screen, C.FIRE, (int(sx), int(sy)), r * 2, 2)

    # ---- 屏幕层绘制(受击红晕 + 命中标记) ----
    def draw_screen(self, screen):
        if self.damage_t > 0:
            self.vignette.set_alpha(int(255 * min(1.0, self.damage_t / 0.55)))
            screen.blit(self.vignette, (0, 0))
        if self.hit_marker > 0:  # 命中敌人时的 X 形标记
            cx, cy = W // 2, H // 2
            for sx, sy in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
                pygame.draw.line(screen, (255, 92, 66),
                                 (cx + sx * 7, cy + sy * 7),
                                 (cx + sx * 15, cy + sy * 15), 3)


class HUD:
    """HUD：血条/弹药“当前/20”/击毁数/敌方存活/准星/装填进度，事件驱动更新。"""

    def __init__(self, fonts):
        self.fonts = fonts
        self.reset()

    def reset(self):
        self.ammo = CONFIG["player"]["ammo"]
        self.max_ammo = CONFIG["player"]["maxAmmo"]
        self.kills = 0
        self.hp = CONFIG["player"]["hp"]
        self.max_hp = CONFIG["player"]["hp"]
        self.hp_shake = 0.0

    # ---- 事件总线订阅回调 ----
    def on_shell_fired(self, payload):       # shell:fired → 弹药 -1
        if payload.get("team") == "player":
            self.ammo = max(0, self.ammo - 1)

    def on_tank_destroyed(self, payload):    # tank:destroyed → 击毁+1 且弹药+5
        if payload.get("team") == "enemy":
            self.kills += 1
            self.ammo = min(self.max_ammo, self.ammo + 5)

    def on_player_damaged(self, payload):    # player:damaged → 血条更新
        self.hp = max(0, int(payload.get("hp", self.hp)))
        self.hp_shake = 0.35

    def update(self, dt):
        self.hp_shake = max(0.0, self.hp_shake - dt)

    def draw(self, screen, player, enemies_alive, scoping):
        now = pygame.time.get_ticks() / 1000.0
        f_main = self.fonts.get(24)
        f_small = self.fonts.get(18)
        # ---- 左上：血条面板(受击抖动，低血量红色警示) ----
        shake_x = 0
        if self.hp_shake > 0:
            shake_x = int((random.random() * 2 - 1) * 6 * self.hp_shake)
        px, py = 24 + shake_x, 22
        panel = pygame.Surface((300, 74), pygame.SRCALPHA)
        panel.fill((16, 22, 16, 170))
        pygame.draw.rect(panel, C.HUD_ACCENT, (0, 0, 300, 74), 2)
        screen.blit(panel, (px - shake_x, py))
        low = self.hp <= self.max_hp * 0.3
        bar_col = C.HP_RED if low else C.HP_GREEN
        if low and int(now * 3) % 2 == 0:
            bar_col = (255, 120, 100)
        title = f_main.render("HP", True, C.HUD_TEXT)
        screen.blit(title, (px + 12, py + 8))
        pygame.draw.rect(screen, (40, 48, 40), (px + 56, py + 12, 200, 16))
        ratio = clamp(self.hp / self.max_hp, 0, 1)
        if ratio > 0:
            pygame.draw.rect(screen, bar_col, (px + 56, py + 12, int(200 * ratio), 16))
        pygame.draw.rect(screen, C.HUD_TEXT, (px + 56, py + 12, 200, 16), 1)
        hp_txt = f_small.render(f"{self.hp}/{self.max_hp}", True, C.HUD_TEXT)
        screen.blit(hp_txt, (px + 56, py + 34))
        if low:
            warn = f_small.render("血量告急！", True, C.HP_RED)
            screen.blit(warn, (px + 150, py + 34))
        # ---- 右上：弹药/击毁/敌方存活 ----
        panel2 = pygame.Surface((250, 108), pygame.SRCALPHA)
        panel2.fill((16, 22, 16, 170))
        pygame.draw.rect(panel2, C.HUD_ACCENT, (0, 0, 250, 108), 2)
        screen.blit(panel2, (W - 274, 22))
        ammo_col = C.HUD_TEXT if self.ammo > 5 else C.HP_RED
        lines = [
            (f"弹药  {self.ammo}/{self.max_ammo}", ammo_col),
            (f"击毁  {self.kills}/{CONFIG['enemy']['count']}", C.HUD_ACCENT),
            (f"敌方存活  {enemies_alive}", C.ENEMY_NAME),
        ]
        for i, (txt, col) in enumerate(lines):
            s = f_main.render(txt, True, col)
            screen.blit(s, (W - 258, 34 + i * 32))
        # ---- 中央准星 + 装填进度(开镜时由 ScopeOverlay 接管) ----
        cx, cy = W // 2, H // 2
        if not scoping:
            gap = 10 + int(14 * clamp(player.reload_timer / player.reload_time, 0, 1))
            col = C.WHITE
            pygame.draw.circle(screen, col, (cx, cy), 2)
            pygame.draw.line(screen, col, (cx - gap - 14, cy), (cx - gap, cy), 2)
            pygame.draw.line(screen, col, (cx + gap, cy), (cx + gap + 14, cy), 2)
            pygame.draw.line(screen, col, (cx, cy - gap - 14), (cx, cy - gap), 2)
            pygame.draw.line(screen, col, (cx, cy + gap), (cx, cy + gap + 14), 2)
        if player.alive and player.reload_timer > 0:
            prog = 1.0 - clamp(player.reload_timer / player.reload_time, 0, 1)
            pygame.draw.rect(screen, (40, 48, 40), (cx - 40, cy + 34, 80, 6))
            pygame.draw.rect(screen, C.HUD_ACCENT, (cx - 40, cy + 34, int(80 * prog), 6))
            tip = f_small.render("装填中…", True, C.HUD_TEXT)
            screen.blit(tip, (cx - tip.get_width() / 2, cy + 44))
        elif player.alive and self.ammo <= 0:
            tip = f_small.render("弹药耗尽！", True, C.HP_RED)
            screen.blit(tip, (cx - tip.get_width() / 2, cy + 40))


class ScopeOverlay:
    """瞄准镜：圆形遮罩 + 十字线 + 分划，FOV 60°→20° 插值由相机负责。"""

    def __init__(self, fonts):
        # 修复：SRCALPHA 粗环圆在 pygame-ce 中内外颠倒导致全屏黑幕；
        # 改用"整面压暗 + colorkey 挖透明圆孔"的可靠方案，圆内视野清晰可见
        self.radius = 260
        cx, cy = W // 2, H // 2
        hole_key = (255, 0, 255)  # 挖孔专用色
        self.mask = pygame.Surface((W, H))
        self.mask.fill((6, 10, 6))  # 圆外压暗层
        pygame.draw.circle(self.mask, hole_key, (cx, cy), self.radius)
        self.mask.set_colorkey(hole_key)  # 圆孔区域完全透明
        # 描边与分划画在挖孔之后，直接覆盖在可见区域上
        pygame.draw.circle(self.mask, (0, 0, 0), (cx, cy), self.radius, 3)
        pygame.draw.circle(self.mask, (96, 110, 96), (cx, cy), self.radius - 6, 2)
        # 十字线
        pygame.draw.line(self.mask, (10, 14, 10), (cx - self.radius, cy),
                         (cx + self.radius, cy), 2)
        pygame.draw.line(self.mask, (10, 14, 10), (cx, cy - self.radius),
                         (cx, cy + self.radius), 2)
        # 密位刻度
        for i in range(1, 6):
            d = i * 40
            pygame.draw.line(self.mask, (10, 14, 10), (cx + d, cy - 5), (cx + d, cy + 5), 2)
            pygame.draw.line(self.mask, (10, 14, 10), (cx - d, cy - 5), (cx - d, cy + 5), 2)
            pygame.draw.line(self.mask, (10, 14, 10), (cx - 5, cy + d), (cx + 5, cy + d), 2)
            pygame.draw.line(self.mask, (10, 14, 10), (cx - 5, cy - d), (cx + 5, cy - d), 2)
        self.fonts = fonts

    def draw(self, screen, t, cam):
        """t: 开镜插值系数 0~1。colorkey 孔不受 set_alpha 影响，圆内始终通透。"""
        if t <= 0.02:
            return
        self.mask.set_alpha(int(236 * clamp(t, 0, 1)))
        screen.blit(self.mask, (0, 0))
        deg = int(math.degrees(cam.fov))
        tip = self.fonts.get(18).render(f"FOV {deg}°  ×{60 // max(1, deg)} 瞄准", True, C.HUD_TEXT)
        tip.set_alpha(int(220 * t))
        screen.blit(tip, (W / 2 - tip.get_width() / 2, H / 2 + ScopeOverlay_R(self) + 12))


def ScopeOverlay_R(scope):
    return scope.radius


class Button:
    """通用按钮：命中检测 + hover 反馈。"""

    def __init__(self, rect, text, fonts, size=30):
        self.rect = pygame.Rect(rect)
        self.text = text
        self.font = fonts.get(size)

    def hit(self, pos):
        return self.rect.collidepoint(pos)

    def draw(self, screen, mouse_pos):
        hover = self.rect.collidepoint(mouse_pos)
        face = C.BTN_HOVER if hover else C.BTN_FACE
        pygame.draw.rect(screen, face, self.rect, border_radius=8)
        pygame.draw.rect(screen, C.BTN_BORDER, self.rect, 2, border_radius=8)
        s = self.font.render(self.text, True, C.WHITE)
        screen.blit(s, (self.rect.centerx - s.get_width() / 2,
                        self.rect.centery - s.get_height() / 2))


class UIManager:
    """主页 / 失败弹窗 / 胜利横幅 的绘制与按钮命中。"""

    LOSE_QUOTE = "若是巅峰留不住，那就重走来时路"
    GAME_TITLE = "库尔斯克会战浪尖战场"

    def __init__(self, fonts):
        self.fonts = fonts
        cx = W // 2
        self.btn_home_start = Button((cx - 160, 470, 320, 66), "进入战场", fonts, 34)
        self.btn_lose_home = Button((cx - 260, 470, 240, 60), "返回主页", fonts)
        self.btn_lose_retry = Button((cx + 20, 470, 240, 60), "重新挑战", fonts)
        self.btn_win_retry = Button((cx - 260, 470, 240, 60), "重新挑战", fonts)
        self.btn_win_home = Button((cx + 20, 470, 240, 60), "返回主页", fonts)

    # ---- 主页 ----
    def draw_home(self, screen, t):
        f_title = self.fonts.get(64)
        f_sub = self.fonts.get(26)
        f_small = self.fonts.get(20)
        # 标题（缓慢浮动，先画阴影再画正字）
        dy = math.sin(t * 1.2) * 6
        shadow = f_title.render(self.GAME_TITLE, True, C.BLACK)
        screen.blit(shadow, (W / 2 - shadow.get_width() / 2 + 3, 153 + dy))
        title = f_title.render(self.GAME_TITLE, True, C.TITLE_GOLD)
        screen.blit(title, (W / 2 - title.get_width() / 2, 150 + dy))
        sub = f_sub.render("—— 浪尖战场 · 钢铁洪流对决 ——", True, C.HUD_TEXT)
        screen.blit(sub, (W / 2 - sub.get_width() / 2, 236 + dy))
        # 操作说明卡片
        card = pygame.Surface((560, 180), pygame.SRCALPHA)
        card.fill((16, 22, 16, 190))
        pygame.draw.rect(card, C.HUD_ACCENT, (0, 0, 560, 180), 2)
        screen.blit(card, (W / 2 - 280, 280))
        help_lines = [
            "滚动滚轮移动（沿炮口方向，停滚即停）  空格：急停",
            "鼠标移动炮塔瞄准    左键 开炮",
            "右键按住 开瞄准镜(FOV 60°→20°)  ESC 结算返回主页",
            "击毁敌坦克+5发弹药    燃料桶爆炸可连锁击杀",
        ]
        for i, line in enumerate(help_lines):
            s = f_small.render(line, True, C.HUD_TEXT)
            screen.blit(s, (W / 2 - s.get_width() / 2, 300 + i * 36))
        self.btn_home_start.draw(screen, pygame.mouse.get_pos())
        foot = f_small.render("目标：击毁全部 4 辆敌方坦克（3 普通 + 1 精英）", True, C.HUD_ACCENT)
        screen.blit(foot, (W / 2 - foot.get_width() / 2, 570))

    # ---- 胜利横幅：文字严格为“胜利”，按钮约 2.0s 后浮现 ----
    def draw_win(self, screen, state_time, stats):
        t_in = clamp(state_time / 0.5, 0, 1)
        dy = -120 * (1 - t_in)
        banner = pygame.Surface((W, 170), pygame.SRCALPHA)
        pygame.draw.rect(banner, (20, 30, 18, 210), (0, 20, W, 130))
        pygame.draw.line(banner, C.TITLE_GOLD, (0, 22), (W, 22), 3)
        pygame.draw.line(banner, C.TITLE_GOLD, (0, 148), (W, 148), 3)
        win_txt = self.fonts.get(88).render("胜利", True, C.TITLE_GOLD)
        banner.blit(win_txt, (W / 2 - win_txt.get_width() / 2,
                              60 - win_txt.get_height() / 2))
        screen.blit(banner, (0, 130 + dy))
        info = self.fonts.get(24).render(
            f"击毁 {stats['kills']} 辆敌坦克    剩余弹药 {stats['ammo']}    剩余血量 {stats['hp']}",
            True, C.HUD_TEXT)
        info.set_alpha(int(255 * t_in))
        screen.blit(info, (W / 2 - info.get_width() / 2, 330))
        if state_time >= CONFIG["timing"]["winButtonDelay"]:
            a = clamp((state_time - CONFIG["timing"]["winButtonDelay"]) / 0.4, 0, 1)
            mp = pygame.mouse.get_pos()
            for btn in (self.btn_win_retry, self.btn_win_home):
                btn.rect.y = int(470 + 40 * (1 - a))
                btn.draw(screen, mp)

    # ---- 失败弹窗：死亡约 1.0s 后弹出 ----
    def draw_lose(self, screen, state_time):
        delay = CONFIG["timing"]["loseDialogDelay"]
        dark_a = int(170 * clamp(state_time / 0.6, 0, 1))
        dark = pygame.Surface((W, H), pygame.SRCALPHA)
        dark.fill((8, 6, 6, dark_a))
        screen.blit(dark, (0, 0))
        if state_time < delay:
            return
        a = clamp((state_time - delay) / 0.35, 0, 1)
        scale = 0.85 + 0.15 * a
        pw, ph = int(680 * scale), int(300 * scale)
        panel = pygame.Surface((pw, ph), pygame.SRCALPHA)
        panel.fill((26, 20, 18, int(235 * a)))
        pygame.draw.rect(panel, (168, 60, 48), (0, 0, pw, ph), 3)
        over = self.fonts.get(40).render("战斗失败", True, C.HP_RED)
        over.set_alpha(int(255 * a))
        panel.blit(over, (pw / 2 - over.get_width() / 2, 42))
        quote = self.fonts.get(30).render(self.LOSE_QUOTE, True, C.HUD_TEXT)
        quote.set_alpha(int(255 * a))
        panel.blit(quote, (pw / 2 - quote.get_width() / 2, 130))
        screen.blit(panel, (W / 2 - pw / 2, H / 2 - ph / 2 - 30))
        if a >= 1.0:
            mp = pygame.mouse.get_pos()
            self.btn_lose_home.draw(screen, mp)
            self.btn_lose_retry.draw(screen, mp)

    # ---- 点击处理：返回动作字符串或 None ----
    def click(self, state, pos, state_time):
        if state == STATE_HOME:
            if self.btn_home_start.hit(pos):
                return "start"
        elif state == STATE_WIN and state_time >= CONFIG["timing"]["winButtonDelay"]:
            if self.btn_win_retry.hit(pos):
                return "restart"
            if self.btn_win_home.hit(pos):
                return "home"
        elif (state == STATE_LOSE
                and state_time >= CONFIG["timing"]["loseDialogDelay"] + 0.35):
            # 门控与 draw_lose 按钮淡入完成条件对齐，避免淡入期“不可见但可点击”
            if self.btn_lose_home.hit(pos):
                return "home"
            if self.btn_lose_retry.hit(pos):
                return "restart"
        return None


# ============================================================
# ██  区块 7  Game 主控：布阵/碰撞/胜负判定/主循环/渲染
# ============================================================

LIGHT_DIR = (0.42, 0.82, 0.39)  # 光照方向(已归一化近似)


class Game:

    def __init__(self):
        self.screen = pygame.display.set_mode((W, H))
        pygame.display.set_caption("库尔斯克会战浪尖战场")
        self.clock = pygame.time.Clock()
        self.bus = EventBus()
        self.fonts = FontManager()
        self.sounds = SoundBank()
        self.camera = Camera()
        self.feedback = FeedbackSystem()
        self.hud = HUD(self.fonts)
        self.scope = ScopeOverlay(self.fonts)
        self.ui = UIManager(self.fonts)
        self.watermark = Watermark(self.fonts)
        self.sky = self._build_sky()
        # 右下角作者签名 LZH：预渲染缓存，避免每帧新建 Font/Surface
        self._signature = self.fonts.get(20).render("LZH", True, (236, 236, 230))
        self._signature.set_alpha(150)  # 半透明浅灰白，低调不抢眼
        self.state = STATE_HOME
        self.state_time = 0.0
        self.running = True
        self.rng = random.Random(CONFIG["seed"])
        self.ai_frozen = False
        self.player = None
        self.enemies = []
        self.obstacles = []
        self.projectiles = []
        self.decals = []   # 焦痕(爆炸残留)
        # 事件驱动自维护按键集合：保留事件增删机制（失焦清空等稳健性逻辑），
        # 玩家移动已改由滚轮事件维护 move_mode，不再依赖轮询
        self.held_keys = set()
        self._bind_events()
        self.setup_battle()
        pygame.mouse.set_visible(True)

    # ---------------- 事件绑定 ----------------
    def _bind_events(self):
        # HUD 订阅：shell:fired→弹药-1、tank:destroyed→击毁+1且弹药+5、player:damaged→血条
        self.bus.on("shell:fired", self.hud.on_shell_fired)
        self.bus.on("tank:destroyed", self.hud.on_tank_destroyed)
        self.bus.on("player:damaged", self.hud.on_player_damaged)
        self.bus.on("player:damaged", self.feedback.on_player_damaged)
        self.bus.on("shell:hit:tank", self.feedback.on_shell_hit)
        self.bus.on("tank:destroyed", self._on_tank_destroyed)

    def _on_tank_destroyed(self, payload):
        """击毁：爆炸粒子 + 焦痕 + 音效。"""
        x, z = payload["pos"]
        self.feedback.explosion((x, 1.4, z), big=True)
        self.decals.append((x, z, 3.4))
        self.camera.add_shake(0.45)
        self.sounds.play("explosion")

    # ---------------- 静态资源 ----------------
    def _build_sky(self):
        """预渲染天空渐变 + 太阳光晕。"""
        sky = pygame.Surface((W, H))
        steps = 60
        for i in range(steps):
            t = i / steps
            col = blend(C.SKY_TOP, C.SKY_BOTTOM, t)
            y0 = int(H * t)
            pygame.draw.rect(sky, col, (0, y0, W, H // steps + 2))
        pygame.draw.circle(sky, (255, 244, 210), (int(W * 0.76), 120), 46)
        pygame.draw.circle(sky, (255, 236, 180), (int(W * 0.76), 120), 70, 2)
        return sky

    # ---------------- 布阵(固定随机种子) ----------------
    ENEMY_SPAWNS = ((-28, 82), (-9, 76), (12, 84), (30, 78))
    PLAYER_SPAWN = (0.0, -85.0)

    def setup_battle(self):
        """重置战场：玩家 Z=-85，敌人 Z≈+80，出生点周围 15m 净空。"""
        self.rng = random.Random(CONFIG["seed"])
        self.player = PlayerTank()
        self.enemies = []
        for i, sp in enumerate(self.ENEMY_SPAWNS):
            self.enemies.append(EnemyTank(list(sp), elite=(i == 3), rng=self.rng))
        self.obstacles = self._gen_obstacles()
        self.projectiles = []
        self.decals = []
        self.feedback.particles.clear()
        self.feedback.muzzles.clear()
        self.feedback.damage_t = 0.0
        self.hud.reset()
        self.ai_frozen = False
        self.camera.pos = [0.0, 4.0, -93.0]
        self.camera.yaw = 0.0
        self.camera.scope_t = 0.0
        self.camera.scoping = False
        self.camera.shake = 0.0

    def _gen_obstacles(self):
        """固定种子生成障碍：岩石×8/硚堡×3/木箱×12/燃料桶×6，互不重叠。"""
        obs_cfg = CONFIG["obstacles"]
        clearance = CONFIG["spawnClearance"]
        kinds = (["rock"] * obs_cfg["rock"] + ["bunker"] * obs_cfg["bunker"]
                 + ["crate"] * obs_cfg["crate"] + ["barrel"] * obs_cfg["barrel"])
        self.rng.shuffle(kinds)
        result = []
        spawns = [self.PLAYER_SPAWN] + list(self.ENEMY_SPAWNS)
        for kind in kinds:
            for _ in range(300):  # 反复重试直到找到合法位置
                x = self.rng.uniform(-46, 46)
                z = self.rng.uniform(-72, 72)
                ob = Obstacle(kind, x, z)
                half = max(ob.sx, ob.sz) * 0.5
                ok = True
                for sx, sz in spawns:  # 出生点净空 15m
                    if dist2d(x, z, sx, sz) < clearance + half:
                        ok = False
                        break
                if ok:
                    for other in result:  # 与已有障碍保持间距
                        ohalf = max(other.sx, other.sz) * 0.5
                        if dist2d(x, z, other.x, other.z) < half + ohalf + 2.5:
                            ok = False
                            break
                if ok:
                    result.append(ob)
                    break
        return result

    # ---------------- 战斗流程 ----------------
    def start_battle(self):
        self.setup_battle()
        self.state = STATE_PLAYING
        self.state_time = 0.0
        pygame.event.clear()      # 清空按键/事件缓存
        self.held_keys.clear()    # 同步清空自维护按键集合
        pygame.mouse.set_visible(False)
        # 抓取鼠标：锁定光标在窗口内，保证鼠标瞄准/滚轮移动稳定
        try:
            pygame.event.set_grab(True)
            pygame.mouse.set_visible(False)
        except Exception:
            pass
        self.sounds.play("click")

    def restart(self):
        self.start_battle()

    def back_home(self):
        self.state = STATE_HOME
        self.state_time = 0.0
        pygame.event.clear()
        self.held_keys.clear()    # 返回主页清空按键集合
        self.player.move_mode = 0  # 清空滚轮移动状态
        self.player.move_timer = 0.0
        pygame.mouse.set_visible(True)
        try:
            pygame.event.set_grab(False)  # 离开战斗释放鼠标抓取
        except Exception:
            pass
        self.camera.scoping = False
        self.sounds.play("click")

    def spawn_shell(self, tank):
        self.projectiles.append(Projectile(tank))

    # ---------------- 胜负判定：先查 WIN 后查 LOSE ----------------
    def check_result(self):
        if self.state != STATE_PLAYING:
            return
        enemies_alive = sum(1 for e in self.enemies if e.alive)
        # ① 先查 WIN：击毁全部敌坦克；同帧双满足时判 WIN
        if enemies_alive == 0:
            self._enter_win()
            return
        # ② 后查 LOSE：血量归零，或 弹药=0 且无玩家炮弹在飞行 且仍有存活敌人
        player_shell_flying = any(
            s.alive and s.team == "player" for s in self.projectiles)
        if (self.player.hp <= 0
                or (self.player.ammo == 0 and not player_shell_flying
                    and enemies_alive > 0)):
            self._enter_lose()

    def _enter_win(self):
        """WIN：清空全部在途炮弹、冻结 AI 开火。"""
        self.projectiles.clear()
        self.ai_frozen = True
        for e in self.enemies:
            e.frozen = True
        self.state = STATE_WIN
        self.state_time = 0.0
        self.camera.scoping = False   # 强制退出开镜
        pygame.event.clear()          # 清空按键缓存
        self.held_keys.clear()        # 同步清空自维护按键集合
        pygame.mouse.set_visible(True)
        self.bus.emit("game:win")
        self.sounds.play("win")

    def _enter_lose(self):
        if self.player.alive:  # 血量归零时补一个死亡爆炸
            self.feedback.explosion((self.player.pos[0], 1.4, self.player.pos[1]))
        self.state = STATE_LOSE
        self.state_time = 0.0
        self.camera.scoping = False
        pygame.event.clear()
        self.held_keys.clear()    # 同步清空自维护按键集合
        pygame.mouse.set_visible(True)
        self.bus.emit("game:lose")
        self.sounds.play("lose")

    # ---------------- 炮弹碰撞(子步内逐段检测) ----------------
    def collide_projectile(self, shell):
        r = shell.radius
        targets = ([e for e in self.enemies if e.alive] if shell.team == "player"
                   else ([self.player] if self.player.alive else []))
        for t in targets:
            if (dist2d(shell.pos[0], shell.pos[2], t.pos[0], t.pos[1])
                    <= Tank.RADIUS + r and shell.pos[1] < 3.4):
                shell.alive = False
                source = "player" if shell.team == "player" else "enemy"
                self.bus.emit("shell:hit:tank", team=t.team, target=t.team,
                              source=source, pos=tuple(shell.pos))
                t.take_damage(shell.damage, source=source, bus=self.bus)
                self.feedback.spark(shell.pos)
                self.sounds.play("hit")
                return True
        for ob in self.obstacles:
            if not ob.alive:
                continue
            if ob.contains(shell.pos[0], shell.pos[2], r) and shell.pos[1] < ob.sy + r:
                shell.alive = False
                if ob.kind == "barrel":
                    self.explode_barrel(ob)
                elif ob.kind == "crate":
                    ob.alive = False
                    self.feedback.explosion((ob.x, 1.0, ob.z), big=False)
                    self.sounds.play("hit")
                else:
                    self.feedback.impact(shell.pos)
                    self.sounds.play("hit")
                return True
        return False

    # ---------------- 燃料桶爆炸(范围伤害 + 连锁) ----------------
    def explode_barrel(self, ob, source="player"):
        if not ob.alive:
            return
        ob.alive = False
        fb = CONFIG["fuelBarrel"]
        R, dmg = fb["explodeRadius"], fb["damage"]
        self.feedback.explosion((ob.x, 1.4, ob.z), big=True)
        self.decals.append((ob.x, ob.z, 2.6))
        self.camera.add_shake(0.5)
        self.sounds.play("explosion")
        # 范围内敌坦克受伤：source=player → 计入玩家击毁数并触发弹药奖励
        for t in self.enemies:
            if not t.alive:
                continue
            d = dist2d(ob.x, ob.z, t.pos[0], t.pos[1])
            if d <= R:
                t.take_damage(dmg * (1.0 - 0.5 * d / R), source="player", bus=self.bus)
        p = self.player
        if p.alive:
            d = dist2d(ob.x, ob.z, p.pos[0], p.pos[1])
            if d <= R:
                p.take_damage(dmg * 0.75, source="barrel", bus=self.bus)
        # 连锁引爆其他燃料桶、摧毁范围内木箱
        for ob2 in self.obstacles:
            if not ob2.alive:
                continue
            d = dist2d(ob.x, ob.z, ob2.x, ob2.z)
            if ob2.kind == "barrel" and d <= R:
                self.explode_barrel(ob2, source=source)
            elif ob2.kind == "crate" and d <= R:
                ob2.alive = False
                self.feedback.explosion((ob2.x, 1.0, ob2.z), big=False)

    # ---------------- 坦克碰撞：AABB 推出 + 边界钳制 ----------------
    def resolve_collisions(self):
        tanks = [self.player] + [e for e in self.enemies if e.alive]
        bound = Tank.RADIUS - 0.1
        for t in tanks:
            t.pos[0] = clamp(t.pos[0], -HALF_W + bound, HALF_W - bound)
            t.pos[1] = clamp(t.pos[1], -HALF_L + bound, HALF_L - bound)
        for t in tanks:
            for ob in self.obstacles:
                if not ob.alive:
                    continue
                if ob.kind == "barrel":
                    d = dist2d(t.pos[0], t.pos[1], ob.x, ob.z)
                    rr = Tank.RADIUS + CONFIG["fuelBarrel"]["radius"]
                    if 1e-4 < d < rr:
                        push = (rr - d)
                        t.pos[0] += (t.pos[0] - ob.x) / d * push
                        t.pos[1] += (t.pos[1] - ob.z) / d * push
                else:
                    dx = t.pos[0] - ob.x
                    dz = t.pos[1] - ob.z
                    pen_x = ob.sx * 0.5 + Tank.RADIUS - abs(dx)
                    pen_z = ob.sz * 0.5 + Tank.RADIUS - abs(dz)
                    if pen_x > 0 and pen_z > 0:
                        if pen_x < pen_z:  # 沿最小穿透轴推出
                            t.pos[0] += pen_x if dx >= 0 else -pen_x
                        else:
                            t.pos[1] += pen_z if dz >= 0 else -pen_z
        # 坦克互撞：包围球推出
        for i in range(len(tanks)):
            for j in range(i + 1, len(tanks)):
                a, b = tanks[i], tanks[j]
                d = dist2d(a.pos[0], a.pos[1], b.pos[0], b.pos[1])
                rr = Tank.RADIUS * 2
                if 1e-4 < d < rr:
                    push = (rr - d) * 0.5
                    nx = (a.pos[0] - b.pos[0]) / d
                    nz = (a.pos[1] - b.pos[1]) / d
                    a.pos[0] += nx * push
                    a.pos[1] += nz * push
                    b.pos[0] -= nx * push
                    b.pos[1] -= nz * push

    # ---------------- 输入处理(事件驱动按键集合 + 鼠标事件) ----------------
    def handle_events(self):
        for ev in pygame.event.get():
            # 按键状态一律走事件增删，不依赖 pygame.key.get_pressed()
            if ev.type == pygame.KEYDOWN:
                self.held_keys.add(ev.key)
            elif ev.type == pygame.KEYUP:
                self.held_keys.discard(ev.key)
            # 失焦/鼠标离开窗口：清空按键集合，防止切窗回来仍在移动
            # pygame-ce 中窗口事件是独立事件类型（无 .event 子字段）
            if ev.type in (getattr(pygame, "WINDOWFOCUSLOST", -1),
                           getattr(pygame, "WINDOWLEAVE", -1),
                           getattr(pygame, "WINDOWMINIMIZED", -1)):
                self.held_keys.clear()
            if ev.type == pygame.QUIT:
                self.running = False
            elif ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
                if self.state == STATE_HOME:
                    self.running = False
                elif self.state in (STATE_WIN, STATE_LOSE):
                    self.back_home()
            if self.state == STATE_PLAYING:
                # 键位调整说明：原“空格开火”改为“空格刹车”，开火仅保留鼠标左键，
                # 避免与滚轮移动的键位冲突
                if ev.type == pygame.KEYDOWN and ev.key == pygame.K_SPACE:
                    self.player.move_mode = 0          # 急停刹车
                    self.player.move_speed_cur = 0.0   # 立即停驻
                    self.player.move_timer = 0.0       # 同步清空滚动窗口
                elif ev.type == pygame.MOUSEWHEEL and self.player.alive:
                    # 滚轮移动（滚动才走、停滚即停）：前滚→前进(+1)，后滚→倒退(-1)，
                    # 反向滚动即切换；每次滚动刷新滚动窗口，停滚超窗自动停下
                    if ev.y > 0:
                        self.player.move_mode = 1
                        self.player.move_timer = PlayerTank.WHEEL_WINDOW
                    elif ev.y < 0:
                        self.player.move_mode = -1
                        self.player.move_timer = PlayerTank.WHEEL_WINDOW
                elif ev.type == pygame.MOUSEMOTION:
                    self.player.handle_aim(ev.rel[0], ev.rel[1],
                                           self.camera.scoping)
                elif ev.type == pygame.MOUSEBUTTONDOWN:
                    if ev.button == 1:
                        self.player.try_fire(self)
                    elif ev.button == 3:
                        self.camera.scoping = True
                elif ev.type == pygame.MOUSEBUTTONUP and ev.button == 3:
                    self.camera.scoping = False
            else:
                if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                    action = self.ui.click(self.state, ev.pos, self.state_time)
                    if action == "start" or action == "restart":
                        self.start_battle()
                    elif action == "home":
                        self.back_home()

    def handle_held_keys(self, dt):
        """持续输入：玩家移动由滚轮事件维护 move_mode + 滚动窗口(move_timer)，
        在 handle_move 内插值推进，停滚超窗自动停下。
        WASD 已彻底移除（按下无任何游戏效果）；空格为急停(KEYDOWN 即发即停)，
        开火仅保留鼠标左键。"""
        if self.player.alive:
            self.player.handle_move(dt)

    # ---------------- 逻辑更新 ----------------
    def update(self, dt):
        if self.state == STATE_PLAYING:
            self.handle_held_keys(dt)
            self.player.update_timers(dt)
            for e in self.enemies:
                e.update_timers(dt)
                if e.alive and not self.ai_frozen:
                    e.update_ai(dt, self)
            for s in self.projectiles:
                s.update(dt, self)
            self.projectiles = [s for s in self.projectiles if s.alive]
            self.resolve_collisions()
            self.camera.update_follow(self.player, dt)
            self.check_result()
        elif self.state == STATE_HOME:
            # 主页：相机缓缓鸟瞰战场
            t = self.state_time
            self.camera.pos = [math.sin(t * 0.12) * 26.0, 12.0, -66.0]
            self.camera.yaw = math.atan2(-self.camera.pos[0], 30.0)
            self.camera.pitch = 0.30
            self.camera.fov = self.camera.base_fov
        self.feedback.update(dt)
        self.camera.update_shake(dt)
        self.hud.update(dt)

    # ---------------- 世界渲染 ----------------
    def draw_ground_cells(self, screen):
        """草地棋盘格 + 战场边界，增强 3D 纵深感。"""
        cam = self.camera
        cell = 10.0
        cols = int(CONFIG["battlefield"]["width"] // cell)
        rows = int(CONFIG["battlefield"]["length"] // cell)
        x0, z0 = -HALF_W, -HALF_L
        for i in range(cols):
            for j in range(rows):
                cx_ = x0 + i * cell + cell * 0.5
                cz_ = z0 + j * cell + cell * 0.5
                if cam.to_camera((cx_, 0.0, cz_))[2] < 3.0:
                    continue  # 相机后方/过近，跳过
                corners = ((x0 + i * cell, 0.0, z0 + j * cell),
                           (x0 + (i + 1) * cell, 0.0, z0 + j * cell),
                           (x0 + (i + 1) * cell, 0.0, z0 + (j + 1) * cell),
                           (x0 + i * cell, 0.0, z0 + (j + 1) * cell))
                pts = []
                ok = True
                for cp in corners:
                    pr = cam.project(cp)
                    if pr is None:
                        ok = False
                        break
                    pts.append((pr[0], pr[1]))
                if not ok:
                    continue
                xs = [p[0] for p in pts]
                ys = [p[1] for p in pts]
                if max(xs) < 0 or min(xs) > W or max(ys) < 0 or min(ys) > H:
                    continue
                color = C.GRASS_A if (i + j) % 2 == 0 else C.GRASS_B
                pygame.draw.polygon(screen, color, pts)
        # 焦痕
        f = cam.focal()
        for dx, dz, dr in self.decals:
            pr = cam.project((dx, 0.05, dz))
            if pr is None:
                continue
            rr = max(2, int(f * dr / pr[2]))
            pygame.draw.ellipse(screen, (46, 44, 38),
                                (int(pr[0] - rr), int(pr[1] - rr * 0.5),
                                 rr * 2, rr))
        # 地图边界线(四边依次连接，某角落在相机后方时跳过该段)
        edge_pts = []
        for (ex, ez) in ((-HALF_W, -HALF_L), (HALF_W, -HALF_L),
                         (HALF_W, HALF_L), (-HALF_W, HALF_L), (-HALF_W, -HALF_L)):
            pr = cam.project((ex, 0.12, ez))
            edge_pts.append((pr[0], pr[1]) if pr else None)
        for a, b in zip(edge_pts, edge_pts[1:]):
            if a and b:
                pygame.draw.line(screen, C.GRASS_EDGE, a, b, 3)

    def collect_faces(self):
        """收集全部可见面片(障碍物/残骸/坦克)，画家算法按深度排序。"""
        faces = []
        for ob in self.obstacles:
            if ob.alive:
                faces += ob.get_faces()
        for e in self.enemies:
            faces += e.get_faces(e.hull_faces, e.turret_faces)
        faces += self.player.get_faces(self.player.hull_faces, self.player.turret_faces)
        return faces

    def draw_faces(self, screen, faces):
        cam = self.camera
        cam_pos = (cam.pos[0], cam.pos[1], cam.pos[2])
        drawn = []
        for verts, color in faces:
            v0, v1, v2 = verts[0], verts[1], verts[2]
            e1 = (v1[0] - v0[0], v1[1] - v0[1], v1[2] - v0[2])
            e2 = (v2[0] - v1[0], v2[1] - v1[1], v2[2] - v1[2])
            nx = e1[1] * e2[2] - e1[2] * e2[1]
            ny = e1[2] * e2[0] - e1[0] * e2[2]
            nz = e1[0] * e2[1] - e1[1] * e2[0]
            cx_ = sum(v[0] for v in verts) / len(verts)
            cy_ = sum(v[1] for v in verts) / len(verts)
            cz_ = sum(v[2] for v in verts) / len(verts)
            # 背面剔除：法线与视线同向则不可见
            if (nx * (cx_ - cam_pos[0]) + ny * (cy_ - cam_pos[1])
                    + nz * (cz_ - cam_pos[2])) >= 0:
                continue
            pts = []
            depth_sum = 0.0
            ok = True
            for v in verts:
                pr = cam.project(v)
                if pr is None:
                    ok = False
                    break
                pts.append((pr[0], pr[1]))
                depth_sum += pr[2]
            if not ok:
                continue
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            if max(xs) < -40 or min(xs) > W + 40 or max(ys) < -40 or min(ys) > H + 40:
                continue
            # 简单光照：法线点乘光向 → 明暗
            nl = math.sqrt(nx * nx + ny * ny + nz * nz) + 1e-6
            dot = max(0.0, (nx * LIGHT_DIR[0] + ny * LIGHT_DIR[1]
                            + nz * LIGHT_DIR[2]) / nl)
            drawn.append((depth_sum / len(verts), pts, shade(color, 0.55 + 0.5 * dot)))
        drawn.sort(key=lambda item: item[0], reverse=True)  # 远 → 近
        for _, pts, color in drawn:
            pygame.draw.polygon(screen, color, pts)

    def draw_projectiles(self, screen):
        cam = self.camera
        f = cam.focal()
        for s in self.projectiles:
            pr = cam.project(tuple(s.pos))
            if pr is None:
                continue
            r = clamp(int(f * 0.3 / pr[2]), 2, 9)
            p0 = cam.project(tuple(s.prev))
            col = (255, 240, 170) if s.team == "player" else (255, 150, 90)
            if p0 is not None:
                pygame.draw.line(screen, col, (p0[0], p0[1]), (pr[0], pr[1]),
                                 max(1, r // 2))
            pygame.draw.circle(screen, col, (int(pr[0]), int(pr[1])), r)

    def draw_enemy_bars(self, screen):
        """敌方坦克头顶血条 + 精英标记。"""
        cam = self.camera
        f = cam.focal()
        for e in self.enemies:
            if not e.alive:
                continue
            pr = cam.project((e.pos[0], 3.6, e.pos[1]))
            if pr is None:
                continue
            bw = clamp(int(f * 3.4 / pr[2]), 10, 90)
            bh = max(3, bw // 14)
            x, y = pr[0] - bw / 2, pr[1]
            pygame.draw.rect(screen, (30, 30, 28), (x, y, bw, bh))
            ratio = clamp(e.hp / e.max_hp, 0, 1)
            if ratio > 0:
                pygame.draw.rect(screen, C.HP_RED, (x, y, int(bw * ratio), bh))
            pygame.draw.rect(screen, C.BLACK, (x, y, bw, bh), 1)
            if e.elite:
                tag = self.fonts.get(14).render("精英", True, C.ENEMY_NAME)
                screen.blit(tag, (pr[0] - tag.get_width() / 2, y - 16))

    def draw_world(self, screen):
        cam = self.camera
        # 天空 + 地平线以下铺地色
        screen.blit(self.sky, (0, 0))
        hy = int(clamp(cam.horizon_y(), 0, H))
        if hy < H:
            pygame.draw.rect(screen, C.GRASS_A, (0, hy, W, H - hy))
        self.draw_ground_cells(screen)
        self.watermark.draw_ground(screen, cam)   # 地面层水印
        faces = self.collect_faces()
        self.draw_faces(screen, faces)            # 画家算法主体
        self.draw_projectiles(screen)
        self.feedback.draw_world(screen, cam)     # 粒子/炮口火光
        self.draw_enemy_bars(screen)

    # ---------------- UI 渲染 ----------------
    def render(self):
        screen = self.screen
        self.draw_world(screen)
        if self.state == STATE_HOME:
            dark = pygame.Surface((W, H), pygame.SRCALPHA)
            dark.fill((10, 14, 10, 120))
            screen.blit(dark, (0, 0))
            self.ui.draw_home(screen, self.state_time)
        elif self.state == STATE_PLAYING:
            self.feedback.draw_screen(screen)
            self.scope.draw(screen, self.camera.scope_t, self.camera)
            self.hud.draw(screen, self.player,
                          sum(1 for e in self.enemies if e.alive),
                          self.camera.scope_t > 0.5)
        elif self.state == STATE_WIN:
            self.feedback.draw_screen(screen)
            self.hud.draw(screen, self.player, 0, False)
            self.ui.draw_win(screen, self.state_time,
                             {"kills": self.hud.kills,
                              "ammo": self.hud.ammo,
                              "hp": self.hud.hp})
        elif self.state == STATE_LOSE:
            self.feedback.draw_screen(screen)
            self.hud.draw(screen, self.player,
                          sum(1 for e in self.enemies if e.alive), False)
            self.ui.draw_lose(screen, self.state_time)
        self.watermark.draw_screen(screen)   # 屏幕层水印(四状态全程)
        # 右下角作者签名 LZH(四状态常驻；敌方存活 HUD 在右上角，互不重叠)
        screen.blit(self._signature,
                    (W - 12 - self._signature.get_width(),
                     H - 12 - self._signature.get_height()))
        pygame.display.flip()

    # ---------------- 主循环 ----------------
    def run(self):
        try:
            while self.running:
                dt = min(self.clock.tick(CONFIG["window"]["fps"]) / 1000.0, 0.05)
                self.state_time += dt
                self.handle_events()
                self.update(dt)
                self.render()
            pygame.quit()
        except Exception:
            # 顶层异常兼容：写入 crash_log.txt 便于排查
            err = traceback.format_exc()
            try:
                with open(crash_log_path(), "w", encoding="utf-8") as fp:
                    fp.write(err)
            except Exception:
                pass
            pygame.quit()
            raise


# ============================================================
# ██  区块 8  程序入口：初始化 → 音频降级兼容 → Game().run()
# ============================================================

def crash_log_path():
    """崩溃日志路径：冻结 exe(--onefile) 下写到 exe 所在目录，
    避免写入 _MEIPASS 临时目录（退出即被删除）；脚本模式写到脚本目录。"""
    if getattr(sys, "frozen", False):
        return os.path.join(os.path.dirname(os.path.abspath(sys.executable)),
                            "crash_log.txt")
    return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "crash_log.txt")


def main():
    try:
        pygame.mixer.pre_init(22050, -16, 1, 512)  # 22.05kHz 16bit 单声道
    except Exception:
        pass
    pygame.init()
    try:
        pygame.mixer.init(22050, -16, 1, 512)
    except Exception:
        pass  # 无声卡环境降级：静音运行
    Game().run()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        err = traceback.format_exc()
        try:
            with open(crash_log_path(), "w", encoding="utf-8") as fp:
                fp.write(err)
        except Exception:
            pass
        try:
            # windowed 冻结 exe 中 sys.stderr 可能为 None，需防护
            if sys.stderr:
                print(err, file=sys.stderr)
        except Exception:
            pass
        sys.exit(1)

