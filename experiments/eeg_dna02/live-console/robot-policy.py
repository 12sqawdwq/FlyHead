"""No ROS or hardware imports: short leases, exclusive operator, fail closed."""
import math
import secrets

class Arbiter:
    def __init__(self):
        self.owner = None
        self.mode = 'manual'
        self.until = 0.0
        self.command = (0.0, 0.0)
        self.reason = '未使能'
        self.generation = 0

    def stop(self, reason='停止'):
        self.owner = None
        self.until = 0
        self.command = (0.0, 0.0)
        self.reason = reason
        self.generation += 1

    def switch(self, mode):
        if mode not in ('manual', 'eeg'):
            raise ValueError('未知模式')
        self.stop('切换模式，重新使能')
        self.mode = mode

    def enable(self, owner, now, ready, source="manual"):
        self.output(now)
        if self.mode != source:
            raise ValueError('EEG 实车接口尚未启用')
        if not ready:
            raise ValueError('底盘或感知未就绪')
        if self.owner not in (None, owner):
            raise ValueError('其他页面持有控制权')
        self.owner = owner
        self.until = now + .3
        self.command = (0.0, 0.0)
        self.reason = '已使能，等待新指令'

    def drive(self, owner, now, forward, turn, ready, source="manual"):
        self.output(now)
        if self.owner != owner or self.mode != source:
            raise ValueError('未使能或控制权已过期')
        if not ready:
            self.stop('底盘或感知保护停止')
            raise ValueError(self.reason)
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in (forward, turn)):
            self.stop('无效速度')
            raise ValueError(self.reason)
        if abs(forward) > .050001 or abs(turn) > .100001 or (forward and turn):
            self.stop('速度或组合动作超限')
            raise ValueError(self.reason)
        self.command = (float(forward), float(turn))
        self.until = now + .25
        self.reason = '指令已接收'

    def output(self, now):
        if self.owner and now >= self.until:
            self.stop('使能/指令租约过期')
        return self.command

class FreshSession:
    def __init__(self, now):
        self.seq = 0
        self.ticket = secrets.token_hex(16)
        self.issued = now

    def accept(self, packet, now):
        if (type(packet.get('seq')) is not int or packet['seq'] != self.seq + 1
                or packet.get('ticket') != self.ticket or not 0 <= now-self.issued <= .4):
            raise ValueError('指令过期、重放或乱序')
        self.seq += 1
        self.ticket = secrets.token_hex(16)
        self.issued = now

