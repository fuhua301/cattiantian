"""Posture-aware cat state machine. No rendering or wall-clock dependencies."""
import math
import random
from bisect import bisect_right


def smoothstep(t):
    t=max(0.0,min(1.0,t))
    return t*t*(3-2*t)


class CatAnimator:
    DURATIONS={'sit_down':1.28,'stand_up':1.16,'sleep_down':2.35,'wake_up':2.20,
               'happy':2.75,'eat':3.85,'groom':3.20,'play':1.95,'turn':1.08,
               'face_front':1.22,'face_side':1.22}
    def __init__(self,seed=None):
        self.rng=random.Random(seed)
        self.state='idle'
        self.clip='idle_front'
        self.view='front'
        self.elapsed=0.0
        self.duration=0.0
        self.goal='idle'
        self.remaining=0.0
        self.direction=1
        self.wanted_direction=1
        self.phase=0.0
        self.velocity=0.0
        self.speed_scale=1.0
        self.stride_scale=205.0
        self.start_speed=0.0
        self.end_speed=0.0
        self.next_state=None
        self.pending_plant=None
        self.blink_clock=0.0
        self.stand_hold=0.0
        self.history=['idle']
        self.idle_event=None
        self.idle_event_elapsed=0.0
        self.idle_event_duration=1.0
        self.idle_event_speed=1.0
        self.next_blink=self.rng.uniform(2.2,4.5)
        self.next_look=self.rng.uniform(6.,12.)
        self.next_paw=self.rng.uniform(14.,27.)
        self.life_clock=self.rng.uniform(0,30)

    def request(self,mode,duration=5):
        if mode not in ('idle','walk','run','happy','eat','groom','sleep','play'):
            raise ValueError(mode)
        self.goal=mode
        self.remaining=duration
        if self.idle_event is not None:
            self.idle_event_speed=2.2

    def face(self,direction):
        self.wanted_direction=1 if direction>=0 else -1

    def enter(self,state,clip=None,duration=None,next_state=None,end_speed=0):
        self.state=state
        self.clip=clip or state
        self.elapsed=0
        self.duration=duration if duration is not None else self.DURATIONS.get(state,0)
        if duration is None and self.duration and state in ('happy','eat','groom','face_front','face_side'):
            self.duration*=self.rng.uniform(.96,1.05)
        self.start_speed=self.velocity
        self.end_speed=end_speed
        self.next_state=next_state
        self.pending_plant=None
        self.history.append(state)
        self.history=self.history[-80:]

    def speed_for(self,gait):
        return (165 if gait=='run' else 58)*self.speed_scale

    def stable(self,state):
        self.enter(state)
        if state=='idle':
            self.blink_clock=0
            self.idle_event=None
            self.idle_event_elapsed=0
            self.idle_event_speed=1
            self.next_blink=self.rng.uniform(2.2,5.5)
            self.next_look=self.rng.uniform(5.,13.)
            self.next_paw=self.rng.uniform(13.,28.)
        if state not in ('walk','run'):
            self.velocity=0
        else:
            self.velocity=self.speed_for(state)
            self.phase=0
        if state=='stand':
            self.view='side'
            self.stand_hold=.14

    def route(self):
        if self.state=='sleep':
            if self.goal!='sleep':
                self.enter('wake_up')
            return
        if self.state=='idle':
            if self.idle_event is not None:
                return
            if self.view=='front':
                if self.goal=='happy':
                    self.enter('happy',clip='happy_front')
                elif self.goal!='idle':
                    if self.goal in ('walk','run','play'):
                        self.direction=self.wanted_direction
                    side='right' if self.direction>0 else 'left'
                    self.enter('face_side',clip='face_side_'+side)
                return
            if self.goal in ('idle','happy'):
                side='right' if self.direction>0 else 'left'
                self.enter('face_front',clip='face_front_'+side)
            elif self.goal in ('walk','run','play') or self.wanted_direction!=self.direction:
                self.enter('stand_up')
            elif self.goal=='sleep':
                self.enter('sleep_down')
            elif self.goal in ('eat','groom'):
                self.enter(self.goal)
            return
        if self.state=='stand':
            if self.stand_hold>0:
                return
            if self.wanted_direction!=self.direction:
                self.enter('turn')
            elif self.goal in ('walk','run'):
                self.enter('start',clip='start_'+self.goal,duration=.38,
                           next_state=self.goal,end_speed=self.speed_for(self.goal))
            elif self.goal=='play':
                self.enter('play')
            else:
                self.enter('sit_down')

    def finish_clip(self):
        state=self.state
        if state=='face_front':
            self.view='front'
            self.stable('idle')
        elif state=='face_side':
            self.view='side'
            self.stable('idle')
        elif state in ('stand_up','brake','play','turn'):
            if state=='turn':
                self.direction*=-1
            if state=='play' and self.goal=='play':
                self.goal='idle'
            self.stable('stand')
        elif state in ('sit_down','wake_up','happy','eat','groom'):
            if state!='happy':
                self.view='side'
            if state in ('happy','eat','groom') and self.goal==state:
                self.goal='idle'
            self.stable('idle')
        elif state=='sleep_down':
            self.stable('sleep')
        elif state in ('start','gait_change'):
            gait=self.next_state
            self.stable(gait)

    def step(self,dt):
        dt=max(0,min(.08,dt))
        self.elapsed+=dt
        self.blink_clock+=dt
        self.life_clock+=dt
        if self.state=='idle' and self.view=='front':
            if self.idle_event is not None:
                self.idle_event_elapsed+=dt*self.idle_event_speed
                if self.idle_event_elapsed>=self.idle_event_duration:
                    self.idle_event=None
                    self.idle_event_speed=1
            elif self.goal=='idle':
                if self.blink_clock>=self.next_blink:
                    self.start_idle_event('blink_front',self.rng.uniform(.52,.72))
                    self.next_blink=self.blink_clock+self.rng.uniform(2.8,7.5)
                elif self.blink_clock>=self.next_look:
                    self.start_idle_event('look_front',self.rng.uniform(1.6,2.1))
                    self.next_look=self.blink_clock+self.rng.uniform(8,19)
                elif self.blink_clock>=self.next_paw:
                    self.start_idle_event('paw_front',self.rng.uniform(1.1,1.5))
                    self.next_paw=self.blink_clock+self.rng.uniform(16,32)
        self.stand_hold=max(0,self.stand_hold-dt)
        dx=0.0
        if self.state in ('walk','run'):
            gait=self.state
            self.remaining-=dt
            if self.remaining<=0 and self.goal==gait:
                self.goal='idle'
            wants_change=self.goal!=gait or self.wanted_direction!=self.direction
            if wants_change and self.pending_plant is None:
                self.pending_plant=(math.floor(self.phase*8)+1)
            speed=self.speed_for(gait)*(1+.045*math.sin(self.life_clock*1.7)+.018*math.sin(self.life_clock*3.1))
            self.velocity=speed
            dx=self.direction*speed*dt
            # Walk: 76 world px supported excursion / .66 support fraction.
            # The planted paw's backwards velocity cancels forward travel.
            stride=self.stride_scale*(.50 if gait=='run' else (76/.66/400))
            old_phase=self.phase
            self.phase+=abs(dx)/stride
            if self.pending_plant is not None and math.floor(self.phase*8)>=self.pending_plant:
                anchor=self.pending_plant%8
                if self.goal in ('walk','run') and self.goal!=gait and self.wanted_direction==self.direction:
                    target=self.goal
                    self.enter('gait_change',clip=f'change_{gait}_{anchor}',duration=.28,
                               next_state=target,end_speed=self.speed_for(target))
                else:
                    self.enter('brake',clip=f'brake_{gait}_{anchor}',duration=.70 if gait=='run' else .48)
            else:
                self.phase%=1
                if self.pending_plant is not None and self.phase<old_phase:
                    self.pending_plant-=8
        elif self.state in ('start','gait_change','brake'):
            t=self.elapsed/max(.001,self.duration)
            v=self.start_speed+(self.end_speed-self.start_speed)*smoothstep(t)
            dx=self.direction*(self.velocity+v)*.5*dt
            self.velocity=v
            if self.elapsed>=self.duration:
                self.finish_clip()
        elif self.duration and self.elapsed>=self.duration:
            self.finish_clip()
        self.route()
        return dx

    def pose(self,manifest):
        """Return a clip and its exact baked frame. Connected endpoints are shared."""
        clip=self.clip
        if self.state=='idle':
            if self.view=='front':
                if self.idle_event is not None:
                    clip,t=self.idle_event,min(1,self.idle_event_elapsed/self.idle_event_duration)
                else:
                    clip,t='idle_front',0
            else:
                clock=self.blink_clock%6.8
                if clock>5.4:
                    clip,t='blink',(clock-5.4)/1.4
                else:
                    clip,t='idle',0
        elif self.state in ('walk','run'):
            t=self.phase
        elif self.state=='sleep':
            t=(self.elapsed%4.0)/4.0
        else:
            t=min(1,self.elapsed/max(.001,self.duration))
            # Subtle acceleration and settling at action boundaries. Locomotion
            # retains its distance-driven phase to keep planted feet in sync.
            if self.state in ('sit_down','stand_up','sleep_down','wake_up',
                              'happy','eat','groom','play','turn','face_front','face_side'):
                t=.4*t+.6*smoothstep(t)
        meta=manifest[clip]
        count=meta['count']
        if 'starts' in meta:
            milliseconds=min(meta['duration_ms']-.001,max(0,t*meta['duration_ms']))
            frame=max(0,min(count-1,bisect_right(meta['starts'],milliseconds)-1))
        else:
            frame=min(count-1,int(t*(count if meta['loop'] else max(1,count-1))))
        return clip,frame

    def start_idle_event(self,name='look_front',duration=1.8):
        if self.state=='idle' and self.view=='front':
            self.idle_event=name
            self.idle_event_elapsed=0
            self.idle_event_duration=duration
            self.idle_event_speed=1

    def likely_next_clips(self):
        def seated_side_next():
            if self.goal in ('idle','happy'):
                return ['face_front_right' if self.direction>0 else 'face_front_left']
            if self.goal in ('walk','run','play') or self.wanted_direction!=self.direction:
                return ['stand_up']
            return ['sleep_down' if self.goal=='sleep' else self.goal]
        if self.state=='idle':
            if self.view=='front':
                if self.goal=='happy':return ['happy_front']
                if self.goal!='idle':
                    direction=self.wanted_direction if self.goal in ('walk','run','play') else self.direction
                    return ['face_side_right' if direction>0 else 'face_side_left']
                return [self.idle_event or 'blink_front','happy_front']
            return seated_side_next()
        if self.state=='face_side':return seated_side_next()
        if self.state=='face_front':
            if self.goal=='happy':return ['happy_front']
            if self.goal!='idle':
                direction=self.wanted_direction if self.goal in ('walk','run','play') else self.direction
                return ['face_side_right' if direction>0 else 'face_side_left']
            return ['idle_front']
        if self.state=='stand_up':
            if self.goal in ('walk','run'):return ['start_'+self.goal]
            return ['play'] if self.goal=='play' else ['sit_down']
        if self.state in ('start','gait_change'):return [self.next_state]
        if self.state=='brake':return ['stand','sit_down']
        if self.state=='stand':return ['start_'+self.goal] if self.goal in ('walk','run') else ['sit_down']
        if self.state=='sit_down':return seated_side_next()
        if self.state in ('walk','run'):
            anchor=(math.floor(self.phase*8)+1)%8
            if self.goal in ('walk','run') and self.goal!=self.state:return [f'change_{self.state}_{anchor}']
            return [f'brake_{self.state}_{anchor}']
        if self.state=='sleep_down':return ['sleep']
        if self.state=='sleep':return ['wake_up']
        if self.state=='wake_up':return seated_side_next()
        return ['idle_front']

    def render_direction(self):
        # Front art has asymmetric identity markings and is never mirrored.
        # Turning clips already contain the left/right-specific body rotation.
        if self.view=='front' or self.state in ('face_front','face_side'):
            return 1
        return self.direction
