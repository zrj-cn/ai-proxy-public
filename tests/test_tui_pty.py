"""Real xterm PTY regression: keyboard-only node change and terminal restoration."""
import fcntl
import json
import os
import pathlib
import pty
import select
import signal
import struct
import sys
import tempfile
import termios
import time
import unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from ai_proxy import core as c

class PtyNavigation(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=pathlib.Path(self.tmp.name);config=self.path/'config';config.mkdir(mode=0o700)
        self.config=config
        st={'port':17890,'api_port':19090,'entry':'a1','exit':'b','dev_rules':False,'applications':[]}
        for name,obj in [('settings.json',st),('nodes.json',{'a1':{'type':'trojan','server':'a.example','port':443,'password':'fixture-only-password'},'a3':{'type':'trojan','server':'b.example','port':443,'password':'fixture-only-password'},'b':{'type':'socks5','server':'exit.example','port':1080}}),('subscriptions.json',{'source':{'url':'https://fixture.example','labels':{'a1':'入口示例 01','a3':'入口示例 03'}}}),('custom-rules.json',[])]:
            (config/name).write_text(json.dumps(obj,ensure_ascii=False));(config/name).chmod(0o600)
    def start(self):
        pid,fd=pty.fork()
        if pid==0:
            env=os.environ.copy();env.update(TERM='xterm-256color',LC_ALL='C.UTF-8',AI_PROXY_CONFIG=str(self.config),AI_PROXY_DATA=str(self.path/'data'),AI_PROXY_STATE=str(self.path/'state'))
            # Use actual CLI and disk transaction, mock only application to avoid touching any live service.
            code='from unittest import mock; from ai_proxy import core; from ai_proxy.main import main; p=mock.patch.object(core,"apply"); p.start(); main()'
            os.chdir(ROOT);os.execve(sys.executable,[sys.executable,'-c',code],env)
        self.pid,self.fd=pid,fd;self.raw=b''
        fcntl.ioctl(fd,termios.TIOCSWINSZ,struct.pack('HHHH',24,100,0,0))
        self.before=termios.tcgetattr(fd)[3]
        self.addCleanup(self.close)
        self.wait_text('主菜单')
    def close(self):
        if getattr(self,'pid',None):
            try:os.kill(self.pid,signal.SIGKILL);os.waitpid(self.pid,0)
            except (ProcessLookupError,ChildProcessError):pass
            self.pid=None
        if getattr(self,'fd',None) is not None:os.close(self.fd);self.fd=None
    def drain(self):
        if select.select([self.fd],[],[],.05)[0]:
            try:self.raw+=os.read(self.fd,65536)
            except OSError:pass
    def wait_text(self,text):
        expected=text.encode();end=time.monotonic()+5
        while expected not in self.raw and time.monotonic()<end:self.drain()
        self.assertIn(expected,self.raw,'PTY did not render requested screen')
    def send(self,data):
        self.raw=b'';os.write(self.fd,data);time.sleep(.1)
        self.drain()
    def finish(self):
        end=time.monotonic()+5;status=None
        while time.monotonic()<end:
            got,st=os.waitpid(self.pid,os.WNOHANG)
            if got:status=st;self.pid=None;break
            self.drain()
        self.assertIsNotNone(status,'PTY did not exit')
        flags=termios.tcgetattr(self.fd)[3]
        self.assertTrue(flags&termios.ECHO,'curses did not restore terminal echo')
        self.assertTrue(flags&termios.ICANON,'curses did not restore canonical input')
        self.assertNotIn(b'fixture-only-password',self.raw)
        return status
    def test_choose_fixture_entry_with_only_arrows_and_enter(self):
        self.start()
        self.send(b'\x1b[B\r');self.wait_text('选择入口 A')
        self.send(b'\x1b[B\r');self.wait_text('节点选择已保存')
        self.assertEqual(json.loads((self.config/'settings.json').read_text())['entry'],'a3')
        self.send(b'\r');self.wait_text('主菜单')
        self.send(b'\x1b');self.assertEqual(self.finish(),0)
    def test_rule_categories_and_result_are_readable_in_real_terminal(self):
        self.start()
        self.send(b'\x1b[B'*6+b'\r');self.wait_text('始终代理')
        self.assertIn('始终直连'.encode(),self.raw);self.assertIn('可回退直连'.encode(),self.raw)
        self.send(b'\x1b[B'*3+b'\r');self.wait_text('查询域名')
        self.send(b'\r');self.wait_text('路由策略：')
        self.assertNotIn(b'"priority"',self.raw)
        self.send(b'd');self.wait_text('收起')
        self.send(b'\r');self.wait_text('分流规则')
        self.send(b'\x1b[D');self.wait_text('主菜单')
        self.send(b'\x1b');self.assertEqual(self.finish(),0)

    def test_live_traffic_real_terminal_navigation_resize_and_restore(self):
        self.start()
        self.send(b'\x1b[B'*7+b'\r');self.wait_text('最终目标 → 实际通道')
        self.send(b'\t');self.wait_text('最终目标 → 实际通道')
        self.send(b'\t');self.wait_text('ACTIVITY')
        self.send(b'\t');self.wait_text('直连下载')
        self.send(b' ');self.wait_text('暂停画面')
        self.send(b'\x1b[C');self.wait_text('[完整代理]')
        fcntl.ioctl(self.fd,termios.TIOCSWINSZ,struct.pack('HHHH',18,72,0,0))
        os.kill(self.pid,signal.SIGWINCH)
        self.send(b' ');self.wait_text('实时流量')
        self.send(b'\x1b');self.wait_text('主菜单')
        self.send(b'\x1b');self.assertEqual(self.finish(),0)
        self.assertEqual(json.loads((self.config/'settings.json').read_text())['entry'],'a1')

    def test_ctrl_c_restores_terminal_and_does_not_change_selection(self):
        self.start();os.write(self.fd,b'\x03');self.finish()
        self.assertEqual(json.loads((self.config/'settings.json').read_text())['entry'],'a1')

if __name__=='__main__':unittest.main()
