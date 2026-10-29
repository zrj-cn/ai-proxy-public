"""UI behavior: arrows trigger shared actions, cancel never mutates, secrets stay hidden."""
import curses
import pathlib
import sys
import tempfile
import unittest
from unittest import mock
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from ai_proxy import core as c
from ai_proxy import tui

class Screen:
    def __init__(self,keys):self.keys=iter(keys);self.output=[]
    def keypad(self,value):pass
    def getmaxyx(self):return (14,70)
    def erase(self):pass
    def refresh(self):pass
    def timeout(self,value):pass
    def addstr(self,y,x,text,*args):self.output.append(text)
    def get_wch(self):
        try:return next(self.keys)
        except StopIteration:raise curses.error()
    def move(self,*args):pass

class Navigation(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        p=pathlib.Path(self.tmp.name)
        for name,part in [('C','config'),('D','data'),('S','state')]:
            patch=mock.patch.object(c,name,p/part);patch.start();self.addCleanup(patch.stop)
        c.init()
        for name in ['noecho','cbreak','curs_set','set_escdelay']:
            patch=mock.patch.object(curses,name,create=True);patch.start();self.addCleanup(patch.stop)
    def ui(self,keys):return tui.Terminal(Screen(keys))
    def test_arrow_select_and_back_without_typing(self):
        ui=self.ui([curses.KEY_DOWN,'\n',curses.KEY_LEFT])
        self.assertEqual(ui.choose('test',[('one','a'),('two','b')]),'b')
        self.assertIsNone(ui.choose('back',[('one','a')]))
    def test_csi_and_ss3_arrow_sequences(self):
        for seq in ['[B','OB']:
            ui=self.ui(['\x1b',*seq,'\r'])
            self.assertEqual(ui.choose('test',[('one','a'),('two','b')]),'b')
    def test_long_list_page_navigation(self):
        ui=self.ui([curses.KEY_NPAGE,'\n'])
        self.assertEqual(ui.choose('long',[(str(i),i) for i in range(30)]),7)
    def test_password_editing_hidden_in_rendered_output(self):
        secret='private-form-value'
        ui=self.ui(['\x15',*secret,'\n'])
        self.assertEqual(ui.text('password','old',secret=True),secret)
        self.assertNotIn(secret,' '.join(ui.screen.output))
        self.assertNotIn('old',' '.join(ui.screen.output))
    def test_input_cancel_discards_draft(self):
        ui=self.ui(['x','\x1b'])
        self.assertIsNone(ui.text('field','old'))
    def test_current_node_default_and_role_filter(self):
        nodes={'a':{'type':'trojan','server':'a.example','port':443,'password':'private-test'},'b':{'type':'socks5','server':'b.example','port':1080}}
        c.save(c.C/'nodes.json',nodes);st=c.settings();st.update(entry='a',exit='b');c.save(c.C/'settings.json',st)
        c.save(c.C/'subscriptions.json',{'source':{'labels':{'a':'入口示例 03'}}})
        self.assertEqual([key for _,key in tui.node_options('exit')],['b'])
        self.assertIn('入口示例 03',tui.node_options('entry')[0][0])
        ui=self.ui(['\n'])
        with mock.patch.object(ui,'perform') as perform:ui.select_node('entry');perform.assert_not_called()
    def test_node_selection_uses_shared_handler(self):
        c.save(c.C/'nodes.json',{'a':{'type':'socks5'},'b':{'type':'socks5'}})
        st=c.settings();st['entry']='a';c.save(c.C/'settings.json',st)
        ui=self.ui([curses.KEY_DOWN,'\n'])
        with mock.patch.object(ui,'perform') as perform:
            ui.select_node('entry');perform.assert_called_once_with('切换节点',['node','select','entry','b'])
    def test_cancelled_confirmation_is_not_a_service_stop(self):
        ui=self.ui(['\n'])
        self.assertFalse(ui.confirm('stop','停止服务'))
    def test_ctrl_c_exits_without_dispatch(self):
        ui=self.ui(['\x03'])
        with self.assertRaises(KeyboardInterrupt):ui.choose('main',[('one','a')])
    def test_rule_home_has_three_clear_categories(self):
        ui=self.ui([])
        with mock.patch.object(ui,'choose',return_value=None) as choose:
            ui.rules()
        options=choose.call_args[0][1]
        self.assertEqual([v for _,v in options[:3]],['CHAIN','DIRECT','FALLBACK'])
        self.assertIn('失败即停止',options[0][0])
    def test_result_view_uses_chinese_and_keeps_expandable_details(self):
        ui=self.ui([])
        with mock.patch.object(ui,'message') as message:
            self.assertTrue(ui.perform('路由验证',['rule','explain','clau.de']))
        self.assertIn('路由策略：始终代理',message.call_args[0][1])
        self.assertNotIn('"priority"',message.call_args[0][1])
        self.assertIn('来源：',message.call_args[1]['details'])
    def test_semantic_colors_and_no_color_fallback(self):
        with mock.patch.dict('os.environ',{'NO_COLOR':''}),mock.patch.object(curses,'has_colors',return_value=True),mock.patch.object(curses,'start_color'),mock.patch.object(curses,'use_default_colors'),mock.patch.object(curses,'init_pair'),mock.patch.object(curses,'color_pair',side_effect=lambda i:i*100):
            ui=self.ui([])
            self.assertEqual(ui.tone('通过 配置合法'),200)
            self.assertEqual(ui.tone('始终代理'),300)
            self.assertEqual(ui.tone('代理优先 可回退'),400)
            self.assertEqual(ui.tone('失败 请求'),500)
        with mock.patch.dict('os.environ',{'NO_COLOR':'1'}):self.assertEqual(self.ui([]).tone('失败 请求'),0)

    def test_untrusted_labels_cannot_inject_terminal_escape(self):
        self.assertNotIn('\x1b',tui.clean('\x1b[31mnode\nname'))

if __name__=='__main__':unittest.main()
