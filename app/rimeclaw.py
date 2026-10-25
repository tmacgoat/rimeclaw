#!/usr/bin/env python3
"""Rimeclaw - an Emberfall desktop pet that walks around your screen and roasts you.
Runs on PyQt6. Under GNOME Wayland it uses XWayland (QT_QPA_PLATFORM=xcb) so it can
position itself, stay on top and be click-through outside the sprite."""
import os, sys, json, random, math, time, subprocess, shutil, glob, signal, collections, re

APP_DIR = os.path.dirname(os.path.abspath(__file__))
SLUG = 'rimeclaw'
CONF_DIR = os.path.join(os.environ.get('XDG_CONFIG_HOME', os.path.expanduser('~/.config')), SLUG)
CONF = os.path.join(CONF_DIR, 'settings.json')

# ---- platform: prefer XWayland on Wayland sessions -------------------------------------
STATIONARY = False
if 'QT_QPA_PLATFORM' not in os.environ:
    if os.environ.get('DISPLAY'):
        os.environ['QT_QPA_PLATFORM'] = 'xcb'
    elif os.environ.get('WAYLAND_DISPLAY'):
        os.environ['QT_QPA_PLATFORM'] = 'wayland'
if os.environ.get('QT_QPA_PLATFORM', '').startswith('wayland') or os.environ.get('RIMECLAW_STATIONARY') == '1':
    STATIONARY = True   # pure Wayland: cannot place windows, so the pet lives in its own little window
os.environ.setdefault('QT_LOGGING_RULES', 'qt.qpa.*=false')

from PyQt6.QtCore import Qt, QTimer, QPointF, QPoint, QRectF, QRect, QProcess, QElapsedTimer
from PyQt6.QtGui import (QGuiApplication, QPainter, QPixmap, QImage, QTransform, QColor, QFont, QFontMetrics,
                         QRegion, QBitmap, QPainterPath, QPen, QBrush, QIcon, QAction, QActionGroup, QCursor, QPolygon)
from PyQt6.QtWidgets import QApplication, QWidget, QMenu, QSystemTrayIcon
from PyQt6.QtNetwork import QLocalServer, QLocalSocket

DEFAULTS = {'pet': 'dragon', 'muted': False, 'clean': False, 'freq_min': 7, 'size': 140,
            'rant_share': 0.25, 'reactions': True, 'volume': 1.0}
FREQS = [(3, 'Every ~3 minutes'), (5, 'Every ~5 minutes'), (7, 'Every ~7 minutes (default)'),
         (12, 'Every ~12 minutes'), (20, 'Every ~20 minutes'), (45, 'Every ~45 minutes'), (0, 'Only when I ask')]
SIZES = [(110, 'Small'), (140, 'Medium'), (180, 'Large')]
PETS = {'dragon': 'Rimeclaw the frost dragon', 'goblin': 'Skarn the goblin'}

def load_settings():
    s = dict(DEFAULTS)
    try:
        s.update(json.load(open(CONF)))
    except Exception:
        pass
    return s

def save_settings(s):
    try:
        os.makedirs(CONF_DIR, exist_ok=True)
        tmp = CONF + '.tmp'
        json.dump(s, open(tmp, 'w'), indent=1); os.replace(tmp, CONF)
    except Exception as e:
        print('settings save failed:', e, file=sys.stderr)

# ---- audio --------------------------------------------------------------------------------
class Player:
    def __init__(self):
        self.proc = None
        self.cmd = None
        for name, mk in [('pw-play', lambda f, v: ['pw-play', '--volume', str(v), f]),
                         ('paplay', lambda f, v: ['paplay', '--volume', str(int(65536 * v)), f]),
                         ('ffplay', lambda f, v: ['ffplay', '-nodisp', '-autoexit', '-loglevel', 'quiet', '-volume', str(int(100 * v)), f]),
                         ('mpv', lambda f, v: ['mpv', '--no-video', '--really-quiet', f'--volume={int(100 * v)}', f]),
                         ('ogg123', lambda f, v: ['ogg123', '-q', f])]:
            if shutil.which(name):
                self.cmd = mk; self.name = name; break
    def play(self, f, vol=1.0):
        self.stop()
        if not self.cmd or not os.path.exists(f):
            return False
        try:
            self.proc = subprocess.Popen(self.cmd(f, vol), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except Exception:
            return False
    def stop(self):
        if self.proc and self.proc.poll() is None:
            try: self.proc.terminate()
            except Exception: pass
        self.proc = None

# ---- lines --------------------------------------------------------------------------------
class Lines:
    def __init__(self):
        self.all = json.load(open(os.path.join(APP_DIR, 'lines.json')))
        self.recent = collections.deque(maxlen=60)
        self.dur = {}
        for pet in self.all:
            try:
                self.dur[pet] = json.load(open(os.path.join(APP_DIR, 'voice', pet, 'index.json')))['durations']
            except Exception:
                self.dur[pet] = {}
    def pick(self, pet, cat, clean):
        pool = [l for l in self.all[pet] if l['cat'] == cat and
                (l['mode'] == 'both' or l['mode'] == ('clean_only' if clean else 'vulgar'))]
        if not pool:
            return None
        if not clean and cat == 'roast':   # R-rated default: favor the filthy ones a little
            pool = pool + [l for l in pool if l['mode'] == 'vulgar']
        fresh = [l for l in pool if l['id'] not in self.recent] or pool
        l = random.choice(fresh)
        self.recent.append(l['id'])
        return l

# ---- speech bubble ------------------------------------------------------------------------
def bubble_font():
    f = QFont('Cantarell'); f.setPointSizeF(11.5); f.setWeight(QFont.Weight.DemiBold)
    return f

def bubble_layout(text, maxw):
    fm = QFontMetrics(bubble_font())
    r = fm.boundingRect(QRect(0, 0, maxw, 4000), int(Qt.TextFlag.TextWordWrap), text)
    return r.width() + 28, r.height() + 22

def paint_bubble(p, rect, text, shown, tail_x, tail_down, accent):
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath(); path.addRoundedRect(rect, 14, 14)
    t = QPainterPath()
    tx = max(rect.left() + 18, min(rect.right() - 18, tail_x))
    if tail_down:
        t.moveTo(tx - 10, rect.bottom() - 1); t.lineTo(tx + 10, rect.bottom() - 1); t.lineTo(tx + 2, rect.bottom() + 13)
    else:
        t.moveTo(tx - 10, rect.top() + 1); t.lineTo(tx + 10, rect.top() + 1); t.lineTo(tx + 2, rect.top() - 13)
    t.closeSubpath(); path = path.united(t)
    p.setPen(QPen(accent, 2.2)); p.setBrush(QColor(22, 20, 34, 238)); p.drawPath(path)
    p.setFont(bubble_font())
    inner = rect.adjusted(14, 11, -14, -11)
    # draw full text invisibly for stable layout, reveal visible part
    p.setPen(QColor(240, 244, 255))
    p.drawText(inner, int(Qt.TextFlag.TextWordWrap), text[:shown] + '\u00a0' * 0)

class Bubble(QWidget):
    def __init__(self):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.X11BypassWindowManagerHint |
                         Qt.WindowType.WindowTransparentForInput | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.text = ''; self.shown = 0; self.tail_x = 20; self.tail_down = True; self.accent = QColor(120, 200, 255)
    def set_text(self, text, accent):
        self.text = text; self.shown = 0; self.accent = accent
        maxw = 360 if len(text) > 160 else 280
        w, h = bubble_layout(text, maxw)
        self.bw, self.bh = w, h
        self.resize(w + 4, h + 18)
    def place(self, anchor_x, top_y, bottom_y, scr):
        w, h = self.width(), self.height()
        x = int(anchor_x - w / 2)
        x = max(scr.left() + 4, min(scr.right() - w - 4, x))
        if top_y - h - 2 >= scr.top():
            y = top_y - h - 2; self.tail_down = True
        else:
            y = bottom_y + 2; self.tail_down = False
        self.tail_x = anchor_x - x
        if (x, y) != (self.x(), self.y()):
            self.move(x, y)
        self.update_mask()
    def update_mask(self):
        r = self.body_rect()
        reg = QRegion(r.toRect().adjusted(-2, -2, 3, 3), QRegion.RegionType.Rectangle)
        tx = int(max(r.left() + 18, min(r.right() - 18, self.tail_x)))
        if self.tail_down:
            tri = QPolygon([QPoint(tx - 12, int(r.bottom()) - 2), QPoint(tx + 12, int(r.bottom()) - 2), QPoint(tx + 2, int(r.bottom()) + 16)])
        else:
            tri = QPolygon([QPoint(tx - 12, int(r.top()) + 2), QPoint(tx + 12, int(r.top()) + 2), QPoint(tx + 2, int(r.top()) - 16)])
        self.setMask(reg.united(QRegion(tri)))
    def body_rect(self):
        top = 2 if self.tail_down else 16
        return QRectF(2, top, self.bw, self.bh)
    def paintEvent(self, e):
        p = QPainter(self)
        paint_bubble(p, self.body_rect(), self.text, self.shown, self.tail_x, self.tail_down, self.accent)

# ---- the pet ------------------------------------------------------------------------------
FRAMES = ['idle', 'walk1', 'walk2', 'sit', 'sleep', 'fall', 'drag', 'laugh']

class Pet(QWidget):
    G = 2200.0
    def __init__(self, app):
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus
        if not STATIONARY:
            flags |= Qt.WindowType.Tool
            if os.environ.get('RIMECLAW_NO_BYPASS') != '1':
                flags |= Qt.WindowType.X11BypassWindowManagerHint
        super().__init__(None, flags)
        self.app = app
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setWindowTitle('Rimeclaw')
        self.s = load_settings()
        if self.s.get('pet') not in PETS: self.s['pet'] = 'dragon'
        self.lines = Lines(); self.player = Player()
        self.bubble = Bubble() if not STATIONARY else None
        self.clock = QElapsedTimer(); self.clock.start()
        self.state = 'fall'; self.orient = 'floor'; self.facing = 1
        self.t_state = 0.0; self.dur_state = 1.0
        self.vx = 0.0; self.vy = 0.0
        self.anim_t = 0.0; self.squash = 0.0
        self.speaking_until = 0.0; self.speak_start = 0.0; self.speak_text = ''; self.speak_len = 1.0
        self.user_sleep = False; self.idle_sleep = False
        self.drag_off = QPointF(); self.drag_hist = []; self.press_pos = None; self.press_t = 0; self.moved = False
        self.last_poke = -99; self.last_land_line = -99; self.climb_target = 0
        self.user_idle_ms = 0; self.active_since = self.now(); self.last_staring = self.now()
        self.batt_warned = False; self.late_warned_day = None
        self.frame_key = None
        self.load_sprites()
        scr = QGuiApplication.primaryScreen().availableGeometry()
        if STATIONARY:
            self.resize(420, 420)
            self.fx, self.fy = 210.0, 410.0
            self.state = 'idle'
        else:
            self.fx = float(scr.left() + scr.width() * random.uniform(0.35, 0.75)); self.fy = float(scr.top() + 40)
        self.timer = QTimer(self); self.timer.timeout.connect(self.tick); self.timer.start(33)
        self.last_tick = self.now()
        self.next_auto = self.now() + max(90, self.s.get('freq_min', 7) * 60 * random.uniform(0.4, 0.7))
        self.quiet_landing = True
        self.build_menu()
        self.tray = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(self.icon(), self)
            self.tray.setToolTip('Rimeclaw'); self.tray.setContextMenu(self.menu); self.tray.show()
        self.idle_proc = None
        self.mon = QTimer(self); self.mon.timeout.connect(self.monitor); self.mon.start(20000)
        QTimer.singleShot(1800, self.greet)
        QTimer.singleShot(3000, self.monitor)
        self.place_window()
        self.show()
        self.raiser = QTimer(self); self.raiser.timeout.connect(self.keep_on_top); self.raiser.start(15000)

    # -- helpers
    def now(self): return self.clock.elapsed() / 1000.0
    def accent(self): return QColor(130, 205, 255) if self.s['pet'] == 'dragon' else QColor(222, 178, 72)
    def icon(self):
        p = os.path.join(APP_DIR, 'icons', f'{self.s["pet"]}.png')
        return QIcon(p if os.path.exists(p) else os.path.join(APP_DIR, 'icons', 'rimeclaw.png'))
    def screen_rect(self):
        if STATIONARY:
            return QRect(0, 0, self.width(), self.height())
        scr = QGuiApplication.screenAt(QPoint(int(self.fx), int(self.fy) - 5)) or QGuiApplication.primaryScreen()
        return scr.availableGeometry()

    def load_sprites(self):
        self.H = int(self.s.get('size', 140))
        dpr = max(1.0, QGuiApplication.primaryScreen().devicePixelRatio())
        self.dpr = dpr
        pet = self.s['pet']
        idle = QImage(os.path.join(APP_DIR, 'sprites', f'{pet}_idle.png'))
        k = self.H / max(1, idle.height())
        self.img = {}
        for n in FRAMES:
            im = QImage(os.path.join(APP_DIR, 'sprites', f'{pet}_{n}.png'))
            w, h = max(1, int(im.width() * k * dpr)), max(1, int(im.height() * k * dpr))
            im = im.scaled(w, h, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
            for flip in (False, True):
                v = im.mirrored(True, False) if flip else im
                v.setDevicePixelRatio(dpr)
                self.img[(n, flip)] = v
        self.S = int(self.H * 1.75)
        if not STATIONARY:
            self.setFixedSize(self.S, self.S)
        self.frame_key = None; self.mask_cache = {}

    # -- window placement: (fx, fy) is the point where the feet touch the floor/wall
    def win_origin(self):
        S = self.S
        if STATIONARY:
            return QPoint(0, 0)
        if self.orient == 'rwall': return QPoint(int(self.fx - S), int(self.fy - S / 2))
        if self.orient == 'lwall': return QPoint(int(self.fx), int(self.fy - S / 2))
        return QPoint(int(self.fx - S / 2), int(self.fy - S + 2))
    def place_window(self):
        if STATIONARY: return
        o = self.win_origin()
        if o != self.pos(): self.move(o)
        self.place_bubble()
    def place_bubble(self):
        if not self.bubble or not self.bubble.isVisible(): return
        o = self.win_origin(); r = self.sprite_rect()
        top = o.y() + int(r.top()); bottom = o.y() + int(r.bottom()); ax = o.x() + int(r.center().x())
        self.bubble.place(ax, top, bottom, self.screen_rect())

    def current_frame(self):
        st = self.state; t = self.anim_t
        if st == 'walk' or st == 'climb':
            n = 'walk1' if int(t / 0.2) % 2 == 0 else 'walk2'
        elif st == 'hang': n = 'drag'
        elif st == 'fall': n = 'fall'
        elif st == 'drag': n = 'drag'
        elif st == 'sit': n = 'sit'
        elif st == 'sleep': n = 'sleep'
        elif st == 'talk': n = 'laugh' if int(t / 0.24) % 2 == 0 else 'idle'
        elif st == 'laugh': n = 'laugh'
        else: n = 'idle'
        flip = self.facing < 0
        if st in ('fall', 'drag', 'hang'):
            flip = False   # these frames are drawn facing the viewer
        return n, flip

    def transform(self):
        """returns (rotation_deg, sx, sy, dx, dy) procedural motion on top of the frame"""
        t = self.anim_t; st = self.state
        rot = 0.0; sx = sy = 1.0; dx = dy = 0.0
        if st in ('idle', 'sit', 'talk', 'laugh'):
            b = math.sin(t * 2.6) * 0.018; sy += b; sx -= b * 0.6
        if st == 'sleep':
            b = math.sin(t * 1.3) * 0.03; sy += b; sx -= b * 0.5
        if st == 'walk':
            dy = -abs(math.sin(t * math.pi / 0.2)) * 3
        if st == 'talk':
            dy = -abs(math.sin(t * 9)) * 2
        if st == 'laugh':
            dx = math.sin(t * 40) * 1.5
        if st == 'fall':
            rot = max(-35, min(35, self.vx * 0.03)) + math.sin(t * 7) * 6
        if st == 'drag':
            rot = max(-30, min(30, self.vx * 0.02)) + math.sin(t * 5) * 4
        if self.squash > 0:
            sy -= self.squash * 0.25; sx += self.squash * 0.2
        if self.orient == 'rwall': rot += -90
        elif self.orient == 'lwall': rot += 90
        return rot, sx, sy, dx, dy

    def sprite_rect(self):
        n, flip = self.current_frame(); im = self.img[(n, flip)]
        w, h = im.width() / self.dpr, im.height() / self.dpr
        S = self.S if not STATIONARY else None
        if STATIONARY:
            return QRectF(self.fx - w / 2, self.fy - h, w, h)
        if self.orient == 'rwall': return QRectF(S - h, S / 2 - w / 2, h, w)
        if self.orient == 'lwall': return QRectF(0, S / 2 - w / 2, h, w)
        return QRectF(S / 2 - w / 2, S - h - 2, w, h)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        n, flip = self.current_frame(); im = self.img[(n, flip)]
        w, h = im.width() / self.dpr, im.height() / self.dpr
        rot, sx, sy, dx, dy = self.transform()
        # pivot = feet point in window coords
        if STATIONARY:
            px, py = self.fx, self.fy
        elif self.orient == 'rwall': px, py = self.S, self.S / 2
        elif self.orient == 'lwall': px, py = 0, self.S / 2
        else: px, py = self.S / 2, self.S - 2
        p.translate(px, py); p.rotate(rot); p.translate(dx, dy); p.scale(sx, sy)
        if self.orient == 'floor' and self.state == 'fall':
            p.translate(0, -h / 2); p.drawImage(QRectF(-w / 2, -h / 2, w, h), im)   # tumble around the middle
        else:
            p.drawImage(QRectF(-w / 2, -h, w, h), im)
        if self.state == 'sleep':
            p.resetTransform()
            r = self.sprite_rect(); f = QFont('Cantarell'); f.setBold(True)
            for i in range(3):
                ph = (self.anim_t * 0.35 + i / 3) % 1.0
                f.setPointSizeF(9 + ph * 8); p.setFont(f)
                c = QColor(200, 230, 255); c.setAlphaF(max(0, 1 - ph) * 0.9); p.setPen(c)
                p.drawText(QPointF(r.center().x() + r.width() * 0.15 + ph * 18, r.top() + 10 - ph * 30), 'z')
        if STATIONARY and self.speak_text and self.now() < self.speaking_until:
            p.resetTransform()
            text = self.speak_text
            w2, h2 = bubble_layout(text, 360)
            rect = QRectF((self.width() - w2) / 2, 6, w2, h2)
            paint_bubble(p, rect, text, self.shown_chars(), self.width() / 2, True, self.accent())

    def update_mask(self):
        if STATIONARY: return
        n, flip = self.current_frame()
        key = (n, flip, self.orient, self.state == 'sleep', self.state == 'fall')
        if key == self.frame_key: return
        self.frame_key = key
        if key not in self.mask_cache:
            img = QImage(self.S, self.S, QImage.Format.Format_ARGB32_Premultiplied); img.fill(0)
            saved = (self.anim_t, self.squash); self.squash = 0
            p = QPainter(img)
            im = self.img[(n, flip)]; w, h = im.width() / self.dpr, im.height() / self.dpr
            rot = {'rwall': -90, 'lwall': 90}.get(self.orient, 0)
            px, py = {'rwall': (self.S, self.S / 2), 'lwall': (0, self.S / 2)}.get(self.orient, (self.S / 2, self.S - 2))
            p.translate(px, py); p.rotate(rot)
            if self.state == 'fall':
                p.translate(0, -h / 2); p.drawImage(QRectF(-w / 2, -h / 2, w, h), im)
            else:
                p.drawImage(QRectF(-w / 2, -h - 4, w, h + 8), im)   # a little slack for bobbing
            p.end(); self.anim_t, self.squash = saved
            bm = QBitmap.fromImage(img.createAlphaMask())
            reg = QRegion(bm)
            if self.state in ('fall',):
                reg = QRegion(0, 0, self.S, self.S)   # tumbling: whole box
            if self.state == 'sleep':   # room for the floating z's
                r = self.sprite_rect()
                reg = reg.united(QRegion(int(r.center().x()), max(0, int(r.top()) - 40), int(r.width() * 0.5) + 30, 60))
            self.mask_cache[key] = reg
        self.setMask(self.mask_cache[key])

    # -- speech
    def shown_chars(self):
        el = self.now() - self.speak_start
        return min(len(self.speak_text), int(len(self.speak_text) * el / max(0.5, self.speak_len * 0.92)) + 1)

    def say(self, cat, force=False):
        line = self.lines.pick(self.s['pet'], cat, self.s['clean'])
        if not line: return False
        d = self.lines.dur.get(self.s['pet'], {}).get(line['id'], 0)
        if not d: d = max(2.5, len(line['text'].split()) * 0.36)
        played = False
        if not self.s['muted']:
            played = self.player.play(os.path.join(APP_DIR, 'voice', self.s['pet'], line['id'] + '.ogg'), self.s.get('volume', 1.0))
        if not played:
            d = max(2.5, len(line['text'].split()) * 0.30)
        self.speak_text = line['text']; self.speak_start = self.now(); self.speak_len = d
        self.speaking_until = self.now() + d + 1.6 + len(line['text']) * 0.004
        if self.bubble:
            self.bubble.set_text(line['text'], self.accent()); self.bubble.show(); self.place_bubble(); self.bubble.raise_()
        if self.orient == 'floor' and self.state in ('idle', 'walk', 'sit', 'laugh', 'talk'):
            self.set_state('talk', d + 0.5)
        self.last_spoke = self.now()
        print(f'[{cat}] {line["text"]}', flush=True)
        return True

    def end_speech(self):
        self.speak_text = ''
        if self.bubble: self.bubble.hide()
        if self.state == 'talk': self.set_state('idle', random.uniform(2, 5))

    def roast_now(self):
        self.wake(silent=True); self.say('roast'); self.schedule_next()
    def rant_now(self):
        self.wake(silent=True); self.say('rant'); self.schedule_next()
    def schedule_next(self):
        f = self.s.get('freq_min', 7)
        self.next_auto = self.now() + (f * 60 * random.uniform(0.7, 1.3) if f else 1e12)

    def greet(self):
        h = time.localtime().tm_hour
        cat = 'greet_morning' if 5 <= h < 12 else ('greet_day' if 12 <= h < 18 else 'greet_night')
        self.say(cat)

    # -- states
    def set_state(self, st, dur=None):
        if st != self.state: self.anim_t = 0.0
        self.state = st; self.t_state = 0.0
        self.dur_state = dur if dur is not None else random.uniform(2, 6)

    def go_sleep(self, user=False, silent=False):
        if user: self.user_sleep = True
        if self.state == 'sleep': return
        if self.orient != 'floor' or self.state in ('fall', 'drag', 'climb', 'hang'):
            return
        if not silent: self.say('sleep')
        QTimer.singleShot(2500 if not silent else 0, lambda: self.set_state('sleep', 1e9) if (self.user_sleep or self.idle_sleep) else None)
        self.update_sleep_action()

    def wake(self, silent=False):
        was = self.state == 'sleep'
        self.user_sleep = False; self.idle_sleep = False
        if was:
            self.set_state('idle', 2)
            if not silent: self.say('wake')
        self.update_sleep_action()

    def decide(self):
        if self.user_sleep or self.idle_sleep:
            self.set_state('sleep', 1e9); return
        r = random.random()
        h = time.localtime().tm_hour
        if r < 0.45:
            self.facing = random.choice([-1, 1]) if random.random() < 0.6 else self.facing
            self.set_state('walk', random.uniform(2.5, 7))
        elif r < 0.70:
            self.set_state('idle', random.uniform(3, 8))
        elif r < 0.90:
            self.set_state('sit', random.uniform(6, 16))
        elif r < 0.96 or not (h >= 23 or h < 6):
            self.set_state('laugh', random.uniform(0.8, 1.4))
        else:
            self.set_state('sleep', random.uniform(30, 90))

    def tick(self):
        t = self.now(); dt = min(0.1, t - self.last_tick); self.last_tick = t
        self.anim_t += dt; self.t_state += dt
        if self.squash > 0: self.squash = max(0.0, self.squash - dt * 3)
        sr = self.screen_rect()
        half = self.H * 0.35
        floor = sr.bottom() + 1 if not STATIONARY else self.height() - 10
        left, right, top = sr.left() + half, sr.right() + 1 - half, sr.top()
        st = self.state
        if STATIONARY and st in ('walk', 'climb', 'hang', 'fall'):
            st = 'idle'; self.set_state('idle', 3)
        if st == 'fall':
            self.vy += self.G * dt; self.fx += self.vx * dt; self.fy += self.vy * dt
            if self.fx < left: self.fx = left; self.vx = abs(self.vx) * 0.45
            if self.fx > right: self.fx = right; self.vx = -abs(self.vx) * 0.45
            if self.fy < top + self.H: self.fy = top + self.H; self.vy = abs(self.vy) * 0.3
            if self.fy >= floor:
                impact = self.vy; self.fy = floor; self.vy = 0; self.vx = 0
                self.squash = min(1.0, impact / 2200)
                if self.quiet_landing: self.quiet_landing = False; self.set_state('idle', random.uniform(1, 3))
                elif impact > 1300 and t - self.last_land_line > 25 and t > self.speaking_until and random.random() < 0.7:
                    self.last_land_line = t; self.set_state('sit', 3); self.say('land')
                else:
                    self.set_state('idle', random.uniform(1, 3))
        elif st == 'walk':
            self.fx += self.facing * self.H * 0.42 * dt
            if self.fx <= left or self.fx >= right:
                self.fx = max(left, min(right, self.fx))
                if random.random() < 0.4 and not STATIONARY and t > self.speaking_until:
                    self.orient = 'rwall' if self.fx >= right else 'lwall'
                    self.fx = sr.right() + 1 if self.orient == 'rwall' else sr.left()
                    self.fy = floor - self.H * 0.5
                    self.climb_target = top + (floor - top) * random.uniform(0.15, 0.65)
                    self.set_state('climb', 1e9)
                else:
                    self.facing *= -1
            elif self.t_state > self.dur_state:
                self.decide()
        elif st == 'climb':
            self.fy -= self.H * 0.38 * dt
            if self.fy <= self.climb_target or self.fy <= top + self.H:
                self.set_state('hang', random.uniform(1.5, 4))
        elif st == 'hang':
            if self.t_state > self.dur_state: self.let_go()
        elif st == 'drag':
            pass
        elif st == 'talk':
            if t > self.speaking_until - 1.0: self.set_state('idle', random.uniform(2, 5))
        elif st == 'sleep':
            if not (self.user_sleep or self.idle_sleep) and self.t_state > self.dur_state: self.set_state('idle', 2)
        else:
            if self.fy < floor - 1 and self.orient == 'floor' and not STATIONARY:
                self.set_state('fall')   # floor moved (dock / resolution change)
            elif self.fy > floor: self.fy = floor
            if self.t_state > self.dur_state: self.decide()
        # speech lifecycle
        if self.speak_text:
            if t > self.speaking_until: self.end_speech()
            elif self.bubble:
                n = self.shown_chars()
                if n != self.bubble.shown: self.bubble.shown = n; self.bubble.update()
                self.place_bubble()
        # auto roast scheduler
        if t > self.next_auto:
            if self.state == 'sleep' or self.state in ('drag', 'fall') or self.speak_text or self.user_idle_ms > 120000:
                self.next_auto = t + 60
            else:
                self.say('rant' if random.random() < self.s.get('rant_share', 0.25) else 'roast'); self.schedule_next()
        self.place_window(); self.update_mask(); self.update()
        # adaptive frame rate: smooth when moving, lazy when chilling (keeps idle CPU tiny)
        moving = self.state in ('walk', 'fall', 'drag', 'climb') or self.squash > 0
        iv = 33 if moving else (70 if self.speak_text else (400 if self.state == 'sleep' else 125))
        if self.timer.interval() != iv: self.timer.setInterval(iv)

    def let_go(self):
        o = self.orient
        if o == 'floor': return
        self.orient = 'floor'
        self.fy = self.fy + self.H * 0.5
        self.fx += -self.H * 0.6 if o == 'rwall' else self.H * 0.6
        self.vx = (-1 if o == 'rwall' else 1) * random.uniform(60, 200); self.vy = -150
        self.facing = -1 if o == 'rwall' else 1
        self.set_state('fall')

    # -- mouse
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.RightButton:
            self.menu.popup(e.globalPosition().toPoint()); return
        if e.button() != Qt.MouseButton.LeftButton: return
        self.press_pos = e.globalPosition(); self.press_t = self.now(); self.moved = False
        if STATIONARY:
            self.windowHandle().startSystemMove(); return
        self.drag_hist = [(self.now(), e.globalPosition())]
    def mouseMoveEvent(self, e):
        if self.press_pos is None or STATIONARY: return
        gp = e.globalPosition()
        if not self.moved and (gp - self.press_pos).manhattanLength() > 6:
            self.moved = True
            if self.orient != 'floor':
                self.orient = 'floor'
            self.set_state('drag', 1e9)
            if self.state == 'drag' and self.now() > self.speaking_until and random.random() < 0.5:
                self.say('pickup')
        if self.moved:
            self.fx = gp.x(); self.fy = gp.y() + self.H * 0.75
            self.drag_hist.append((self.now(), gp)); self.drag_hist = self.drag_hist[-6:]
            if len(self.drag_hist) >= 2:
                (t0, p0), (t1, p1) = self.drag_hist[0], self.drag_hist[-1]
                if t1 > t0: self.vx = (p1.x() - p0.x()) / (t1 - t0)
            self.place_window()
    def mouseReleaseEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton or self.press_pos is None: return
        self.press_pos = None
        if STATIONARY or not self.moved:
            self.poke(); return
        (t0, p0), (t1, p1) = self.drag_hist[0], self.drag_hist[-1]
        dtt = max(0.016, t1 - t0)
        self.vx = max(-2500, min(2500, (p1.x() - p0.x()) / dtt)); self.vy = max(-2500, min(2500, (p1.y() - p0.y()) / dtt))
        if self.now() - t1 > 0.1: self.vx = self.vy = 0
        self.set_state('fall')
    def poke(self):
        t = self.now()
        if self.state == 'sleep':
            self.wake(); return
        self.squash = 0.6
        if t - self.last_poke < 1.2: return
        self.last_poke = t
        self.player.stop()
        if self.speak_text: self.end_speech()
        if self.orient == 'floor': self.set_state('laugh', 0.8)
        self.say('poke')

    # -- background monitors: idle time, battery, time of day
    def monitor(self):
        if self.s.get('reactions', True):
            self.check_battery(); self.check_late()
        if shutil.which('gdbus') and (self.idle_proc is None or self.idle_proc.state() == QProcess.ProcessState.NotRunning):
            self.idle_proc = QProcess(self)
            self.idle_proc.finished.connect(self.got_idle)
            self.idle_proc.start('gdbus', ['call', '--session', '--dest', 'org.gnome.Mutter.IdleMonitor', '--object-path',
                                           '/org/gnome/Mutter/IdleMonitor/Core', '--method', 'org.gnome.Mutter.IdleMonitor.GetIdletime'])
    def got_idle(self, *a):
        out = bytes(self.idle_proc.readAllStandardOutput()).decode(errors='ignore')
        m = re.search(r'(\d+)', out)
        if not m: return
        self.user_idle_ms = int(m.group(1)); t = self.now()
        if self.user_idle_ms > 5 * 60000:
            self.active_since = t
            if not self.idle_sleep and not self.user_sleep and self.state != 'sleep' and self.orient == 'floor' and not self.speak_text:
                self.idle_sleep = True; self.set_state('sleep', 1e9)
        elif self.user_idle_ms < 15000:
            if self.idle_sleep and not self.user_sleep:
                self.idle_sleep = False; self.set_state('idle', 2); self.say('wake')
            if self.s.get('reactions', True) and t - self.active_since > 2 * 3600 and t - self.last_staring > 2 * 3600 and not self.speak_text:
                self.last_staring = t; self.say('staring')
    def check_battery(self):
        try:
            for b in glob.glob('/sys/class/power_supply/BAT*'):
                cap = int(open(b + '/capacity').read().strip()); status = open(b + '/status').read().strip()
                if status == 'Discharging' and cap <= 15 and not self.batt_warned and not self.speak_text:
                    self.batt_warned = True; self.wake(silent=True); self.say('battery')
                if cap >= 25 or status != 'Discharging': self.batt_warned = False
                break
        except Exception:
            pass
    def check_late(self):
        lt = time.localtime()
        if 0 <= lt.tm_hour < 4 and self.late_warned_day != lt.tm_yday and self.now() > 600 and not self.speak_text \
                and self.state != 'sleep' and self.user_idle_ms < 60000:
            self.late_warned_day = lt.tm_yday; self.say('late')

    def keep_on_top(self):
        if not STATIONARY and self.isVisible():
            self.raise_()
            if self.bubble and self.bubble.isVisible(): self.bubble.raise_()

    # -- menu
    def build_menu(self):
        m = QMenu()
        m.addAction('Roast me now', self.roast_now)
        m.addAction('Rant now', self.rant_now)
        m.addSeparator()
        self.a_mute = QAction('Mute voice', m, checkable=True); self.a_mute.setChecked(self.s['muted'])
        self.a_mute.toggled.connect(lambda v: self.set_opt('muted', v)); m.addAction(self.a_mute)
        self.a_clean = QAction('Clean mode (no swearing)', m, checkable=True); self.a_clean.setChecked(self.s['clean'])
        self.a_clean.toggled.connect(lambda v: self.set_opt('clean', v)); m.addAction(self.a_clean)
        fm = m.addMenu('Roast frequency'); g = QActionGroup(fm)
        for v, label in FREQS:
            a = QAction(label, fm, checkable=True); a.setChecked(self.s['freq_min'] == v); g.addAction(a); fm.addAction(a)
            a.triggered.connect(lambda _=False, v=v: (self.set_opt('freq_min', v), self.schedule_next()))
        pm = m.addMenu('Switch pet'); g2 = QActionGroup(pm); self.pet_actions = {}
        for k, label in PETS.items():
            a = QAction(label, pm, checkable=True); a.setChecked(self.s['pet'] == k); g2.addAction(a); pm.addAction(a)
            a.triggered.connect(lambda _=False, k=k: self.switch_pet(k)); self.pet_actions[k] = a
        sm = m.addMenu('Size'); g3 = QActionGroup(sm)
        for v, label in SIZES:
            a = QAction(label, sm, checkable=True); a.setChecked(self.s['size'] == v); g3.addAction(a); sm.addAction(a)
            a.triggered.connect(lambda _=False, v=v: self.set_size(v))
        self.a_react = QAction('React to battery / late nights / long sessions', m, checkable=True)
        self.a_react.setChecked(self.s.get('reactions', True)); self.a_react.toggled.connect(lambda v: self.set_opt('reactions', v))
        m.addAction(self.a_react)
        m.addSeparator()
        self.a_sleep = m.addAction('Sleep', self.toggle_sleep)
        m.addAction('Quit', self.quit)
        self.menu = m
    def update_sleep_action(self):
        if hasattr(self, 'a_sleep'): self.a_sleep.setText('Wake up' if (self.user_sleep or self.state == 'sleep') else 'Sleep')
    def toggle_sleep(self):
        if self.user_sleep or self.state == 'sleep': self.wake()
        else: self.go_sleep(user=True)
        self.update_sleep_action()
    def set_opt(self, k, v):
        self.s[k] = v; save_settings(self.s)
        if k == 'muted' and v: self.player.stop()
    def switch_pet(self, k):
        if k == self.s['pet']: return
        self.player.stop(); self.end_speech()
        self.s['pet'] = k; save_settings(self.s); self.load_sprites()
        if self.tray: self.tray.setIcon(self.icon())
        self.setWindowIcon(self.icon())
        self.orient = 'floor'; self.fy -= self.H; self.set_state('fall'); QTimer.singleShot(1200, self.greet)
    def set_size(self, v):
        self.s['size'] = v; save_settings(self.s); self.load_sprites(); self.place_window()
    def quit(self):
        self.player.stop(); save_settings(self.s)
        if self.tray: self.tray.hide()
        QApplication.quit()

def main():
    app = QApplication(sys.argv)
    app.setApplicationName(SLUG); app.setDesktopFileName(SLUG); app.setQuitOnLastWindowClosed(False)
    # single instance: a second launch just asks the running pet for a roast
    name = f'{SLUG}-{os.getuid()}'
    cmd = sys.argv[1].lstrip('-') if len(sys.argv) > 1 else ''
    sock = QLocalSocket(); sock.connectToServer(name)
    if sock.waitForConnected(300):
        c = cmd if cmd in ('roast', 'rant', 'quit') else 'roast'
        sock.write(c.encode() + b'\n'); sock.flush(); sock.waitForBytesWritten(300); sock.disconnectFromServer()
        print({'quit': 'Asked Rimeclaw to leave.', 'rant': 'Asked Rimeclaw to rant.'}.get(c, 'Rimeclaw is already running; asked it to roast you.'))
        return 0
    if cmd == 'quit':
        print('Rimeclaw is not running.'); return 0
    QLocalServer.removeServer(name); server = QLocalServer(); server.listen(name)
    pet = Pet(app)
    app.setWindowIcon(pet.icon())
    def on_conn():
        c = server.nextPendingConnection()
        def rd():
            cmd = bytes(c.readAll()).decode(errors='ignore').strip()
            {'roast': pet.roast_now, 'rant': pet.rant_now, 'quit': pet.quit}.get(cmd, pet.roast_now)()
        c.readyRead.connect(rd)
    server.newConnection.connect(on_conn)
    signal.signal(signal.SIGINT, lambda *a: pet.quit()); signal.signal(signal.SIGTERM, lambda *a: pet.quit())
    if os.environ.get('RIMECLAW_SELFTEST'):
        QTimer.singleShot(int(float(os.environ['RIMECLAW_SELFTEST']) * 1000), pet.quit)
    return app.exec()

if __name__ == '__main__':
    sys.exit(main())
