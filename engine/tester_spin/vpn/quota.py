"""A quota belongs to the verified exit IP, not to a profile filename."""
import ipaddress

class IpQuota:
    def __init__(self,limit):
        if type(limit) is not int or limit<=0:raise ValueError('La cantidad por IP debe ser un entero positivo')
        self.limit=limit;self.counts={}
    def _ip(self,value):return str(ipaddress.ip_address(value))
    def remaining(self,ip):return max(0,self.limit-self.counts.get(self._ip(ip),0))
    def consume(self,ip):
        ip=self._ip(ip)
        if not self.remaining(ip):raise ValueError('Cuota de esta IP agotada')
        self.counts[ip]=self.counts.get(ip,0)+1
