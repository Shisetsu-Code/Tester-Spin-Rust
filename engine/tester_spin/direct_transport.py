"""Shared direct WebSocket lifecycle. A sent command is never retried."""
import time

class CorrelatedSocket:
    def __init__(self, wire, stop_event, timeout_s, *, observe=None, heartbeat_response=None, disconnect_frames=()):
        self.wire=wire;self.stop=stop_event;self.timeout=max(0.001,float(timeout_s));self.observe=observe
        self.heartbeat_response=heartbeat_response or {};self.disconnect_frames=disconnect_frames
    def __enter__(self): return self
    def __exit__(self,*args): self.wire.close()
    def send(self, payload):
        if self.stop.is_set():raise InterruptedError('DETENIDO')
        self.wire.send(payload)
        if self.observe:self.observe('sent',payload)
    def wait(self, accept):
        from websocket import WebSocketTimeoutException
        deadline=time.monotonic()+self.timeout
        while time.monotonic()<deadline:
            if self.stop.is_set():raise InterruptedError('DETENIDO')
            self.wire.settimeout(min(0.25,max(0.001,deadline-time.monotonic())))
            try:payload=self.wire.recv()
            except (TimeoutError,WebSocketTimeoutException):continue
            if payload in ('',None):raise ConnectionError('DEMO_SOCKET_CLOSED')
            if self.observe:self.observe('received',payload)
            if payload in self.heartbeat_response:self.send(self.heartbeat_response[payload]);continue
            if payload in self.disconnect_frames:raise ConnectionError('DEMO_SOCKET_DISCONNECTED')
            if accept(payload):return payload
        raise TimeoutError('DIRECT_RESPONSE_TIMEOUT')
    def exchange(self, payload, accept):
        self.send(payload)
        return self.wait(accept)
