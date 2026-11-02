import ctypes
import hashlib
import json
import math
import os
import random
import sys
import time
import wave
import winsound
import winreg
from array import array
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QCursor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QInputDialog, QLineEdit, QMenu, QSystemTrayIcon, QWidget
from animator import CatAnimator
from frame_store import FrameStore

ROOT=Path(getattr(sys,'_MEIPASS',Path(__file__).parent))
DATA=Path(os.environ.get('APPDATA',str(Path.home())))/'PhotoCatPet'
DATA.mkdir(parents=True,exist_ok=True)
SETTINGS=DATA/'settings.json'
ANIMATION=ROOT/'assets'/'smooth'
RUN_KEY=r'Software\Microsoft\Windows\CurrentVersion\Run'

def startup_enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,RUN_KEY) as key:
            return bool(winreg.QueryValueEx(key,'PhotoCatPet')[0])
    except FileNotFoundError:
        return False

def set_startup(enabled):
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER,RUN_KEY) as key:
        if enabled:
            command=f'"{sys.executable}"'
            if not getattr(sys,'frozen',False):
                command+=f' "{Path(__file__).resolve()}"'
            winreg.SetValueEx(key,'PhotoCatPet',0,winreg.REG_SZ,command)
        else:
            try:
                winreg.DeleteValue(key,'PhotoCatPet')
            except FileNotFoundError:
                pass

@lru_cache(maxsize=60)
def volume_clip(source,level):
    if level==100:
        return source
    cache=DATA/'audio-cache'
    cache.mkdir(exist_ok=True)
    digest=hashlib.sha256(source.read_bytes()).hexdigest()[:10]
    target=cache/f'{digest}-{level}.wav'
    if target.exists():
        return target
    with wave.open(str(source),'rb') as audio:
        params=audio.getparams()
        samples=array('h',audio.readframes(audio.getnframes()))
    gain=level/100
    output=array('h')
    for sample in samples:
        value=sample/32768*gain
        if abs(value)>.90:
            value=math.copysign(.90+.08*math.tanh((abs(value)-.90)/.08),value)
        output.append(round(max(-.98,min(.98,value))*32767))
    with wave.open(str(target),'wb') as audio:
        audio.setparams(params)
        audio.writeframes(output.tobytes())
    return target

class Pet(QWidget):
    def __init__(self):
        super().__init__()
        try:
            self.config=json.loads(SETTINGS.read_text(encoding='utf-8'))
        except (OSError,ValueError):
            self.config={}
        self.name=self.config.get('name','小花')
        self.size=max(130,min(330,self.config.get('size',205)))
        self.roam=self.config.get('roam',True)
        self.sound=self.config.get('sound',True)
        self.volume=max(25,min(150,self.config.get('volume',125)))
        self.follow=False
        self.hunger=self.config.get('hunger',80)
        self.bond=self.config.get('bond',0)
        self.anim=CatAnimator()
        self.manifest=json.loads((ANIMATION/'manifest.json').read_text(encoding='utf-8'))
        self.scene=json.loads((ANIMATION/'geometry.json').read_text(encoding='utf-8'))
        self.frames=FrameStore(ANIMATION,self.manifest,self)
        self.frames.changed.connect(self.frame_ready)
        self.frames.failed.connect(lambda message:(DATA/'frame-error.log').write_text(message,encoding='utf-8'))
        self.last_draw=None
        self.frame_intervals=[]
        self.tick_costs=[]
        self.paint_costs=[]
        self.decode_waits=0
        self.voice_clips=[ROOT/'assets'/'voices'/f'meow{i}.wav' for i in range(1,11)]
        self.last_clip=None
        self.last_meow=0
        self.next_meow=time.monotonic()+random.uniform(90,180)
        self.next_action=time.monotonic()+random.uniform(7,13)
        self.last_tick=time.monotonic()
        self.last_save=self.last_tick
        self.message=''
        self.message_until=0
        self.hearts=[]
        self.press_at=None
        self.dragged=False
        self.move_fraction=0.0
        self.last_stroke=0
        self.stroke_distance=0
        self.last_hover=None
        self.hover_since=None
        self.hover_handled=False
        self.rename_dialog=None
        self.click_timer=QTimer(self)
        self.click_timer.setSingleShot(True)
        self.click_timer.setTimerType(Qt.PreciseTimer)
        self.click_timer.setInterval(QApplication.doubleClickInterval())
        self.click_timer.timeout.connect(self.pet)
        self.setWindowTitle('照片猫咪桌宠 · 取名修复版 v11')
        self.setWindowFlags(Qt.FramelessWindowHint|Qt.WindowStaysOnTopHint|Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setMouseTracking(True)
        self.resize(round(self.size*self.scene['width']/400+100),round(self.size*self.scene['height']/400+105))
        a=QApplication.primaryScreen().availableGeometry()
        self.move(a.right()-self.width()-40,a.bottom()-self.height())
        self.tray=QSystemTrayIcon(QIcon(str(ROOT/'assets'/'cat.ico')),self)
        self.tray.setToolTip(f'{self.name} · 摸头、喂食、玩耍')
        self.tray.activated.connect(self.tray_click)
        self.tray_menu=QMenu()
        self.tray_menu.aboutToShow.connect(lambda:self.fill_menu(self.tray_menu))
        self.tray.setContextMenu(self.tray_menu)
        self.tray.show()
        self.timer=QTimer(self)
        self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.timeout.connect(self.tick)
        self.timer.start(16)
        self.say('喵～慢慢摸摸我的头吧 ♡')

    @property
    def mode(self):
        return self.anim.state

    def frame_ready(self,clip,index):
        if (clip,index)==self.anim.pose(self.manifest):
            self.update()

    def save(self):
        self.config.update(name=self.name,size=self.size,roam=self.roam,sound=self.sound,
                           volume=self.volume,hunger=self.hunger,bond=self.bond)
        temp=SETTINGS.with_suffix('.tmp')
        temp.write_text(json.dumps(self.config,ensure_ascii=False),encoding='utf-8')
        temp.replace(SETTINGS)

    def say(self,message,duration=3.5):
        self.message=message
        self.message_until=time.monotonic()+duration
        self.update()

    def act(self,mode,duration,message):
        self.anim.request(mode,duration)
        self.next_action=time.monotonic()+duration+random.uniform(8,16)
        self.say(message)

    def pet(self,gentle=False):
        if not gentle:
            self.meow()
        self.bond+=1
        self.follow=False
        self.act('happy',2.35,random.choice(['嗯…这里很舒服～','呼噜呼噜…再摸一下 ♡','轻轻蹭蹭你～']))
        self.hearts.extend([[self.width()*.6+random.uniform(-10,15),self.height()-self.size*.88-20,1.0] for _ in range(1 if gentle else 2)])
        if gentle and random.random()<.65:
            self.message_until=time.monotonic()

    def feed(self):
        self.follow=False
        self.meow()
        self.hunger=min(100,self.hunger+22)
        self.bond+=2
        self.act('eat',3.2,'让我坐好，啊呜～')

    def play(self):
        self.follow=False
        self.meow()
        self.bond+=2
        self.act('play',1.8,'蹲低一点…扑！')

    def run_around(self):
        self.follow=False
        self.act('run',5,'起身，跑一圈，再回来坐好～')

    def sit(self):
        self.follow=False
        self.act('idle',3,'坐好，转过来看着你～')

    def look_at_me(self):
        self.follow=False
        self.act('idle',3,'转过来，看着你啦 ♡')
        if self.anim.view=='front' and self.mode=='idle':
            self.anim.start_idle_event('look_front',random.uniform(1.6,2.1))

    def sleep(self):
        self.follow=False
        if self.anim.goal=='sleep' or self.mode in ('sleep','sleep_down'):
            self.act('idle',3,'睡醒啦…慢慢抬起头～')
        else:
            self.act('sleep',3600,'先趴下来，再团成一小团…')

    def meow(self,force=False,preferred=None):
        now=time.monotonic()
        if self.sound and (force or now-self.last_meow>2):
            choices=[c for c in self.voice_clips if c!=self.last_clip] or self.voice_clips
            if not choices:
                return
            clip=preferred if preferred is not None and preferred.exists() else random.choice(choices)
            self.last_clip=clip
            try:
                winsound.PlaySound(str(volume_clip(clip,self.volume)),winsound.SND_FILENAME|winsound.SND_ASYNC|winsound.SND_NODEFAULT)
            except RuntimeError:
                pass
            self.last_meow=now

    def set_volume(self,level):
        self.volume=level
        self.sound=True
        self.save()
        self.say(f'猫叫音量 {level}%')
        self.meow(True)

    def area(self):
        screen=QApplication.screenAt(self.geometry().center()) or QApplication.primaryScreen()
        return screen.availableGeometry()

    def clamp(self):
        a=self.area()
        self.move(max(a.left(),min(self.x(),a.right()-self.width()+1)),max(a.top(),min(self.y(),a.bottom()-self.height()+1)))

    def tick(self):
        tick_start=time.perf_counter()
        now=time.monotonic()
        interval=now-self.last_tick
        self.frame_intervals.append(interval*1000)
        if len(self.frame_intervals)>1800:self.frame_intervals=self.frame_intervals[-1200:]
        dt=min(.08,interval)
        self.last_tick=now
        # Layered windows may lose WM_MOUSEMOVE during alpha-surface changes.
        # Poll the pointer as well, so a still pointer can reliably stroke the head.
        position=self.mapFromGlobal(QCursor.pos())
        scale=self.size/self.scene['pixels_per_size']
        front=self.anim.view=='front' or self.mode in ('face_front','face_side')
        head_x=self.width()/2+(0 if front else self.anim.direction*115*scale)
        head_y=self.height()-self.scene['ground_y']*scale-10+260*scale
        on_head=(self.isVisible() and abs(position.x()-head_x)<self.size*.20
                 and abs(position.y()-head_y)<self.size*.24)
        if on_head and self.press_at is None:
            if self.hover_since is None:self.hover_since=now
            if (self.anim.goal!='play' and self.mode!='play' and not self.hover_handled
                    and now-self.hover_since>.55 and now-self.last_stroke>1.8):
                self.hover_handled=True
                self.last_stroke=now
                self.pet(True)
        else:
            self.hover_since=None
            self.hover_handled=False
        self.hunger=max(0,self.hunger-dt/80)
        if self.follow and self.mode in ('idle','stand','walk','run','start'):
            delta=QCursor.pos().x()-self.geometry().center().x()
            if abs(delta)>75:
                self.anim.face(1 if delta>0 else -1)
                gait='run' if abs(delta)>(220 if self.anim.goal=='run' else 330) else 'walk'
                if self.anim.goal!=gait or self.anim.remaining<1:
                    self.anim.request(gait,5)
            elif self.anim.goal in ('walk','run'):
                self.anim.request('idle')
        elif self.roam and not on_head and self.mode=='idle' and self.anim.goal=='idle' and now>self.next_action:
            choice=random.choice(['walk','walk','run','groom','idle'])
            if choice in ('walk','run'):
                self.anim.face(random.choice([-1,1]))
            self.anim.request(choice,random.uniform(3,6))
            self.next_action=now+random.uniform(17,36)
        self.anim.speed_scale=self.size/205
        self.anim.stride_scale=self.size
        clip,index=self.anim.pose(self.manifest)
        if self.frames.ready(clip,index):
            dx=self.anim.step(dt)
        else:
            # Keep the last shared endpoint while a worker catches up, rather
            # than blocking the UI or skipping half of a newly entered action.
            dx=0
            self.decode_waits+=1
        clip,index=self.anim.pose(self.manifest)
        self.frames.ensure(clip,index)
        for predicted in self.anim.likely_next_clips():
            if predicted in self.manifest:self.frames.ensure(predicted,0,ahead=7,urgent=False)
        if self.press_at is None:
            self.move_fraction+=dx
            step=int(self.move_fraction)
            self.move_fraction-=step
            if step:
                self.move(self.x()+step,self.y())
                a=self.area()
                if (step>0 and self.x()+self.width()>=a.right()) or (step<0 and self.x()<=a.left()):
                    self.anim.face(-1 if step>0 else 1)
                    self.move_fraction=0
                self.clamp()
        if now>self.next_meow:
            if self.isVisible() and self.mode not in ('sleep','sleep_down'):
                self.meow()
            self.next_meow=now+random.uniform(90,200)
        for h in self.hearts:
            h[1]-=dt*23
            h[2]-=dt*.5
        self.hearts=[h for h in self.hearts if h[2]>0]
        if now-self.last_save>30:
            self.save()
            self.last_save=now
        self.update()
        self.tick_costs.append((time.perf_counter()-tick_start)*1000)
        if len(self.tick_costs)>1800:self.tick_costs=self.tick_costs[-1200:]

    def current_sprite(self):
        clip,frame=self.anim.pose(self.manifest)
        image=self.frames.get(clip,frame)
        if image is not None:
            self.last_draw=(image,self.manifest[clip]['rect'],self.anim.render_direction())
        if self.last_draw is None:
            image=self.frames.get('idle_front',0)
            if image is None:
                image=self.frames.fallback
            self.last_draw=(image,self.manifest['idle_front']['rect'],1)
        return self.last_draw

    def paintEvent(self,event):
        paint_start=time.perf_counter()
        p=QPainter(self)
        # A layered Windows surface must replace its previous alpha each frame.
        # Clear the entire canvas, including the old head, bowl and speech bubble.
        p.setCompositionMode(QPainter.CompositionMode_Source)
        p.fillRect(self.rect(),Qt.transparent)
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        sprite,rect,direction=self.current_sprite()
        scale=self.size/self.scene['pixels_per_size']
        y=self.height()-self.scene['ground_y']*scale-10
        p.save()
        p.translate(self.width()/2,y)
        p.scale(direction*scale,scale)
        p.translate(-self.scene['center_x'],0)
        if self.mode=='eat':
            p.setPen(QColor('#7b9fbb'))
            p.setBrush(QColor('#b7d7ec'))
            p.drawRoundedRect(QRectF(470,505,65,18),5,5)
            p.setBrush(QColor('#bd8860'))
            p.drawEllipse(QRectF(473,504,59,8))
        # No rotation, whole-body wobble or fake breathing scale. Poses contain
        # the physical body motion, including facial changes and landing flexion.
        p.drawImage(QRectF(*rect),sprite,QRectF(sprite.rect()))
        p.restore()
        p.setFont(QFont('Microsoft YaHei',14))
        for hx,hy,opacity in self.hearts:
            p.setPen(QColor(231,132,153,int(220*opacity)))
            p.drawText(QPointF(hx,hy),'♥')
        if time.monotonic()<self.message_until:
            p.setFont(QFont('Microsoft YaHei',10))
            p.setPen(QColor('#725b4d'))
            p.setBrush(QColor(255,250,240,245))
            rect=QRectF(9,12,self.width()-18,53)
            p.drawRoundedRect(rect,17,17)
            p.drawText(rect.adjusted(7,4,-7,-4),Qt.AlignCenter|Qt.TextWordWrap,self.message)
        p.end()
        self.paint_costs.append((time.perf_counter()-paint_start)*1000)
        if len(self.paint_costs)>1800:self.paint_costs=self.paint_costs[-1200:]

    def mousePressEvent(self,event):
        if event.button()==Qt.LeftButton:
            self.press_at=event.globalPosition().toPoint()
            self.start_pos=self.pos()
            self.dragged=False

    def mouseMoveEvent(self,event):
        if self.press_at is not None:
            diff=event.globalPosition().toPoint()-self.press_at
            if diff.manhattanLength()>7:
                self.dragged=True
                self.anim.request('idle')
                self.follow=False
                self.move(self.start_pos+diff)
        else:
            position=event.position()
            if self.last_hover is not None:
                self.stroke_distance+=(position-self.last_hover).manhattanLength()
            self.last_hover=position
            scale=self.size/self.scene['pixels_per_size']
            front=self.anim.view=='front' or self.mode in ('face_front','face_side')
            head_x=self.width()/2+(0 if front else self.anim.direction*115*scale)
            head_y=self.height()-self.scene['ground_y']*scale-10+260*scale
            if abs(position.x()-head_x)<self.size*.20 and abs(position.y()-head_y)<self.size*.24:
                if (self.anim.goal!='play' and self.mode!='play' and self.stroke_distance>28
                        and time.monotonic()-self.last_stroke>1.8):
                    self.last_stroke=time.monotonic()
                    self.stroke_distance=0
                    self.pet(True)
            else:
                self.stroke_distance=0

    def leaveEvent(self,event):
        self.last_hover=None
        self.stroke_distance=0

    def mouseReleaseEvent(self,event):
        if event.button()==Qt.LeftButton and self.press_at is not None:
            if self.dragged:
                self.clamp()
                self.say('在这里坐一会儿～')
            else:
                self.click_timer.start()
            self.press_at=None

    def mouseDoubleClickEvent(self,event):
        if event.button()==Qt.LeftButton:
            self.click_timer.stop()
            self.play()

    def wheelEvent(self,event):
        self.set_size(self.size+(15 if event.angleDelta().y()>0 else -15))

    def set_size(self,size):
        bottom=self.geometry().bottom()
        self.size=max(130,min(330,size))
        self.resize(round(self.size*self.scene['width']/400+100),round(self.size*self.scene['height']/400+105))
        self.move(self.x(),bottom-self.height()+1)
        self.clamp()
        self.save()

    def rename(self):
        # Let the right-click/tray menu close before opening a focusable window.
        QTimer.singleShot(0,self.show_rename_dialog)

    def show_rename_dialog(self):
        if self.rename_dialog is not None:
            self.rename_dialog.raise_()
            self.rename_dialog.activateWindow()
            return
        dialog=QInputDialog(self,Qt.Dialog|Qt.WindowStaysOnTopHint|Qt.WindowCloseButtonHint)
        self.rename_dialog=dialog
        dialog.setAttribute(Qt.WA_ShowWithoutActivating,False)
        dialog.setAttribute(Qt.WA_DeleteOnClose)
        dialog.setWindowModality(Qt.NonModal)
        dialog.setWindowTitle('给猫咪起名字')
        dialog.setLabelText('名字：')
        dialog.setInputMode(QInputDialog.TextInput)
        dialog.setTextValue(self.name)
        dialog.setOkButtonText('确定')
        dialog.setCancelButtonText('取消')
        field=dialog.findChild(QLineEdit)
        if field is not None:
            field.setMaxLength(16)
            field.selectAll()
        dialog.adjustSize()
        area=self.area()
        center=self.geometry().center()
        x=max(area.left(),min(center.x()-dialog.width()//2,area.right()-dialog.width()+1))
        y=max(area.top(),min(center.y()-dialog.height()//2,area.bottom()-dialog.height()+1))
        dialog.move(x,y)

        def finished(result):
            if result and dialog.textValue().strip():
                self.name=dialog.textValue().strip()[:16]
                self.tray.setToolTip(f'{self.name} · 摸头、喂食、玩耍')
                self.say(f'我叫{self.name}，喵！')
                self.save()
            self.rename_dialog=None

        dialog.finished.connect(finished)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        if field is not None:
            field.setFocus(Qt.OtherFocusReason)

    def toggle(self,field):
        setattr(self,field,not getattr(self,field))
        if field=='follow' and not self.follow:
            self.anim.request('idle')
        if field=='roam' and not self.roam:
            self.anim.request('idle')
        self.save()

    def fill_menu(self,menu):
        menu.clear()
        menu.addAction(f'{self.name} · 饱食 {round(self.hunger)} · 亲密 {self.bond}').setEnabled(False)
        menu.addSeparator()
        menu.addAction('轻轻摸头 / 蹭蹭 ♡',self.pet)
        menu.addAction('看着我 / 正面坐好',self.look_at_me)
        menu.addAction('喂小鱼',self.feed)
        menu.addAction('舔爪洗脸',lambda:self.act('groom',2.5,'舔舔爪子，洗洗脸～'))
        menu.addAction('预蹲、扑跳、落地',self.play)
        menu.addAction('起身跑一圈',self.run_around)
        menu.addAction('停稳，再坐下',self.sit)
        menu.addAction('叫一声 喵～',lambda:self.meow(True))
        menu.addAction('慢慢叫醒' if self.anim.goal=='sleep' else '趴下睡觉',self.sleep)
        menu.addSeparator()
        for text,field in [('自由散步','roam'),('跟随鼠标（横向）','follow'),('猫叫声','sound')]:
            action=menu.addAction(text)
            action.setCheckable(True)
            action.setChecked(getattr(self,field))
            action.triggered.connect(lambda checked=False,f=field:self.toggle(f))
        volume_menu=menu.addMenu(f'猫叫音量：{self.volume}%')
        for text,level in [('轻声 50%',50),('适中 75%',75),('清晰 100%',100),('更响 125%',125),('响亮 150%',150)]:
            action=volume_menu.addAction(text,lambda checked=False,v=level:self.set_volume(v))
            action.setCheckable(True)
            action.setChecked(self.volume==level)
        sizes=menu.addMenu('猫咪大小')
        for text,size in [('小巧',150),('标准',205),('大只',280)]:
            sizes.addAction(text,lambda checked=False,s=size:self.set_size(s))
        menu.addAction('起个名字',self.rename)
        startup=menu.addAction('开机启动')
        startup.setCheckable(True)
        startup.setChecked(startup_enabled())
        startup.triggered.connect(set_startup)
        menu.addAction('显示猫咪 / 回到屏幕',self.reveal)
        menu.addAction('暂时隐藏',self.hide)
        menu.addSeparator()
        menu.addAction('退出桌宠',self.quit)

    def contextMenuEvent(self,event):
        menu=QMenu(self)
        self.fill_menu(menu)
        menu.exec(event.globalPos())

    def reveal(self):
        self.clamp()
        self.show()
        self.raise_()

    def tray_click(self,reason):
        if reason==QSystemTrayIcon.Trigger:
            self.reveal()

    def quit(self):
        self.save()
        self.frames.close()
        QApplication.quit()

def main():
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateMutexW.argtypes=[ctypes.c_void_p,ctypes.c_bool,ctypes.c_wchar_p]
    kernel.CreateMutexW.restype=ctypes.c_void_p
    name='Local\\PhotoCatPet-20261030'+('-Smoke' if '--smoke-test' in sys.argv else '')
    mutex=kernel.CreateMutexW(None,False,name)
    if ctypes.get_last_error()==183:
        return
    app=QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setWindowIcon(QIcon(str(ROOT/'assets'/'cat.ico')))
    pet=Pet()
    pet.show()
    if '--enable-startup' in sys.argv:
        set_startup(True)
    app.aboutToQuit.connect(pet.frames.close)
    if '--smoke-test' in sys.argv:
        pet.roam=False
        pet.message_until=0
        pet.anim.view='side'
        pet.anim.stable('walk')
        pet.anim.goal='walk'
        pet.anim.remaining=10
        pet.move(pet.area().center().x()-pet.width()//2,pet.y())
        QTimer.singleShot(700,lambda:pet.grab().save(str(DATA/'smoke-v6.png')))
        QTimer.singleShot(1400,app.quit)
    sys.exit(app.exec())

if __name__=='__main__':
    try:
        main()
    except Exception:
        import traceback
        (DATA/'error.log').write_text(traceback.format_exc(),encoding='utf-8')
        raise
